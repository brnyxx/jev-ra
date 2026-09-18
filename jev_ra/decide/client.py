"""One HTTP round trip per step, with every answer validated before it can move a browser."""

import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field

import httpx

from ..config import is_openrouter

logger = logging.getLogger(__name__)

TIMEOUT_S = 25.0
RETRY_STATUS = {429, 500, 502, 503, 529}
PROBABILITY_TOLERANCE = 0.02


class JevError(Exception):
    """A decision could not be obtained. No action has been executed."""


class JevAuthError(JevError):
    """No usable key, or the provider rejected it."""


class JevUnavailable(JevError):
    """The provider could not be reached or kept failing."""


class JevInvalidResponse(JevError):
    """The provider answered, but the answers cannot be trusted."""


@dataclass(frozen=True)
class Reply:
    answers: dict
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0

    @property
    def cost(self):
        value = self.usage.get("cost")
        return float(value) if isinstance(value, (int, float)) else 0.0


def as_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def as_text_questions(questions):
    return {
        name: dict(
            question,
            instructions=as_text(question["instructions"]),
            criteria={key: as_text(value) for key, value in question["criteria"].items()},
        )
        for name, question in questions.items()
    }


def finite_unit(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def read_choice(answer, criteria, name):
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(criteria):
        raise JevInvalidResponse(f"{name}: probabilities do not cover the offered options")
    if not all(finite_unit(value) for value in probabilities.values()):
        raise JevInvalidResponse(f"{name}: probabilities are not numbers in [0, 1]")
    if abs(sum(probabilities.values()) - 1) > PROBABILITY_TOLERANCE:
        raise JevInvalidResponse(f"{name}: probabilities do not sum to 1")
    if not finite_unit(answer.get("confidence")):
        raise JevInvalidResponse(f"{name}: confidence is not a number in [0, 1]")
    choice = answer.get("choice")
    if choice not in criteria:
        raise JevInvalidResponse(f"{name}: choice {choice!r} was not offered")
    if probabilities[choice] < max(probabilities.values()) - 1e-6:
        raise JevInvalidResponse(f"{name}: choice is not the most probable option")
    return answer


def read_noul(answer, name):
    if not finite_unit(answer.get("noul")):
        raise JevInvalidResponse(f"{name}: noul is not a number in [0, 1]")
    return answer


def read_answers(payload, questions):
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevInvalidResponse("Response carries no answers")
    validated = {}
    for name, question in questions.items():
        answer = answers.get(name)
        if not isinstance(answer, dict):
            raise JevInvalidResponse(f"{name}: no answer")
        kind = question.get("type")
        if kind == "choice":
            validated[name] = read_choice(answer, question["criteria"], name)
        elif kind == "noul":
            validated[name] = read_noul(answer, name)
        else:
            raise JevInvalidResponse(f"{name}: unsupported question type {kind!r}")
    return validated


class DecisionClient:
    def __init__(self, config, transport=None, retry_delay_s=0.5):
        self.config = config
        self.retry_delay_s = retry_delay_s
        # OpenRouter accepts a session id to group a run's decisions; harmless elsewhere.
        self.session_id = uuid.uuid4().hex
        self._client = httpx.Client(http2=True, timeout=TIMEOUT_S, transport=transport)

    def build(self, state, questions):
        body = {"model": self.config.model, "state": state, "questions": questions}
        if is_openrouter(self.config.endpoint):
            body["questions"] = as_text_questions(questions)
            body["session_id"] = self.session_id
        return body

    def decide(self, state, questions):
        if not self.config.api_key:
            raise JevAuthError("No Jev API key. Set JEV_RA_API_KEY, TYPESAFE_API_KEY or OPENROUTER_API_KEY.")
        started = time.perf_counter()
        payload = self.post(self.build(state, questions))
        if not isinstance(payload, dict):
            raise JevInvalidResponse("Response is not a JSON object")
        return Reply(
            answers=read_answers(payload, questions),
            model=payload.get("model") or self.config.model,
            usage=payload.get("usage") or {},
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    def post(self, body):
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        for attempt in range(2):
            try:
                response = self._client.post(self.config.endpoint, json=body, headers=headers)
            except httpx.HTTPError as error:
                raise JevUnavailable(f"Could not reach {self.config.endpoint}: {error}") from None
            if response.status_code in {401, 403}:
                raise JevAuthError(
                    f"Provider rejected the key from {self.config.key_variable}: HTTP {response.status_code}"
                )
            if response.status_code in RETRY_STATUS:
                if attempt == 0:
                    logger.warning("Jev returned HTTP %s; retrying once", response.status_code)
                    time.sleep(self.retry_delay_s)
                    continue
                raise JevUnavailable(f"Jev kept returning HTTP {response.status_code}")
            if response.is_error:
                raise JevError(f"Jev returned HTTP {response.status_code}")
            try:
                return response.json()
            except ValueError:
                raise JevInvalidResponse("Response body is not JSON") from None
        raise JevUnavailable("Jev is unavailable")

    def close(self):
        self._client.close()
