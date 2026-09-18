"""Build one request's questions, then read the answers back into an executable decision."""

import json
from dataclasses import dataclass, field

from ..browser.actions import element_view
from .questions import (
    CANDIDATES,
    GOAL_ACHIEVED,
    GOAL_ACHIEVED_CRITERIA,
    NEXT_ACTION,
    NONE_VALUE,
    NONE_VALUE_LABEL,
    OPERATION_LABELS,
    PAGE_TEXT_CHARS,
    PREV_OK,
    PREV_OK_CRITERIA,
    RECENT_ACTIONS,
    TARGET,
    TERMINAL,
    VALUE_FOR_FIELD,
    VALUE_PREVIEW_CHARS,
)


class InvalidDecision(Exception):
    """The answered operation/target pair cannot be executed on the observed page."""

    def __init__(self, operation, target, reason):
        super().__init__(f"{operation}{'/' + target if target else ''}: {reason}")
        self.operation = operation
        self.target = target


@dataclass(frozen=True)
class Decision:
    """What one answer set means: an operation, a target, and the confidence behind it."""

    operation: str
    target: str | None = None
    action: dict | None = None
    probability: float = 0.0
    confidence: float = 0.0
    value_name: str | None = None
    prev_ok: float | None = None
    goal_achieved: float | None = None
    latency_ms: int = 0
    cost: float = 0.0
    candidates: list = field(default_factory=list)

    @property
    def terminal(self):
        """Whether this decision ends the run rather than moving the browser."""
        return self.operation in TERMINAL


def question_name(operation):
    """The target question that belongs to an operation."""
    return operation.lower() + "_target"


def instructions(goal, rules, **extra):
    """The goal and the measured rules, as the one string both endpoints accept."""
    # One string on both endpoints: OpenRouter rejects structured instructions.
    return json.dumps({"goal": goal, **extra, "rules": rules}, ensure_ascii=False)


def choice(criteria, text):
    """A choice question over the given criteria."""
    return {"type": "choice", "criteria": criteria, "instructions": text}


def noul(criteria, text):
    """A noul question over the given criteria."""
    return {"type": "noul", "criteria": criteria, "instructions": text}


def preview(value):
    """A value shortened to fit one criterion line."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= VALUE_PREVIEW_CHARS else text[: VALUE_PREVIEW_CHARS - 1] + "…"


def offered_targets(space, exclude=()):
    """The per-operation targets minus anything a corrective re-ask removed."""
    excluded = set(exclude)
    kept = {}
    for operation, candidates in space.targets.items():
        remaining = {target: action for target, action in candidates.items() if (operation, target) not in excluded}
        if remaining:
            kept[operation] = remaining
    return kept


def build_questions(space, goal, history=(), values=None, exclude=()):
    """Every question this step asks, in one request."""
    excluded = set(exclude)
    targets = offered_targets(space, excluded)
    operations = {operation: OPERATION_LABELS[operation] for operation in targets}
    operations.update({key: control["label"] for key, control in space.controls.items() if (key, None) not in excluded})
    operations.update({name: OPERATION_LABELS[name] for name in TERMINAL})
    questions = {"operation": choice(operations, instructions(goal, NEXT_ACTION))}
    for operation, candidates in targets.items():
        questions[question_name(operation)] = choice(
            {target: space.describe(target, action) for target, action in candidates.items()},
            instructions(goal, [NEXT_ACTION, TARGET], operation=operation),
        )
    if values and "TYPE_TEXT" in targets:
        criteria = {name: f"{name}: {preview(value)}" for name, value in values.items()}
        criteria[NONE_VALUE] = NONE_VALUE_LABEL
        # The field is chosen by a parallel question, so name the candidates here or there is nothing to match.
        fields = [space.describe(target, action) for target, action in targets["TYPE_TEXT"].items()]
        questions["value_for_field"] = choice(criteria, instructions(goal, VALUE_FOR_FIELD, fields=fields))
    if history:
        questions["prev_ok"] = noul(PREV_OK_CRITERIA, instructions(goal, PREV_OK))
    questions["goal_achieved"] = noul(GOAL_ACHIEVED_CRITERIA, instructions(goal, GOAL_ACHIEVED))
    return questions


def build_state(page, space, goal, history=(), values=None):
    """The state sent alongside the questions: meaning, never markup."""
    return {
        "goal": goal,
        "page": {
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "text": page.get("text", "")[:PAGE_TEXT_CHARS],
        },
        "elements": [element_view(element) for element in space.elements],
        "recent_actions": [
            {key: step.get(key) for key in ("action", "kind", "text", "page_changed")}
            for step in list(history)[-RECENT_ACTIONS:]
        ],
        "values_available": sorted(values) if values else [],
    }


def rank_candidates(space, answers, questions):
    """The operation/target pairs by joint probability, best first."""
    operation_probabilities = answers["operation"]["probabilities"]
    ranked = []
    for operation, probability in operation_probabilities.items():
        name = question_name(operation)
        if operation in space.targets and name in answers:
            for target, share in answers[name]["probabilities"].items():
                action = space.targets[operation].get(target)
                if action is None:
                    continue
                ranked.append(
                    {
                        "operation": operation,
                        "target": target,
                        "label": space.describe(target, action),
                        "probability": round(probability * share, 6),
                    }
                )
        else:
            label = questions["operation"]["criteria"].get(operation, operation)
            ranked.append(
                {"operation": operation, "target": None, "label": label, "probability": round(probability, 6)}
            )
    ranked.sort(key=lambda item: float(item.get("probability") or 0.0), reverse=True)
    return ranked[:CANDIDATES]


def read_answers(space, questions, reply):
    """Turn one validated answer set into an executable decision."""
    answers = reply.answers
    operation_answer = answers["operation"]
    operation = operation_answer["choice"]
    probability = operation_answer["probabilities"][operation]
    target, action = None, None
    if operation in space.targets:
        name = question_name(operation)
        if name not in answers:
            raise InvalidDecision(operation, None, "no target question was asked for this operation")
        target = answers[name]["choice"]
        action = offered_targets(space).get(operation, {}).get(target)
        if action is None:
            raise InvalidDecision(operation, target, "target is not in the observed action space")
        probability *= answers[name]["probabilities"][target]
    elif operation in space.controls:
        action = space.controls[operation]
    elif operation not in TERMINAL:
        raise InvalidDecision(operation, None, "operation is not offered on this page")
    value_answer = answers.get("value_for_field")
    value_name = value_answer["choice"] if value_answer else None
    return Decision(
        operation=operation,
        target=target,
        action=action,
        probability=round(probability, 6),
        confidence=operation_answer["confidence"],
        value_name=None if value_name == NONE_VALUE else value_name,
        prev_ok=answers["prev_ok"]["noul"] if "prev_ok" in answers else None,
        goal_achieved=answers["goal_achieved"]["noul"] if "goal_achieved" in answers else None,
        latency_ms=reply.latency_ms,
        cost=reply.cost,
        candidates=rank_candidates(space, answers, questions),
    )
