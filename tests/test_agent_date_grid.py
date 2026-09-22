"""A date-picker grid should be driven by its dates, not its field."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser

FIXTURE = "/sites/date-grid.html"
BUTTON_FIXTURE = "/sites/date-button-grid.html"
DATE = "September 20, 2026"


def certain(choice, criteria):
    return {
        "choice": choice,
        "confidence": 0.95,
        "probabilities": {key: float(key == choice) for key in criteria},
    }


@pytest.mark.parametrize("fixture", [FIXTURE, BUTTON_FIXTURE])
def test_the_open_departure_grid_is_named_and_the_date_field_is_not_offered(session, fixture_server, fixture):
    calls = []

    def decide(state, questions):
        calls.append((state, questions))
        if len(calls) == 1:
            operation = "CLICK"
            target = next(
                key for key, label in questions["click_target"]["criteria"].items() if "Open Departure" in label
            )
        elif len(calls) == 2:
            operation = "CLICK"
            target = next(key for key, label in questions["click_target"]["criteria"].items() if DATE in label)
        else:
            operation, target = "DONE", None

        answers = {
            "operation": certain(operation, questions["operation"]["criteria"]),
            "goal_achieved": {"noul": 0.95 if operation == "DONE" else 0.05},
        }
        if target is not None:
            name = operation.lower() + "_target"
            answers[name] = certain(target, questions[name]["criteria"])
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.95}
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    result = agent.run(
        "Set the Departure date to September 20, 2026.",
        values={"departure_date": DATE},
        url=fixture_server + fixture,
    )

    grid_state, grid_questions = calls[1]
    assert grid_state["last_step_effect"] == "the last step opened 4 dates under Departure, listed first below"
    assert [element["label"] for element in grid_state["elements"][:4]] == [
        "September 19, 2026",
        DATE,
        "September 21, 2026",
        "September 22, 2026",
    ]
    assert "type_text_target" not in grid_questions
    assert all("Open Departure" not in label for label in grid_questions["click_target"]["criteria"].values())
    assert "type_text_target" in calls[2][1]
    departure = next(element for element in result.final_page["elements"] if element["label"] == "Departure")
    assert (result.status, result.reason, departure["value"]) == ("done", "goal_achieved", DATE)
