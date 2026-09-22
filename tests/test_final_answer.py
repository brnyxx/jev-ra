"""A question-shaped goal ends with one sentence that answers it, or with why it does not."""

import json

import httpx
import pytest

from jev_ra import agent as agent_module
from jev_ra import config
from jev_ra.agent import question_shaped
from jev_ra.text import ValueBinder
from tests.test_agent import DONE, FakeSession, agent_with, decider, page

HELPER_ENV = {"JEV_RA_TEXT_MODEL": "writer-mini", "JEV_RA_TEXT_BASE_URL": "https://writer.test/v1"}
QUESTION = "What is the cheapest fare on this route?"
LISTING = "Booking form. The cheapest fare is 128 USD."


def helper(content, status=200, calls=None, raises=False):
    def handler(request):
        if raises:
            raise httpx.ConnectError("refused", request=request)
        if calls is not None:
            calls.append(json.loads(request.read()))
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}], "usage": {"total": 9}})

    return httpx.MockTransport(handler)


def run_with(monkeypatch, goal, transport=None, env=HELPER_ENV, text=LISTING):
    binders = []

    def build(values, resolved):
        bound = ValueBinder(values, resolved, transport=transport)
        binders.append(bound)
        return bound

    monkeypatch.setattr(agent_module, "ValueBinder", build)
    session = FakeSession(pages=[page(0, text=text)])
    return agent_with(decider([DONE]), session=session, env=env).run(goal)


@pytest.mark.parametrize(
    "goal",
    [
        "What is the cheapest fare on this route?",
        "Show me the cheapest fare?",
        "what is the cheapest fare",
        "Which airline flies this route",
        "How many stops does it make",
        "When does the next train leave",
        "Who wrote this paper",
        "Find the cheapest fare on this route",
    ],
)
def test_a_goal_that_reads_as_a_question_is_one(goal):
    assert question_shaped(goal) is True


@pytest.mark.parametrize(
    "goal",
    [
        "Book the cheapest fare on this route",
        "Add a keyboard to the cart",
        "Whatever the page says, click Apply",
        "Whose turn it is is not the question",
        "",
        "   ",
    ],
)
def test_an_instruction_is_not_a_question(goal):
    assert question_shaped(goal) is False


def test_a_question_gets_one_sentence_from_the_page_it_finished_on(monkeypatch):
    calls = []
    transport = helper('{"answer": "The cheapest fare is 128 USD."}', calls=calls)
    result = run_with(monkeypatch, QUESTION, transport)
    assert result.final_answer == "The cheapest fare is 128 USD."
    assert len(calls) == 1
    asked = json.loads(calls[0]["messages"][1]["content"])
    assert asked["goal"] == QUESTION
    assert asked["page"]["text"] == LISTING
    assert result.text_calls[0]["model"] == "writer-mini"


def test_the_helper_is_never_asked_about_an_instruction(monkeypatch):
    calls = []
    transport = helper('{"answer": "no"}', calls=calls)
    result = run_with(monkeypatch, "Book the cheapest fare on this route", transport)
    assert result.final_answer is None
    assert calls == []
    assert "final_answer" not in result.detail


def test_a_question_asked_of_a_run_with_no_helper_says_why_there_is_no_answer(monkeypatch):
    result = run_with(monkeypatch, QUESTION, helper('{"answer": "no"}'), env={})
    assert result.final_answer is None
    assert result.detail["final_answer"] == "no text helper is configured"


def test_a_helper_that_finds_nothing_on_the_page_says_so(monkeypatch):
    result = run_with(monkeypatch, QUESTION, helper('{"answer": null}'))
    assert result.final_answer is None
    assert result.detail["final_answer"] == "the text helper found no answer on the page"


def test_a_helper_that_cannot_be_reached_does_not_end_the_run(monkeypatch):
    result = run_with(monkeypatch, QUESTION, helper("", raises=True))
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert result.final_answer is None
    assert "unreachable" in result.detail["final_answer"]


def test_a_helper_that_refuses_is_reported_not_raised(monkeypatch):
    result = run_with(monkeypatch, QUESTION, helper('{"answer": "x"}', status=500))
    assert result.final_answer is None
    assert "HTTP 500" in result.detail["final_answer"]


def test_a_question_that_ended_blocked_still_gets_the_answer_on_screen(monkeypatch):
    transport = helper('{"answer": "The cheapest fare is 128 USD."}')
    binders = []

    def build(values, resolved):
        bound = ValueBinder(values, resolved, transport=transport)
        binders.append(bound)
        return bound

    monkeypatch.setattr(agent_module, "ValueBinder", build)
    blocked = {"operation": {"choice": "BLOCKED", "confidence": 0.9, "probabilities": {"BLOCKED": 1.0}}}
    session = FakeSession(pages=[page(0, text=LISTING)])
    result = agent_with(decider([blocked]), session=session, env=HELPER_ENV).run(QUESTION)
    assert result.status == "blocked"
    assert result.final_answer == "The cheapest fare is 128 USD."


def test_an_answer_longer_than_a_sentence_is_cut_to_one_line(monkeypatch):
    content = json.dumps({"answer": "a" * 500 + "\n\nand more"})
    result = run_with(monkeypatch, QUESTION, helper(content))
    assert result.final_answer == "a" * 400
    assert "\n" not in result.final_answer


def test_the_binder_answers_nothing_without_a_helper():
    bound = ValueBinder({}, config.load({}))
    assert bound.answer(QUESTION, {"text": LISTING}) == (None, "no text helper is configured")
