"""The loop: observe, decide once, verify deterministically, and hand back control when stuck."""

import logging
import time
from dataclasses import asdict, dataclass, field, replace

from .browser import actions
from .browser.session import Session
from .config import load, redact
from .decide.client import DecisionClient
from .decide.policy import InvalidDecision, build_questions, build_state, read_answers
from .decide.questions import CANDIDATES, GOAL_ACHIEVED_THRESHOLD
from .errors import Escalated, JevBadResponse, JevError, StalePage, render
from .profile import CATEGORIES, StepTimer
from .runs import new_id
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


@dataclass
class Result:
    """What one run did: its status, its steps, and what it cost."""

    status: str
    reason: str = ""
    run_id: str = ""
    url: str = ""
    title: str = ""
    steps: list = field(default_factory=list)
    decisions: int = 0
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

    def __init__(self, session=None, config=None, decide=None, client=None):
        self.config = config or load()
        self.session = session or Session(self.config)
        self.run_id = None
        self._client = client
        if decide is None:
            self._client = client or DecisionClient(self.config)
            decide = self._client.decide
        self.decide = decide

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
                logger.info("Page went stale while reading it (%s/%s): %s", attempt + 1, STALE_RETRIES, error)
        return None

    def said(self, error):
        """What an error says and what to do about it, with this run's key taken out of it.

        Nothing the client raises carries the response body today, so nothing carries the key.
        A provider that echoes it back, or a decide callable a host supplies itself, would reach
        the caller through here, and the detail of an escalation is the one place a run hands a
        string it did not write to whoever called it.
        """
        return redact(render(error), self.config.api_key)

    def space(self, page):
        """The action space of an observed page."""
        return actions.build(page, self.session.max_elements)

    def run(self, goal, values=None, max_steps=None, url=None):
        """Pursue a goal until it is done, blocked, escalated or out of budget."""
        started = time.perf_counter()
        budgets = self.config.budgets
        limit = max_steps or budgets.max_steps
        binder = ValueBinder(values, self.config)
        run = _Run(self, goal, binder, started)
        page = self.read(self.session.open, url) if url else self.read(self.session.observe)
        if page is None:
            return run.escalate("stale", BLANK_PAGE, detail={"error": "The page never settled to be read."})
        exclude, stale_retries, looks, reasked = set(), 0, 0, False
        best, waited, reasked_value = 0.0, False, False
        while True:
            over = run.over_budget(limit, budgets, len(run.steps))
            if over:
                return run.finish("budget", over, page)
            timer = StepTimer()
            with timer.measure("actions"):
                space = self.space(page)
                questions = build_questions(space, goal, run.history, binder.available(), exclude)
                state = build_state(page, space, goal, run.history, binder.available())
            try:
                with timer.measure("decide"):
                    reply = self.decide(state, questions)
            except JevBadResponse as error:
                run.decisions += 1
                if reasked:
                    return run.escalate("invalid_decision", page, detail={"error": self.said(error)})
                logger.warning("Unusable answer set; asking once more: %s", error)
                reasked = True
                continue
            except JevError as error:
                # A budget is something this run spent and the host can give more of. A provider
                # that will not answer - a rejected key, a dead connection - is neither, and a
                # host told "budget" narrows the goal and buys the same refusal again. Its own
                # reason, with the provider's own words and next step, redacted.
                run.decisions += 1
                return run.escalate("provider_error", page, detail={"error": self.said(error)})
            run.decisions += 1
            run.cost += reply.cost
            try:
                decision = read_answers(space, questions, reply)
            except InvalidDecision as error:
                combo = (error.operation, error.target)
                if combo in exclude:
                    return run.escalate("invalid_decision", page, detail={"error": str(error)})
                logger.warning("Re-asking without %s: %s", combo, error)
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
                if look is None and wait is None:
                    return run.escalate("unverified_done", page, decision)
                best = max(best, score)
                if look is not None:
                    looks += 1
                    logger.info("DONE at %.2f; looking below the fold (%s/%s)", score, looks, MAX_LOOKS)
                else:
                    waited = True
                    logger.info("DONE at %.2f; waiting for the page to finish loading", score)
                chosen = look if look is not None else wait
                if chosen is None:
                    return run.escalate("unverified_done", page, decision)
                try:
                    self.session.act(chosen, page, timer=timer)
                except StalePage:
                    # The page moved while it was being looked at, which is itself new information.
                    logger.info("The page moved before it could be looked at; reading it again")
                    page = self.read(self.session.observe, timer) or page
                    continue
                after = self.read(self.session.observe, timer)
                if after is None:
                    return run.escalate(
                        "stale", page, decision, detail={"error": "The page never settled while it was looked at."}
                    )
                before, page = page, after
                run.record(
                    replace(
                        decision,
                        operation="SCROLL_DOWN" if look is not None else "WAIT",
                        target=chosen["id"],
                        action=chosen,
                    ),
                    before,
                    page,
                    None,
                    timer,
                )
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
                        logger.info("No field for the supplied values; reading the page again")
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
                logger.info("Page went stale; re-observing (%s/%s)", stale_retries, STALE_RETRIES)
                page = self.session.observe()
                continue
            stale_retries = 0
            reasked_value = False
            if value is not None:
                # Only now is the value really on the page; a stale retry must not burn it.
                binder.spend(value)

            after = self.read(self.session.observe, timer)
            if after is None:
                return run.escalate(
                    "stale", page, decision, detail={"error": "The page never settled after that action."}
                )
            before, page = page, after
            run.record(decision, before, page, text, timer)
            stuck = run.stuck(space)
            if stuck:
                return run.escalate(stuck, page, decision)

    def act(self, instruction, values=None, max_steps=1):
        """One decided step towards an instruction."""
        return self.run(instruction, values=values, max_steps=max_steps)

    def click(self, ref):
        """Click one observed element by its ref, without asking the model."""
        return self.direct(ref, "click")

    def type(self, ref, text):
        """Type into one observed field by its ref, without asking the model."""
        return self.direct(ref, "fill", text=text)

    def select(self, ref, option):
        """Select an observed dropdown option, without asking the model."""
        return self.direct(ref, "select", option=option)

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

    def direct(self, ref, kind, text=None, option=None):
        """Execute one observed action chosen by ref, not by the model."""
        page = self.session.observe()
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
        self.run_id = agent.run_id or new_id()
        agent.run_id = None
        self.goal = goal
        self.binder = binder
        self.started = started
        self.history = []
        self.steps = []
        self.decisions = 0
        self.cost = 0.0

    def elapsed_ms(self):
        """Milliseconds since the run started."""
        return round((time.perf_counter() - self.started) * 1000)

    def over_budget(self, limit, budgets, taken):
        """The budget this run has exhausted, or None."""
        if taken >= limit:
            return f"max_steps ({limit}) reached"
        if self.decisions >= budgets.max_decisions:
            return f"max_decisions ({budgets.max_decisions}) reached"
        if self.elapsed_ms() >= budgets.timeout_s * 1000:
            return f"timeout_s ({budgets.timeout_s}) reached"
        return None

    def record(self, decision, before, after, text, timer=None):
        """Record one executed step and what the page did about it."""
        changed = after.get("marker") != before.get("marker")
        profile = timer.result() if timer is not None else dict.fromkeys((*CATEGORIES, "total_ms"), 0)
        self.steps.append(
            {
                **profile,
                "n": len(self.steps) + 1,
                "operation": decision.operation,
                "target": decision.target,
                "target_label": decision.action.get("label", ""),
                "kind": decision.action.get("kind", ""),
                "text": text,
                "probability": decision.probability,
                "confidence": decision.confidence,
                "latency_ms": decision.latency_ms,
                "page_changed": changed,
                "prev_ok": decision.prev_ok,
                "url": after.get("url", ""),
                "verified": verification(before, after),
            }
        )
        self.history.append(
            {
                "action": decision.action.get("label", ""),
                "kind": decision.action.get("kind", ""),
                "text": text,
                "page_changed": changed,
            }
        )

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

    def result(self, status, reason, page, decision=None, detail=None):
        """Assemble the Result for this run and store it under its id."""
        result = Result(
            status=status,
            reason=reason,
            run_id=self.run_id,
            url=page.get("url", ""),
            title=page.get("title", ""),
            steps=self.steps,
            decisions=self.decisions,
            text_calls=self.binder.calls,
            elapsed_ms=self.elapsed_ms(),
            cost=round(self.cost, 6),
            final_page=self.final_page(page),
            candidates=decision.candidates[:CANDIDATES] if decision else [],
            detail=detail or {},
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
