"""The loop: observe, decide once, verify deterministically, and hand back control when stuck."""

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from urllib.parse import urlsplit

from .browser import actions
from .browser.actions import LIST_ROLES, calendar_control
from .browser.session import Session
from .config import load, redact
from .decide.client import DecisionClient
from .decide.policy import Decision, InvalidDecision, build_questions, build_state, read_answers
from .decide.questions import CANDIDATES, GOAL_ACHIEVED_THRESHOLD
from .errors import Escalated, JevBadResponse, JevError, StalePage, render
from .profile import CATEGORIES, StepTimer
from .runs import write as store_run
from .text import NeedsValue, ValueBinder

logger = logging.getLogger(__name__)

ESCALATION_TEXT_CHARS = 3000
BLANK_PAGE = {"url": "", "title": "", "text": "", "elements": [], "actions": [], "omitted": 0}
NO_PROGRESS_STREAK = 3
STALE_RETRIES = 3
PREV_OK_THRESHOLD = 0.6
# An unconfident DONE re-asked about the same pixels can only repeat itself. The proof the model
# is missing is usually just below the fold - a sort bar under a filter list, a confirmation under
# a form - so look there first, for at most this many viewports, before handing control back.
LOOKS = 1
MAX_LOOKS = 4
# A look has to earn the next one. Confidence that climbs means the page is giving up its answer
# a screen at a time; confidence that does not means the answer is not down there.
LOOK_GAIN = 0.02
# A ref names an element in the observation it came from. When the caller quotes that observation's
# page_key, the ref is only honoured if the page still reads the same; otherwise observe again.
STALE_OBSERVATION = "the page changed since that observation, observe again"
# What a site says when it has decided the caller is a machine. None of it is something a
# decision can act on, and reporting it as BLOCKED says the task was impossible rather than that
# the site would not serve it. Matched lowercased, against everything the opened page says.
WALL_PHRASES = (
    "captcha",
    "접속이 차단",
    "unusual traffic",
    "bots use",
    "access denied",
    # Measured on the first public-benchmark pass: carvana.com answered with Cloudflare's own
    # refusal and marriott.com with Akamai's, and neither said any of the five above.
    "you have been blocked",
    "have permission to access",
)
# A refusal is the whole page. Past this much text the page is about something else and merely
# mentions the word: vercel.com/docs offers "an invisible check instead of a CAPTCHA" six
# thousand characters in, and reading that as a wall costs a task that was working.
WALL_TEXT_CHARS = 1500
# A wall that says nothing at all still says it every time. One thin page is an ordinary login
# form; three opens in a row on one host that answer with nothing is the host answering.
THIN_TEXT_CHARS = 200
THIN_OPENS = 3
# A site's hiccup is the site's, not the task's: the same address a moment later is often the
# working page. One retry is spent before any decision is made on an error answer, and a site
# that is still serving it after that is reported as the site refusing, never as blocked.
SITE_RETRY_S = 2.0
# An error page is a short page, and that is what keeps an article about an outage from reading
# as one. The phrases are what a site says when the number is missing or rewritten.
SITE_ERROR_CHARS = 600
SITE_ERROR_PHRASES = (
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway time-out",
    "too many requests",
    "application error",
    "service temporarily unavailable",
)
# A goal can be an instruction or a question, and a question wants an answer as well as the page
# it is answered on: the leaderboards' own top entries end on one sentence. These are the openings
# a question takes when it does not end in a question mark.
QUESTION_STARTS = ("what", "which", "how many", "when", "who", "find the")
# The page controls a snapshot offers beside the elements, which no input of its own removes.
CONTROL_ACTIONS = ("scroll_down", "scroll_up", "wait")
# An answer nobody is waiting for is worth the moment it takes to price it, and no longer.
DISCARD_WAIT_S = 1.0
# The readings a step's settle takes before the page proves it has stopped moving are usually the
# one it stops on, so each distinct one may ask its question ahead. A page still changing after
# this many is asked about once it has settled, the ordinary way.
LOOKAHEADS = 2


class Speculation:
    """One decision asked while the page was still settling, and the request it answers."""

    def __init__(self, decide, state, questions):
        self.state = state
        self.questions = questions
        self.reply = None
        self.thread = threading.Thread(target=self.ask, args=(decide, state, questions), daemon=True)
        self.thread.start()

    def ask(self, decide, state, questions):
        """Ask in a thread and keep what came back. A speculation that fails is simply no answer.

        Nothing here may raise: this thread's failure is a question that has to be asked again,
        never a run that ends, and a run that ends first closes the client under it.
        """
        try:
            self.reply = decide(state, questions)
        except Exception as error:
            logger.info("A speculative decision went unanswered: %s", error)

    def asks(self, state, questions):
        """Whether this is the request the speculation sent."""
        return (state, questions) == (self.state, self.questions)

    def take(self, state, questions):
        """The prefetched reply, when the settled page asks exactly this, else None.

        Identical questions are not enough: the same question over a different state is a
        different question to ask. What is accepted is the request the settled page would have
        sent, character for character, which is an answer to it and not to a guess.
        """
        if not self.asks(state, questions):
            return None
        self.thread.join()
        return self.reply

    def discard(self, wait=DISCARD_WAIT_S):
        """Wait briefly for a speculation nobody used, and report what it cost anyway."""
        self.thread.join(wait)
        return self.reply.cost if self.reply is not None else 0.0


def speculate(page, action, text):
    """The page as it reads once this input has landed and nothing else has happened, or None.

    Only typing has an effect a guess can get right. The field holds what was typed, a field
    holding something offers the key that submits it, and the page has moved, because the field
    state is part of the marker every reading is compared on. What a click does to a page is
    exactly what the settled reading is for, so a click is not guessed at.
    """
    if action.get("kind") != "fill" or not isinstance(text, str):
        return None
    node = action.get("node")
    elements = [dict(item, value=text) if item.get("node") == node else item for item in page.get("elements", [])]
    offered = [
        item for item in page.get("actions", []) if item["id"] not in CONTROL_ACTIONS and item["kind"] != "press"
    ]
    offered = [dict(item, value=text) if item.get("node") == node else item for item in offered]
    label = next((item.get("label", "") for item in elements if item.get("node") == node), "")
    if text.strip():
        offered.append(
            {
                "id": "press_enter",
                "node": node,
                "kind": "press",
                "key": "Enter",
                "label": f"Press Enter to submit {label or 'the focused field'}",
            }
        )
    controls = [item for item in page.get("actions", []) if item["id"] in CONTROL_ACTIONS]
    return {**page, "elements": elements, "actions": [*offered, *controls]}


# The two operations that can put something new on the page without leaving it.
OPENING = ("CLICK", "TYPE_TEXT")


@dataclass(frozen=True)
class Taken:
    """One executed step: its decision, the page it was taken on, what it typed and what was open."""

    decision: Decision
    before: dict
    text: str | None = None
    opened: dict | None = None

    def entry(self, after):
        """The history line this step leaves once the page reads `after`."""
        return entry(self.decision, self.text, after.get("marker") != self.before.get("marker"))

    def leaves_open(self, after):
        """The list or calendar still open once the page reads `after`, or None."""
        return revealed(self.decision, self.before, after) or suggesting(self.opened, after)


@dataclass
class Result:
    """What one run did: its status, its steps, and what it cost."""

    status: str
    reason: str = ""
    run_id: str = ""
    url: str = ""
    title: str = ""
    http_status: int | None = None
    site_error: bool = False
    final_answer: str | None = None
    steps: list = field(default_factory=list)
    decisions: int = 0
    speculations: int = 0
    prefetched: int = 0
    text_calls: list = field(default_factory=list)
    elapsed_ms: int = 0
    cost: float = 0.0
    final_page: dict = field(default_factory=dict)
    candidates: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def as_dict(self):
        """The result as plain JSON-safe data."""
        return asdict(self)


class Agent:
    """The loop: observe, decide once, verify, and hand control back when stuck."""

    def __init__(self, session=None, config=None, decide=None, client=None, prefetch=True):
        self.config = config or load()
        self.session = session or Session(self.config)
        self.run_id = None
        # A decider that answers from a script rather than from the questions cannot be asked twice.
        self.prefetch = prefetch
        self._client = client
        self._run_id = ""
        if decide is None:
            self._client = client or DecisionClient(self.config)
            decide = self._client.decide
        self.decide = decide

    def identify(self):
        """The id a run carries: the decision session's, or a fresh one for a scripted run."""
        session_id = getattr(self._client, "session_id", "")
        return session_id or uuid.uuid4().hex[:12]

    def open(self, url):
        """Navigate to a url and observe."""
        return self.session.open(url)

    def observe(self):
        """Observe the current page."""
        return self.session.observe()

    def read(self, observe, *args):
        """One observation, retried while the page keeps moving under it, or None."""
        for attempt in range(STALE_RETRIES):
            try:
                return observe(*args)
            except StalePage as error:
                logger.info(
                    "[%s] Page went stale while reading it (%s/%s): %s",
                    self._run_id,
                    attempt + 1,
                    STALE_RETRIES,
                    error,
                )
        return None

    def said(self, error):
        """What an error says and what to do about it, with this run's key taken out of it.

        Nothing the client raises carries the response body today, so nothing carries the key.
        A provider that echoes it back, or a decide callable a host supplies itself, would reach
        the caller through here, and the detail of an escalation is the one place a run hands a
        string it did not write to whoever called it.
        """
        return redact(render(error), self.config.api_key)

    def space(self, page, goal=""):
        """The action space of an observed page, as this goal reads it."""
        return actions.build(page, self.session.max_elements, goal)

    def site(self, page, run, timer=None):
        """The page after one reload when the site answered an error, and the wall still there.

        A decision made on a site's error page is a decision about nothing. Spend one reload on
        it - the site's bad minute should cost a retry, not the task - and report what the reload
        cannot fix as the site refusing, with the status it kept answering with.
        """
        wall = site_error(page)
        if wall is None:
            return page, None
        run.site_error = True
        logger.info("[%s] The site answered %s; reloading once in %s s", run.run_id, wall, SITE_RETRY_S)
        time.sleep(SITE_RETRY_S)
        reloaded = self.read(self.session.reload, timer)
        if reloaded is None:
            return page, wall
        return reloaded, site_error(reloaded)

    def run(self, goal, values=None, max_steps=None, url=None):
        """Pursue a goal until it is done, blocked, escalated or out of budget."""
        started = time.perf_counter()
        budgets = self.config.budgets
        limit = max_steps or budgets.max_steps
        binder = ValueBinder(values, self.config)
        run = _Run(self, goal, binder, started)
        self._run_id = run.run_id
        page = self.read(self.session.open, url) if url else self.read(self.session.observe)
        if page is None:
            return run.escalate("stale", BLANK_PAGE, detail={"error": "The page never settled to be read."})
        wall = run.walled(page)
        if wall:
            return run.escalate("blocked_by_site", page, detail={"wall": wall})
        exclude, stale_retries, looks, reasked = set(), 0, 0, False
        best, waited, reasked_value = 0.0, False, False
        opened = None
        guesses, guessed = [], None
        while True:
            over = run.over_budget(limit, budgets, len(run.steps))
            if over:
                return run.finish("budget", over, page)
            timer = StepTimer()
            with timer.measure("actions"):
                page, wall = self.site(page, run, timer)
                if wall:
                    return run.escalate("blocked_by_site", page, detail={"wall": wall})
                space, state, questions = run.request(page, opened, exclude)
            try:
                with timer.measure("decide"):
                    used, guessed = taken(guesses, state, questions)
                    reply = guessed if guessed is not None else self.decide(state, questions)
            except JevBadResponse as error:
                run.decisions += 1
                if reasked:
                    return run.escalate("invalid_decision", page, detail={"error": self.said(error)})
                logger.warning("[%s] Unusable answer set; asking once more: %s", run.run_id, error)
                reasked = True
                continue
            except JevError as error:
                # A budget is something this run spent and the host can give more of. A provider
                # that will not answer - a rejected key, a dead connection - is neither, and a
                # host told "budget" narrows the goal and buys the same refusal again. Its own
                # reason, with the provider's own words and next step, redacted.
                run.decisions += 1
                return run.escalate("provider_error", page, detail={"error": self.said(error)})
            finally:
                for guess in guesses:
                    run.speculated(guess, guessed if guess is used else None)
                guesses.clear()
            run.decisions += 1
            run.cost += reply.cost
            try:
                decision = read_answers(space, questions, reply)
            except InvalidDecision as error:
                combo = (error.operation, error.target)
                if combo in exclude:
                    return run.escalate("invalid_decision", page, detail={"error": str(error)})
                logger.warning("[%s] Re-asking without %s: %s", run.run_id, combo, error)
                exclude.add(combo)
                continue
            exclude, reasked = set(), False

            if decision.operation == "BLOCKED":
                wanted = unsupplied_field(decision, space, binder, goal)
                if wanted is not None:
                    return run.escalate("needs_value", page, decision, detail=wanted)
                return run.escalate("blocked", page, decision, status="blocked")
            if decision.operation == "DONE":
                if (decision.goal_achieved or 0.0) >= GOAL_ACHIEVED_THRESHOLD:
                    return run.finish("done", "goal_achieved", page, decision)
                score = decision.goal_achieved or 0.0
                spent = looks >= MAX_LOOKS or (looks >= LOOKS and score <= best + LOOK_GAIN)
                look = None if spent else space.controls.get("SCROLL_DOWN")
                # A page that has not finished loading looks exactly like one with nothing more to
                # show, and a search's results land a moment after its page does. When there was
                # nowhere to scroll at all, wait a beat and judge the same goal again before
                # giving up; a look that already ran has given the page the same moment.
                wait = None if look is not None or waited or looks else space.controls.get("WAIT")
                chosen = look if look is not None else wait
                if chosen is None:
                    return run.escalate("unverified_done", page, decision)
                best = max(best, score)
                if look is not None:
                    looks += 1
                    logger.info(
                        "[%s] DONE at %.2f; looking below the fold (%s/%s)", run.run_id, score, looks, MAX_LOOKS
                    )
                else:
                    waited = True
                    logger.info("[%s] DONE at %.2f; waiting for the page to finish loading", run.run_id, score)
                try:
                    self.session.act(chosen, page, timer=timer)
                except StalePage:
                    # The page moved while it was being looked at, which is itself new information.
                    logger.info("[%s] The page moved before it could be looked at; reading it again", run.run_id)
                    page = self.read(self.session.observe, timer) or page
                    continue
                looked = Taken(
                    replace(
                        decision,
                        operation="SCROLL_DOWN" if look is not None else "WAIT",
                        target=chosen["id"],
                        action=chosen,
                    ),
                    page,
                )
                with self.ahead(run, guesses, run.room(limit, budgets), looked):
                    after = self.read(self.session.observe, timer)
                if after is None:
                    return run.escalate(
                        "stale", page, decision, detail={"error": "The page never settled while it was looked at."}
                    )
                page = after
                run.record(looked, page, timer, guessed is not None)
                opened = None
                continue
            looks, best, waited = 0, 0.0, False

            text, value = None, None
            if decision.operation == "TYPE_TEXT":
                try:
                    value = binder.bind(decision.value_name, decision.action, goal, page, run.history)
                except NeedsValue as error:
                    if binder.available() and not reasked_value:
                        # The host has values to spend and the model still found no field for
                        # them: the panel the field lives in may have mounted a beat after the
                        # page was read. Read it again and ask once more before handing the
                        # missing value back to the host.
                        reasked_value = True
                        logger.info("[%s] No field for the supplied values; reading the page again", run.run_id)
                        page = self.read(self.session.observe) or page
                        continue
                    return run.escalate("needs_value", page, decision, detail=error.detail)
                text = value.text
            try:
                self.session.act(decision.action, page, text=text, timer=timer)
            except StalePage as error:
                stale_retries += 1
                if stale_retries > STALE_RETRIES:
                    return run.escalate("stale", page, decision, detail={"error": str(error)})
                logger.info("[%s] Page went stale; re-observing (%s/%s)", run.run_id, stale_retries, STALE_RETRIES)
                page = self.session.observe()
                continue
            stale_retries = 0
            reasked_value = False
            if value is not None:
                # Only now is the value really on the page; a stale retry must not burn it.
                binder.spend(value)
            # The page is about to spend up to a whole settle budget doing whatever it does with
            # that input. Ask the next question now, against the page as it should read once the
            # input has landed and nothing else has happened. If the settled reading would have
            # asked anything else at all, the answer is thrown away and the question asked again.
            room = run.room(limit, budgets)
            pending = speculate(page, decision.action, text) if self.prefetch else None
            if pending is not None and room:
                moves = self.space(pending)
                story = [*run.history, entry(decision, text, True)]
                guesses.append(
                    run.speculating(
                        Speculation(
                            self.decide,
                            build_state(pending, moves, goal, story, binder.available()),
                            build_questions(moves, goal, story, binder.available()),
                        )
                    )
                )

            step = Taken(decision, page, text, opened)
            with self.ahead(run, guesses, room, step):
                after = self.read(self.session.observe, timer)
            if after is None:
                return run.escalate(
                    "stale", page, decision, detail={"error": "The page never settled after that action."}
                )
            before, page = page, after
            run.record(step, page, timer, guessed is not None)
            opened = step.leaves_open(page)
            wall = run.walled(page, before)
            if wall:
                return run.escalate("blocked_by_site", page, decision, detail={"wall": wall})
            stuck = run.stuck(space)
            if stuck:
                return run.escalate(stuck, page, decision)

    @contextmanager
    def ahead(self, run, guesses, room, step=None):
        """Ask the next question from each reading the page gives before it has settled.

        A step's settle reads the page, then waits for it to prove it has stopped moving, and the
        reading it proves is most often the first one that showed the input's effect. The decision
        on that reading is asked while the proving goes on. It is used only when the settled page
        asks the same request, character for character; any other reading is asked about as ever.
        """
        if not self.prefetch or not room:
            yield
            return
        asked = []

        def seen(reading):
            if len(asked) >= LOOKAHEADS:
                return
            _space, state, questions = run.request(reading, step=step)
            if any(guess.asks(state, questions) for guess in guesses):
                return
            asked.append(reading)
            guesses.append(run.speculating(Speculation(self.decide, state, questions)))

        self.session.preview = seen
        try:
            yield
        finally:
            self.session.preview = None

    def act(self, instruction, values=None, max_steps=1):
        """One decided step towards an instruction."""
        return self.run(instruction, values=values, max_steps=max_steps)

    def click(self, ref, page_key=None):
        """Click one observed element by its ref, without asking the model."""
        return self.direct(ref, "click", page_key=page_key)

    def type(self, ref, text, page_key=None):
        """Type into one observed field by its ref, without asking the model."""
        return self.direct(ref, "fill", text=text, page_key=page_key)

    def select(self, ref, option, page_key=None):
        """Select an observed dropdown option, without asking the model."""
        return self.direct(ref, "select", option=option, page_key=page_key)

    def scroll(self, direction="down"):
        """Scroll one viewport step, without asking the model."""
        return self.control(f"scroll_{direction}")

    def wait(self):
        """Wait a moment and observe again."""
        return self.control("wait")

    def press(self, key):
        """Press a key and observe again, through the check a decided press already gets.

        Enter lands on whatever holds focus, so a snapshot offers it only as `press_enter` naming
        the field it would submit, and acting on that action re-checks the field right before the
        key goes out. A direct press used to skip all of it and send the key into the void.
        Escape and Tab name no field and submit nothing, so there is nothing for them to check.
        """
        page = self.session.observe()
        action = next((a for a in page["actions"] if a["kind"] == "press" and a.get("key") == key), None)
        if action is not None:
            self.session.act(action, page)
            return self.session.observe()
        if key == "Enter":
            raise Escalated("Nothing is focused, so Enter has nothing to submit.")
        self.session.press(key)
        return self.session.observe()

    def direct(self, ref, kind, text=None, option=None, page_key=None):
        """Execute one observed action chosen by ref, not by the model."""
        page = self.session.observe()
        if page_key is not None and page.get("page_key") != page_key:
            raise StalePage(STALE_OBSERVATION)
        candidates = [a for a in page["actions"] if a["id"] == ref and a["kind"] == kind]
        if kind == "select":
            candidates = [a for a in candidates if option in (a.get("value"), a.get("label", "").split(" → ")[-1])]
        if not candidates:
            raise LookupError(f"No {kind} action for {ref} on this page")
        self.session.act(candidates[0], page, text=text)
        return self.session.observe()

    def control(self, name):
        """Execute one page control such as scroll or wait."""
        page = self.session.observe()
        action = next((a for a in page["actions"] if a["id"] == name), None)
        if action is None:
            raise LookupError(f"{name} is not offered on this page")
        self.session.act(action, page)
        return self.session.observe()

    def close(self):
        """Close the session and the decision client this agent owns."""
        self.session.close()
        if self._client is not None:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class _Run:
    """Per-run bookkeeping: history, budgets, verification and the Result it ends with."""

    def __init__(self, agent, goal, binder, started):
        self.agent = agent
        # A host that already named this run - `jev-ra serve` logs the id before the tools run -
        # spends that name here, so its log line and the stored run are the same run.
        self.run_id = agent.run_id or agent.identify()
        agent.run_id = None
        self.goal = goal
        self.binder = binder
        self.started = started
        self.history = []
        self.steps = []
        self.decisions = 0
        self.speculations = 0
        self.prefetched = 0
        self.pending = []
        self.cost = 0.0
        self.opens = ()
        self.site_error = False

    def elapsed_ms(self):
        """Milliseconds since the run started."""
        return round((time.perf_counter() - self.started) * 1000)

    def room(self, limit, budgets):
        """Whether this run could still take another step, which is what a speculation is for."""
        return self.over_budget(limit, budgets, len(self.steps) + 1) is None

    def speculating(self, guess):
        """Hold the speculation in flight, so a run that ends before it lands still pays for it."""
        self.pending.append(guess)
        return guess

    def speculated(self, guess, used):
        """Count one speculation, and charge a discarded one to the run that paid for it."""
        if guess in self.pending:
            self.pending.remove(guess)
        self.speculations += 1
        if used is not None:
            self.prefetched += 1
            return
        self.cost += guess.discard()

    def over_budget(self, limit, budgets, taken):
        """The budget this run has exhausted, or None."""
        if taken >= limit:
            return f"max_steps ({limit}) reached"
        if self.decisions >= budgets.max_decisions:
            return f"max_decisions ({budgets.max_decisions}) reached"
        if self.elapsed_ms() >= budgets.timeout_s * 1000:
            return f"timeout_s ({budgets.timeout_s}) reached"
        return None

    def request(self, page, opened=None, exclude=(), step=None):
        """The action space, state and questions the next decision sends about this page.

        The loop asks it of the page a step settled on, once the step is recorded. A lookahead asks
        it of an earlier reading, before the step is recorded, and passes the step: its history line
        and what it left open are taken from that reading exactly as the loop will take them.
        """
        story = self.history
        if step is not None:
            story, opened = [*story, step.entry(page)], step.leaves_open(page)
        space = self.agent.space(page, self.goal)
        values = self.binder.available()
        state = build_state(page, space, self.goal, story, values, opened)
        return space, state, build_questions(space, self.goal, story, values, exclude, opened)

    def record(self, step, after, timer=None, prefetched=False):
        """Record one executed step and what the page did about it."""
        decision, before, line = step.decision, step.before, step.entry(after)
        changed = line["page_changed"]
        profile = timer.result() if timer is not None else dict.fromkeys((*CATEGORIES, "total_ms"), 0)
        self.steps.append(
            {
                **profile,
                "n": len(self.steps) + 1,
                "prefetched": prefetched,
                "operation": decision.operation,
                "target": decision.target,
                "target_label": decision.action.get("label", ""),
                "kind": decision.action.get("kind", ""),
                "text": step.text,
                "probability": decision.probability,
                "confidence": decision.confidence,
                "latency_ms": decision.latency_ms,
                "page_changed": changed,
                "prev_ok": decision.prev_ok,
                "url": after.get("url", ""),
                "verified": verification(before, after),
            }
        )
        self.history.append(line)

    def walled(self, page, before=None):
        """How this site is refusing to serve the machine, or an empty string.

        A refusal in the page's own words counts wherever it is read, as long as the refusal is
        all the page says: a challenge that replaces the page after a click is the same wall as
        one served on arrival, and a documentation page about bot protection is neither. Saying
        nothing counts only on a page the run opened, because a wall answers every fresh address
        that way, while a page the run is still working on says nothing about the host either way.
        """
        text = page_text(page)
        said = text.strip()
        if len(said) < WALL_TEXT_CHARS:
            # A refusal that speaks only in the tab's name is still the host refusing: Akamai
            # titles the page "Access Denied" and gives it an edge reference number for a body.
            lowered = f"{page.get('title', '')}\n{text}".lower()
            phrase = next((phrase for phrase in WALL_PHRASES if phrase in lowered), "")
            if phrase:
                return f"the page answered with {phrase!r}"
        url = page.get("url", "")
        if before is not None and url == before.get("url", ""):
            return ""
        host = urlsplit(url).hostname or ""
        if not host or len(said) >= THIN_TEXT_CHARS:
            self.opens = ()
            return ""
        self.opens = (*self.opens, host) if not self.opens or self.opens[-1] == host else (host,)
        if len(self.opens) < THIN_OPENS:
            return ""
        return f"{host} answered {THIN_OPENS} opens with under {THIN_TEXT_CHARS} characters"

    def stuck(self, space):
        """The escalation reason if the run is going nowhere, else None."""
        recent = self.steps[-NO_PROGRESS_STREAK:]
        if len(recent) < NO_PROGRESS_STREAK:
            return None
        # prev_ok only breaks the tie when the deterministic check saw nothing happen.
        stalled = [
            step
            for step in recent
            if step["kind"] != "wait"
            and not step["page_changed"]
            and (step["prev_ok"] is None or step["prev_ok"] < PREV_OK_THRESHOLD)
        ]
        if len(stalled) == NO_PROGRESS_STREAK:
            return "too_many_controls" if space.omitted else "stuck_loop"
        recent_choices = {(step["operation"], step["target"]) for step in recent}
        # Scrolling is how a page is read, so three scrolls in a row are progress, not a loop;
        # a scroll that moves nothing is already caught above.
        if len(recent_choices) == 1 and recent[-1]["operation"] not in {"SCROLL_DOWN", "SCROLL_UP"}:
            return "stuck_loop"
        return None

    def final_page(self, page):
        """The page text and element table the caller gets back."""
        space = self.agent.space(page)
        return {
            "text": page_text(page),
            "elements": [actions.element_view(element) for element in space.elements],
            "omitted": space.omitted,
        }

    def answer(self, page):
        """One sentence for a question-shaped goal, and why there is none when there is not."""
        if not question_shaped(self.goal):
            return None, ""
        return self.binder.answer(self.goal, page)

    def result(self, status, reason, page, decision=None, detail=None):
        """Assemble the Result for this run and store it under its id."""
        detail = dict(detail or {})
        final_answer, unanswered = self.answer(page)
        if unanswered:
            detail["final_answer"] = unanswered
        for guess in list(self.pending):
            self.speculated(guess, None)
        result = Result(
            status=status,
            reason=reason,
            run_id=self.run_id,
            url=page.get("url", ""),
            title=page.get("title", ""),
            http_status=page.get("http_status"),
            site_error=self.site_error,
            final_answer=final_answer,
            steps=self.steps,
            decisions=self.decisions,
            speculations=self.speculations,
            prefetched=self.prefetched,
            text_calls=self.binder.calls,
            elapsed_ms=self.elapsed_ms(),
            cost=round(self.cost, 6),
            final_page=self.final_page(page),
            candidates=decision.candidates[:CANDIDATES] if decision else [],
            detail=detail,
        )
        store_run(result)
        return result

    def finish(self, status, reason, page, decision=None):
        """End the run with a terminal status."""
        return self.result(status, reason, page, decision)

    def escalate(self, reason, page, decision=None, detail=None, status="escalate"):
        """End the run and hand back what the host needs to decide."""
        detail = dict(detail or {})
        detail["page_text"] = page.get("text", "")[:ESCALATION_TEXT_CHARS]
        return self.result(status, reason, page, decision, detail)


def taken(guesses, state, questions):
    """The speculation that sent exactly this request and has its answer, and that answer."""
    for guess in guesses:
        reply = guess.take(state, questions)
        if reply is not None:
            return guess, reply
    return None, None


def question_shaped(goal):
    """Whether this goal reads as a question rather than an instruction."""
    said = " ".join(goal.split()).lower()
    if not said:
        return False
    if said.endswith("?"):
        return True
    return said in QUESTION_STARTS or said.startswith(tuple(f"{start} " for start in QUESTION_STARTS))


def entry(decision, text, changed):
    """One line of the history a decision is given: what was done and whether the page moved."""
    return {
        "action": decision.action.get("label", ""),
        "kind": decision.action.get("kind", ""),
        "text": text,
        "page_changed": changed,
    }


def unsupplied_field(decision, space, binder, goal):
    """The field a BLOCKED page wanted filled, when nothing was supplied to fill it with.

    A login wall is not blocked; it is waiting for a credential the caller has and jev-ra does
    not. The model says so itself by ranking typing second behind BLOCKED, so the escalation
    that helps the host agent is needs_value with the field named, not a dead end.
    """
    if binder.available():
        return None
    runner_up = next((candidate for candidate in decision.candidates[1:2]), None)
    if runner_up is None or runner_up["operation"] != "TYPE_TEXT":
        return None
    action = space.targets.get("TYPE_TEXT", {}).get(runner_up["target"])
    if action is None:
        return None
    return NeedsValue(action, goal, "the page needs a value that was not supplied").detail


def revealed(decision, before, after):
    """What a step opened: the control itself, and the controls that came up under it.

    A click that changed the address opened a page, not a panel, and one that added nothing
    opened nothing at all. Typing opens something only when suggestions came up for it, which is
    what an autocomplete does and what an ordinary field does not. Node ids outlive a reading of
    the page, so what is new is what was not there a moment ago.
    """
    if decision.operation not in OPENING or not decision.action:
        return None
    if before.get("url") != after.get("url"):
        return None
    was = {element.get("node") for element in before.get("elements") or ()}
    fresh = [element for element in after.get("elements") or () if element.get("node") not in was]
    if not fresh:
        return None
    controls = {element.get("node") for element in fresh}
    dates = [element for element in fresh if calendar_control(element)]
    if len(dates) >= 2:
        opener = next(
            (element for element in before.get("elements") or () if element.get("node") == decision.action.get("node")),
            {},
        )
        return {
            "node": decision.action.get("node"),
            "controls": controls,
            "calendar": True,
            "label": opener.get("label", ""),
        }
    if any(element.get("role") in LIST_ROLES for element in fresh):
        # Options that were not there a moment ago are the whole evidence. Counting the page's
        # actions is not: a second origin field opens its own list as the first one's closes, and
        # the page ends the step offering exactly as many things as it did before.
        return {"node": decision.action.get("node"), "controls": controls, "listbox": True}
    if decision.operation == "TYPE_TEXT":
        return None
    if len(after.get("actions") or ()) <= len(before.get("actions") or ()):
        return None
    return {"node": decision.action.get("node"), "controls": controls, "listbox": False}


def suggesting(opened, page):
    """The list or calendar an earlier step opened, while its controls remain on the page.

    A list or calendar stays open across the steps that read it, and its opener stays the wrong
    thing to press for exactly that long. What proves it is still open is the controls it exposed:
    once one is chosen, they disappear and the field is an ordinary control again.
    """
    if not opened or not (opened.get("listbox") or opened.get("calendar")):
        return None
    shown = (
        {element.get("node") for element in page.get("elements") or () if calendar_control(element)}
        if opened.get("calendar")
        else {element.get("node") for element in page.get("elements") or () if element.get("role") in LIST_ROLES}
    )
    return opened if opened["controls"] & shown else None


def page_text(page):
    """What the page says: the part a reader can see, then whatever the document holds below it."""
    seen = page.get("text") or ""
    whole = page.get("doc_text") or ""
    if not whole:
        return seen
    if not seen:
        return whole
    shown = set(seen.split("\n"))
    return "\n".join([seen, *(line for line in whole.split("\n") if line not in shown)])


def site_error(page):
    """The wall a site's own error answer is, or None.

    A status of 5xx or 429 is the site saying it could not serve this request. A short page that
    says so in words is the same answer when the number is missing or was rewritten, and the
    length limit is what keeps an article about an outage from reading as one.
    """
    status = page.get("http_status")
    if isinstance(status, int) and (status >= 500 or status == 429):
        return f"http {status}"
    said = f"{page.get('title', '')}\n{page_text(page)}".lower()
    if len(said) <= SITE_ERROR_CHARS:
        phrase = next((phrase for phrase in SITE_ERROR_PHRASES if phrase in said), "")
        if phrase:
            return f"the page answered {phrase!r}"
    return None


def verification(before, after):
    """What the deterministic check saw change; it outranks the model's own prev_ok."""
    return {
        "url": before.get("url") != after.get("url"),
        "title": before.get("title") != after.get("title"),
        "text": before.get("text") != after.get("text"),
        "fields": field_state(before) != field_state(after),
    }


def field_state(page):
    """The field-value part of a page key, or None."""
    key = page.get("page_key") or []
    return key[6] if len(key) > 6 else None
