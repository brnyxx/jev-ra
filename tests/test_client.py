import json

import httpx
import pytest

from jev_ra import config
from jev_ra.decide import DecisionClient, JevAuthError, JevBadResponse, JevError, JevUnavailable
from jev_ra.errors import ConfigError

QUESTIONS = {
    "operation": {
        "type": "choice",
        "criteria": {"CLICK": "Click an element.", "DONE": "Everything is satisfied."},
        "instructions": "pick one",
    },
    "goal_achieved": {"type": "noul", "criteria": {"true": "yes", "false": "no"}, "instructions": "judge"},
}

ANSWERS = {
    "operation": {"choice": "CLICK", "confidence": 0.8, "probabilities": {"CLICK": 0.9, "DONE": 0.1}},
    "goal_achieved": {"noul": 0.2},
}


def client_for(handler, env=None, retry_delay_s=0.0):
    resolved = config.load({"OPENROUTER_API_KEY": "sk-or-v1-test"} if env is None else env)
    return DecisionClient(resolved, transport=httpx.MockTransport(handler), retry_delay_s=retry_delay_s)


def choice_answer(choice, probabilities, confidence=0.5):
    return {"choice": choice, "confidence": confidence, "probabilities": probabilities}


def responder(payload, status=200, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        return httpx.Response(status, json=payload)

    return handler


def test_successful_decision_returns_validated_answers():
    calls = []
    payload = {"model": "typesafe/jev-1.13", "answers": ANSWERS, "usage": {"cost": 0.0004}}
    client = client_for(responder(payload, calls=calls))
    reply = client.decide({"goal": "x"}, QUESTIONS)
    assert reply.answers["operation"]["choice"] == "CLICK"
    assert reply.model == "typesafe/jev-1.13"
    assert reply.cost == pytest.approx(0.0004)
    assert reply.latency_ms >= 0
    assert str(calls[0].url) == config.OPENROUTER_ENDPOINT
    assert calls[0].headers["authorization"] == "Bearer sk-or-v1-test"


def test_missing_answer_is_rejected():
    client = client_for(responder({"answers": {"operation": ANSWERS["operation"]}}))
    with pytest.raises(JevBadResponse, match="goal_achieved: no answer"):
        client.decide({}, QUESTIONS)


def test_choice_that_is_not_the_argmax_is_rejected():
    answers = dict(ANSWERS, operation=choice_answer("DONE", {"CLICK": 0.9, "DONE": 0.1}))
    client = client_for(responder({"answers": answers}))
    with pytest.raises(JevBadResponse, match="most probable"):
        client.decide({}, QUESTIONS)


def test_choice_outside_the_offered_options_is_rejected():
    answers = dict(ANSWERS, operation=choice_answer("TYPE_TEXT", {"CLICK": 0.9, "DONE": 0.1}))
    client = client_for(responder({"answers": answers}))
    with pytest.raises(JevBadResponse, match="was not offered"):
        client.decide({}, QUESTIONS)


def test_probabilities_that_do_not_sum_to_one_are_rejected():
    answers = dict(ANSWERS, operation=choice_answer("CLICK", {"CLICK": 0.5, "DONE": 0.1}))
    client = client_for(responder({"answers": answers}))
    with pytest.raises(JevBadResponse, match="do not sum to 1"):
        client.decide({}, QUESTIONS)


def test_noul_outside_the_unit_interval_is_rejected():
    client = client_for(responder({"answers": dict(ANSWERS, goal_achieved={"noul": 4})}))
    with pytest.raises(JevBadResponse, match="goal_achieved: noul"):
        client.decide({}, QUESTIONS)


def test_429_is_retried_once_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json={"answers": ANSWERS})

    reply = client_for(handler).decide({}, QUESTIONS)
    assert len(calls) == 2
    assert reply.answers["operation"]["choice"] == "CLICK"


def test_repeated_429_gives_up_as_unavailable():
    calls = []
    client = client_for(responder({"error": "slow down"}, status=429, calls=calls))
    with pytest.raises(JevUnavailable, match="429"):
        client.decide({}, QUESTIONS)
    assert len(calls) == 2


def test_401_is_not_retried():
    calls = []
    client = client_for(responder({"error": "bad key"}, status=401, calls=calls))
    with pytest.raises(JevAuthError, match="OPENROUTER_API_KEY"):
        client.decide({}, QUESTIONS)
    assert len(calls) == 1


def test_other_client_errors_surface_as_jev_errors():
    client = client_for(responder({"error": "bad request"}, status=400))
    with pytest.raises(JevError, match="HTTP 400"):
        client.decide({}, QUESTIONS)


def test_timeout_becomes_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("too slow", request=request)

    with pytest.raises(JevUnavailable, match="Could not reach"):
        client_for(handler).decide({}, QUESTIONS)


def test_no_key_means_no_request_at_all():
    calls = []
    client = client_for(responder({"answers": ANSWERS}, calls=calls), env={})
    with pytest.raises(ConfigError, match="No Jev API key"):
        client.decide({}, QUESTIONS)
    assert calls == []


def recording_handler(bodies):
    def handler(request):
        bodies.append(json.loads(request.read()))
        return httpx.Response(200, json={"answers": ANSWERS})

    return handler


def test_openrouter_bodies_carry_a_session_id_and_string_criteria():
    bodies = []
    client = client_for(recording_handler(bodies))
    structured = {
        "type": "choice",
        "criteria": {"CLICK": {"element": "[1] Continue"}, "DONE": "Everything is satisfied."},
        "instructions": {"goal": "open the article"},
    }
    client.decide({}, dict(QUESTIONS, operation=structured))
    body = bodies[0]
    assert body["session_id"] == client.session_id
    assert body["model"] == config.OPENROUTER_MODEL
    assert isinstance(body["questions"]["operation"]["instructions"], str)
    assert all(isinstance(value, str) for value in body["questions"]["operation"]["criteria"].values())


def test_typesafe_route_sends_no_session_id():
    bodies = []
    client = client_for(recording_handler(bodies), env={"TYPESAFE_API_KEY": "ts-1"})
    client.decide({}, QUESTIONS)
    assert "session_id" not in bodies[0]
    assert bodies[0]["model"] == config.TYPESAFE_MODEL
