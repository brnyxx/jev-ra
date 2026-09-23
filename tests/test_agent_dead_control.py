"""A choice that twice changed nothing sits out the next question; one retry stays on offer."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply
from tests.test_agent import FakeSession, answer, page

FIXTURE = "/sites/dead-control.html"


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def habitual(favourite, fallback, done_when):
    """A decider that presses its favourite control whenever it is offered, the way a model does
    when it is asked the same question about the same page, and the fallback otherwise."""
    calls = []

    def decide(state, questions):
        calls.append(questions)
        done = done_when in state["page"]["text"]
        answers = {"goal_achieved": {"noul": 0.95 if done else 0.05}}
        if "prev_ok" in questions:
            answers["prev_ok"] = {"noul": 0.1}
        if done:
            answers["operation"] = certain("DONE", questions["operation"]["criteria"])
            return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})
        criteria = questions["click_target"]["criteria"]
        chosen = next((key for key, text in criteria.items() if text.endswith(favourite)), None)
        chosen = chosen or next(key for key, text in criteria.items() if text.endswith(fallback))
        answers["operation"] = certain("CLICK", questions["operation"]["criteria"])
        answers["click_target"] = certain(chosen, criteria)
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.calls = calls
    return decide


def run(session, fixture_server, decide):
    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    return agent.run("Search the catalog for 3d printing.", url=fixture_server + FIXTURE)


@pytest.mark.browser
def test_a_control_that_twice_did_nothing_gives_way_to_the_one_beside_it(session, fixture_server):
    result = run(session, fixture_server, habitual("Open catalog", "Search", "Results for"))
    assert [(step["target_label"], step["page_changed"]) for step in result.steps] == [
        ("Open catalog", False),
        ("Open catalog", False),
        ("Search", True),
    ]
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert "Results for 3d printing" in result.final_page["text"]


@pytest.mark.browser
def test_the_control_sits_out_one_question_only(session, fixture_server):
    decide = habitual("Open catalog", "Search", "Results for")
    run(session, fixture_server, decide)
    offered = [
        any(text.endswith("Open catalog") for text in call["click_target"]["criteria"].values())
        for call in decide.calls
    ]
    assert offered == [True, True, False, True]


@pytest.mark.browser
def test_a_first_press_the_page_swallowed_is_pressed_again(session, fixture_server):
    result = run(session, fixture_server, habitual("Open palette", "Search", "Palette open"))
    assert [(step["target_label"], step["page_changed"]) for step in result.steps] == [
        ("Open palette", False),
        ("Open palette", True),
    ]
    assert (result.status, result.reason) == ("done", "goal_achieved")


def scripted(pick):
    decisions = []

    def decide(state, questions):
        decisions.append(questions)
        return Reply(
            answers={"operation": answer(pick(questions, decisions)), "goal_achieved": {"noul": 0.1}},
            model="scripted",
            latency_ms=1,
            usage={"cost": 0.0},
        )

    decide.decisions = decisions
    return decide


def test_a_scroll_that_twice_moved_nothing_is_not_offered_next():
    scroll_down = {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560}
    still = {**page("same"), "actions": [*page("same")["actions"], scroll_down]}
    decide = scripted(
        lambda questions, _: "SCROLL_DOWN" if "SCROLL_DOWN" in questions["operation"]["criteria"] else "BLOCKED"
    )
    agent = Agent(session=FakeSession(pages=[still] * 6), config=config.load({}), decide=decide, prefetch=False)
    result = agent.run("find the footer")
    assert [step["operation"] for step in result.steps] == ["SCROLL_DOWN", "SCROLL_DOWN"]
    assert (result.status, result.reason) == ("blocked", "blocked")
    assert "SCROLL_DOWN" not in decide.decisions[2]["operation"]["criteria"]


def test_waits_that_changed_nothing_are_still_offered():
    decide = scripted(lambda _questions, decisions: "WAIT" if len(decisions) <= 2 else "BLOCKED")
    agent = Agent(session=FakeSession(pages=[page("same")] * 6), config=config.load({}), decide=decide, prefetch=False)
    agent.run("wait for the results")
    assert "WAIT" in decide.decisions[2]["operation"]["criteria"]
