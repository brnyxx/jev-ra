"""A click that opens a panel: the panel is shown first, and the control says it is open."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser

FIXTURE = "/sites/reveal-panel.html"


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def target_for(criteria, label):
    matches = [key for key, text in criteria.items() if label in text]
    if not matches:
        raise AssertionError(f"{label!r} is not offered; criteria were {criteria}")
    return matches[0]


def click_then_done(label):
    """Click the named control once, then report done. Every state seen is kept."""
    states = []

    def decide(state, questions):
        states.append(state)
        if len(states) == 1:
            answers = {
                "operation": certain("CLICK", questions["operation"]["criteria"]),
                "click_target": certain(
                    target_for(questions["click_target"]["criteria"], label), questions["click_target"]["criteria"]
                ),
                "goal_achieved": {"noul": 0.05},
            }
        else:
            answers = {
                "operation": certain("DONE", questions["operation"]["criteria"]),
                "goal_achieved": {"noul": 0.95},
            }
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.9}
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.states = states
    return decide


def run_against(session, fixture_server, decide):
    agent = Agent(session=session, config=config.load({}), decide=decide)
    return agent.run("Add two adult passengers to the booking.", url=f"{fixture_server}{FIXTURE}")


def labels_of(state):
    return [element["label"] for element in state["elements"]]


def test_the_panel_the_click_opened_is_listed_before_the_button(session, fixture_server):
    decide = click_then_done("Add passengers")
    run_against(session, fixture_server, decide)
    labels = labels_of(decide.states[1])
    assert "Add passengers" in labels
    assert {"Adults", "Children", "Confirm passengers"} <= set(labels)
    assert labels.index("Confirm passengers") < labels.index("Add passengers")
    assert labels.index("Adults") < labels.index("Add passengers")


def test_the_control_that_opened_the_panel_is_marked_expanded(session, fixture_server):
    decide = click_then_done("Add passengers")
    run_against(session, fixture_server, decide)
    opener = next(element for element in decide.states[1]["elements"] if element["label"] == "Add passengers")
    assert opener["expanded"] == "true"


def test_before_the_click_nothing_claims_to_be_expanded(session, fixture_server):
    decide = click_then_done("Add passengers")
    run_against(session, fixture_server, decide)
    assert all("expanded" not in element for element in decide.states[0]["elements"])
