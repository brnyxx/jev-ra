"""A decider that follows a fixed plan. It answers the questions asked without any network call."""

from ..decide.client import Reply


def certain(choice, criteria):
    """A choice answer that puts all of its probability on one option."""
    return {
        "choice": choice,
        "confidence": 0.95,
        "probabilities": {key: (1.0 if key == choice else 0.0) for key in criteria},
    }


def target_for(criteria, label):
    """The offered target whose rendered criterion contains this label."""
    for key, text in criteria.items():
        if label in text:
            return key
    raise LookupError(f"{label!r} is not offered; criteria were {sorted(criteria)}")


class scripted:
    """A decider that walks a plan of (operation, label, value_name) and then answers DONE."""

    def __init__(self, plan):
        self.plan = list(plan)
        self.taken = []

    def __call__(self, _state, questions):
        """Answer the questions this step asks, following the plan."""
        step = self.plan[len(self.taken)] if len(self.taken) < len(self.plan) else None
        self.taken.append(step)
        if step is None:
            answers = {"operation": certain("DONE", questions["operation"]["criteria"])}
        else:
            operation, label, value_name = step
            answers = {"operation": certain(operation, questions["operation"]["criteria"])}
            if operation in {"CLICK", "TYPE_TEXT", "SELECT"}:
                name = operation.lower() + "_target"
                criteria = questions[name]["criteria"]
                answers[name] = certain(target_for(criteria, label), criteria)
            if "value_for_field" in questions:
                criteria = questions["value_for_field"]["criteria"]
                answers["value_for_field"] = certain(value_name or "none", criteria)
        answers["goal_achieved"] = {"noul": 0.95 if step is None else 0.05}
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.9}
        return Reply(answers=answers, model="scripted", latency_ms=0, usage={})
