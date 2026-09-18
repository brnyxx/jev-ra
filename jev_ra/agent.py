"""The loop: observe, decide once, verify deterministically, and hand back control when stuck."""

import logging
import time
from dataclasses import asdict, dataclass, field

from .browser import actions
from .browser.session import Session, StalePage
from .config import load
from .decide.client import DecisionClient, JevInvalidResponse
from .decide.policy import InvalidDecision, build_questions, build_state, read_answers
from .decide.questions import CANDIDATES, GOAL_ACHIEVED_THRESHOLD
from .text import NeedsValue, ValueBinder

logger = logging.getLogger(__name__)

ESCALATION_TEXT_CHARS = 3000
NO_PROGRESS_STREAK = 3
STALE_RETRIES = 3
PREV_OK_THRESHOLD = 0.6


@dataclass
class Result:
    status: str
    reason: str = ""
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
        return asdict(self)


class Agent:
    def __init__(self, session=None, config=None, decide=None, client=None):
        self.config = config or load()
        self.session = session or Session(self.config)
        self._client = client
        if decide is None:
            self._client = client or DecisionClient(self.config)
            decide = self._client.decide
        self.decide = decide

    def open(self, url):
        return self.session.open(url)

    def observe(self):
        return self.session.observe()

    def space(self, page):
        return actions.build(page, self.session.max_elements)

    def run(self, goal, values=None, max_steps=None, url=None):
        started = time.perf_counter()
        budgets = self.config.budgets
        limit = max_steps or budgets.max_steps
        binder = ValueBinder(values, self.config)
        run = _Run(self, goal, binder, started)
        page = self.session.open(url) if url else self.session.observe()
        exclude, stale_retries, unverified, reasked = set(), 0, False, False
        while True:
            over = run.over_budget(limit, budgets, len(run.steps))
            if over:
                return run.finish("budget", over, page)
            space = self.space(page)
            questions = build_questions(space, goal, run.history, binder.available(), exclude)
            state = build_state(page, space, goal, run.history, binder.available())
            try:
                reply = self.decide(state, questions)
            except JevInvalidResponse as error:
                run.decisions += 1
                if reasked:
                    return run.escalate("invalid_decision", page, detail={"error": str(error)})
                logger.warning("Unusable answer set; asking once more: %s", error)
                reasked = True
                continue
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
                return run.escalate("blocked", page, decision, status="blocked")
            if decision.operation == "DONE":
                if (decision.goal_achieved or 0.0) >= GOAL_ACHIEVED_THRESHOLD:
                    return run.finish("done", "goal_achieved", page, decision)
                if unverified:
                    return run.escalate("unverified_done", page, decision)
                unverified = True
                continue
            unverified = False

            text = None
            if decision.operation == "TYPE_TEXT":
                try:
                    value = binder.bind(decision.value_name, decision.action, goal, page, run.history)
                except NeedsValue as error:
                    return run.escalate("needs_value", page, decision, detail=error.detail)
                text = value.text
            try:
                self.session.act(decision.action, page, text=text)
            except StalePage as error:
                stale_retries += 1
                if stale_retries > STALE_RETRIES:
                    return run.escalate("stale", page, decision, detail={"error": str(error)})
                logger.info("Page went stale; re-observing (%s/%s)", stale_retries, STALE_RETRIES)
                page = self.session.observe()
                continue
            stale_retries = 0

            before, page = page, self.session.observe()
            run.record(decision, before, page, text)
            stuck = run.stuck(space)
            if stuck:
                return run.escalate(stuck, page, decision)

    def act(self, instruction, values=None, max_steps=1):
        return self.run(instruction, values=values, max_steps=max_steps)

    def click(self, ref):
        return self.direct(ref, "click")

    def type(self, ref, text):
        return self.direct(ref, "fill", text=text)

    def select(self, ref, option):
        return self.direct(ref, "select", option=option)

    def scroll(self, direction="down"):
        return self.control(f"scroll_{direction}")

    def wait(self):
        return self.control("wait")

    def press(self, key):
        self.session.press(key)
        return self.session.observe()

    def direct(self, ref, kind, text=None, option=None):
        page = self.session.observe()
        candidates = [a for a in page["actions"] if a["id"] == ref and a["kind"] == kind]
        if kind == "select":
            candidates = [a for a in candidates if option in (a.get("value"), a.get("label", "").split(" → ")[-1])]
        if not candidates:
            raise LookupError(f"No {kind} action for {ref} on this page")
        self.session.act(candidates[0], page, text=text)
        return self.session.observe()

    def control(self, name):
        page = self.session.observe()
        action = next((a for a in page["actions"] if a["id"] == name), None)
        if action is None:
            raise LookupError(f"{name} is not offered on this page")
        self.session.act(action, page)
        return self.session.observe()

    def close(self):
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
        self.goal = goal
        self.binder = binder
        self.started = started
        self.history = []
        self.steps = []
        self.decisions = 0
        self.cost = 0.0

    def elapsed_ms(self):
        return round((time.perf_counter() - self.started) * 1000)

    def over_budget(self, limit, budgets, taken):
        if taken >= limit:
            return f"max_steps ({limit}) reached"
        if self.decisions >= budgets.max_decisions:
            return f"max_decisions ({budgets.max_decisions}) reached"
        if self.elapsed_ms() >= budgets.timeout_s * 1000:
            return f"timeout_s ({budgets.timeout_s}) reached"
        return None

    def record(self, decision, before, after, text):
        changed = after.get("marker") != before.get("marker")
        self.steps.append(
            {
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
        if len({(step["operation"], step["target"]) for step in recent}) == 1:
            return "stuck_loop"
        return None

    def final_page(self, page):
        space = self.agent.space(page)
        return {
            "text": page.get("text", ""),
            "elements": [actions.element_view(element) for element in space.elements],
            "omitted": space.omitted,
        }

    def result(self, status, reason, page, decision=None, detail=None):
        return Result(
            status=status,
            reason=reason,
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

    def finish(self, status, reason, page, decision=None):
        return self.result(status, reason, page, decision)

    def escalate(self, reason, page, decision=None, detail=None, status="escalate"):
        detail = dict(detail or {})
        detail["page_text"] = page.get("text", "")[:ESCALATION_TEXT_CHARS]
        return self.result(status, reason, page, decision, detail)


def verification(before, after):
    """What the deterministic check saw change; it outranks the model's own prev_ok."""
    return {
        "url": before.get("url") != after.get("url"),
        "title": before.get("title") != after.get("title"),
        "text": before.get("text") != after.get("text"),
        "fields": field_state(before) != field_state(after),
    }


def field_state(page):
    key = page.get("page_key") or []
    return key[6] if len(key) > 6 else None
