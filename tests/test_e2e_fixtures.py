"""One full agent run against real Chrome, with the decisions scripted instead of asked."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser

PLAN = [
    ("TYPE_TEXT", "Full name", "name"),
    ("TYPE_TEXT", "Email", "email"),
    ("SELECT", "Shipping → Express", None),
    ("CLICK", "Place order", None),
]


def certain(choice, criteria):
    spread = {key: (1.0 if key == choice else 0.0) for key in criteria}
    return {"choice": choice, "confidence": 0.95, "probabilities": spread}


def target_for(criteria, label):
    matches = [key for key, text in criteria.items() if label in text]
    if not matches:
        raise AssertionError(f"{label!r} is not offered; criteria were {criteria}")
    return matches[0]


def scripted(plan):
    """Answers the questions actually asked, picking targets by their rendered label."""
    calls = []

    def decide(state, questions):
        step = plan[len(calls)] if len(calls) < len(plan) else None
        calls.append(questions)
        if step is None:
            answers = {"operation": certain("DONE", questions["operation"]["criteria"])}
        else:
            operation, label, value_name = step
            name = operation.lower() + "_target"
            answers = {
                "operation": certain(operation, questions["operation"]["criteria"]),
                name: certain(target_for(questions[name]["criteria"], label), questions[name]["criteria"]),
            }
            if "value_for_field" in questions:
                criteria = questions["value_for_field"]["criteria"]
                answers["value_for_field"] = certain(value_name or "none", criteria)
        answers["goal_achieved"] = {"noul": 0.95 if step is None else 0.05}
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.9}
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.calls = calls
    return decide


def test_a_scripted_run_fills_selects_and_submits_a_real_form(session, fixture_server):
    decide = scripted(PLAN)
    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    result = agent.run(
        "Place an order for Ada Lovelace with express shipping.",
        values={"name": "Ada Lovelace", "email": "ada@example.com"},
        url=f"{fixture_server}/checkout.html",
    )
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert len(result.steps) == 4
    assert len(result.steps) <= 6
    assert [step["operation"] for step in result.steps] == ["TYPE_TEXT", "TYPE_TEXT", "SELECT", "CLICK"]
    assert [step["text"] for step in result.steps[:2]] == ["Ada Lovelace", "ada@example.com"]
    assert all(step["page_changed"] for step in result.steps)
    assert result.text_calls == []


def test_the_typed_values_are_on_the_confirmation_page(session, fixture_server):
    agent = Agent(session=session, config=config.load({}), decide=scripted(PLAN), prefetch=False)
    result = agent.run(
        "Place an order for Ada Lovelace with express shipping.",
        values={"name": "Ada Lovelace", "email": "ada@example.com"},
        url=f"{fixture_server}/checkout.html",
    )
    text = result.final_page["text"]
    assert "Order confirmed" in text
    assert "Ada Lovelace" in text
    assert "ada@example.com" in text
    assert "Express" in text
    assert session.evaluate("document.getElementById('order').hidden") is True


def test_every_executed_target_came_from_an_observed_node(session, fixture_server):
    decide = scripted(PLAN)
    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    agent.run(
        "Place an order for Ada Lovelace with express shipping.",
        values={"name": "Ada Lovelace", "email": "ada@example.com"},
        url=f"{fixture_server}/checkout.html",
    )
    for questions in decide.calls:
        for name, question in questions.items():
            if not name.endswith("_target"):
                continue
            assert all(key.startswith("e") for key in question["criteria"])
            assert all(isinstance(text, str) for text in question["criteria"].values())
