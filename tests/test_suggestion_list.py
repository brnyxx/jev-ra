"""A field whose suggestions are open: the options lead, and the field is not offered again."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser

FIXTURE = "/sites/suggestion-list.html"
GOAL = "Set the origin to Zurich Airport."


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def target_for(criteria, label):
    matches = [key for key, text in criteria.items() if label in text]
    if not matches:
        raise AssertionError(f"{label!r} is not offered; criteria were {criteria}")
    return matches[0]


def typist(after_typing):
    """Type the origin, then answer each later step with `after_typing(questions)`."""
    steps = []

    def decide(state, questions):
        steps.append((state, questions))
        if len(steps) == 1:
            answers = {
                "operation": certain("TYPE_TEXT", questions["operation"]["criteria"]),
                "type_text_target": certain(
                    target_for(questions["type_text_target"]["criteria"], "Origin"),
                    questions["type_text_target"]["criteria"],
                ),
                "value_for_field": certain("origin", questions["value_for_field"]["criteria"]),
                "goal_achieved": {"noul": 0.05},
            }
        else:
            answers = after_typing(questions)
        if "prev_ok" in questions:
            answers.setdefault("prev_ok", {"noul": 0.9})
        answers.setdefault("goal_achieved", {"noul": 0.05})
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.steps = steps
    return decide


def done(_questions):
    return {"operation": {"choice": "DONE", "confidence": 0.95, "probabilities": {"DONE": 1.0}}}


def first_click(questions):
    """What a run does when it takes the most obvious control it is offered."""
    if "click_target" not in questions:
        return done(questions)
    criteria = questions["click_target"]["criteria"]
    first = next(iter(criteria))
    return {
        "operation": certain("CLICK", questions["operation"]["criteria"]),
        "click_target": certain(first, criteria),
    }


def run_against(session, fixture_server, decide, max_steps=8):
    agent = Agent(session=session, config=config.load({}), decide=decide)
    return agent.run(GOAL, values={"origin": "Zurich"}, max_steps=max_steps, url=f"{fixture_server}{FIXTURE}")


def clicks_offered(questions):
    return list(questions.get("click_target", {}).get("criteria", {}).values())


def test_the_field_is_offered_for_clicking_before_anything_is_typed(session, fixture_server):
    decide = typist(done)
    run_against(session, fixture_server, decide)
    assert any("Open Origin" in text for text in clicks_offered(decide.steps[0][1]))


def test_the_field_is_not_offered_again_while_its_suggestions_are_up(session, fixture_server):
    decide = typist(done)
    run_against(session, fixture_server, decide)
    offered = clicks_offered(decide.steps[1][1])
    assert any("Zurich Airport (ZRH)" in text for text in offered)
    assert not any("Open Origin" in text for text in offered)


def test_the_suggestions_lead_the_element_table(session, fixture_server):
    decide = typist(done)
    run_against(session, fixture_server, decide)
    labels = [element["label"] for element in decide.steps[1][0]["elements"]]
    assert labels[:3] == ["Zurich Airport (ZRH)", "Zurich HB", "Zurich, Switzerland"]


def test_the_field_says_it_is_expanded_while_the_list_is_open(session, fixture_server):
    decide = typist(done)
    run_against(session, fixture_server, decide)
    field = next(element for element in decide.steps[1][0]["elements"] if element["label"] == "Origin")
    assert field["expanded"] == "true"


def test_a_run_that_takes_the_first_control_offered_reaches_a_suggestion(session, fixture_server):
    decide = typist(first_click)
    result = run_against(session, fixture_server, decide, max_steps=2)
    assert [step["target_label"] for step in result.steps] == ["Origin", "Zurich Airport (ZRH)"]


def test_choosing_a_suggestion_puts_the_field_back_on_offer(session, fixture_server):
    decide = typist(first_click)
    run_against(session, fixture_server, decide, max_steps=3)
    offered = clicks_offered(decide.steps[2][1])
    assert any("Open Origin" in text for text in offered)
    assert not any("] option " in text for text in offered)
