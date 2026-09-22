"""The first run on a machine that has never run jev-ra: a Chrome of our own, cold."""

import pytest

from jev_ra import cli, config
from jev_ra.browser import chrome as chrome_module
from jev_ra.browser import session as session_module
from jev_ra.errors import ChromeError


class Bare(session_module.Session):
    """A Session without a browser behind it, for the calls this module is about."""

    def __init__(self):
        self.config = config.load({})
        self.session_id = "s1"
        self.cache = {}
        self.after_input = None
        self.before_input = None
        self.moved_from = None
        self.max_elements = 250


@pytest.fixture
def bare():
    return Bare()


def test_a_navigation_is_given_the_navigation_budget_not_the_call_budget(bare, monkeypatch):
    seen = {}

    def record(method, session_id=None, _response_timeout=None, **params):
        seen[method] = _response_timeout
        return {"result": {"value": "complete"}}

    monkeypatch.setattr(session_module, "cdp", record)
    monkeypatch.setattr(bare, "observe", lambda: {"elements": [{"ref": "e1"}], "actions": []})
    monkeypatch.setattr(bare, "evaluate", lambda *_a, **_k: True)
    bare.open("https://example.com")
    assert seen["Page.navigate"] == session_module.NAVIGATE_TIMEOUT_S
    assert session_module.NAVIGATE_TIMEOUT_S > session_module.CALL_TIMEOUT_S
    # A cold profile's first navigation blocks while Chrome brings up its network stack: measured
    # at 19.5 s on macOS with a profile made a second earlier, against 0.2 s once it is warm.
    assert session_module.NAVIGATE_TIMEOUT_S >= 30


def test_a_launched_chrome_is_ready_once_a_target_answers(monkeypatch):
    answers = iter([TimeoutError("not yet"), TimeoutError("still not"), {"result": {"value": 2}}])

    def flaky(method, **_kwargs):
        if method != "Runtime.evaluate":
            return {"targetId": "t1", "sessionId": "s1"}
        outcome = next(answers)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(chrome_module, "cdp", flaky, raising=False)
    monkeypatch.setattr(chrome_module.time, "sleep", lambda _seconds: None)
    assert chrome_module.ready(cdp=flaky) is True


def test_a_chrome_that_never_answers_is_reported_as_one(monkeypatch):
    def deaf(method, **_kwargs):
        if method != "Runtime.evaluate":
            return {"targetId": "t1", "sessionId": "s1"}
        raise TimeoutError("nothing")

    monkeypatch.setattr(chrome_module.time, "sleep", lambda _seconds: None)
    with pytest.raises(ChromeError, match="did not answer"):
        chrome_module.ready(cdp=deaf, timeout=0.3)


def test_doctor_says_jev_ra_will_launch_its_own_chrome_when_one_is_installed():
    hint = cli.chrome_hint(binary="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    assert "jev-ra will launch" in hint
    assert "--remote-debugging-port" not in hint
    assert "Google Chrome" in hint


def test_doctor_still_explains_the_manual_route_when_no_browser_is_installed():
    hint = cli.chrome_hint(binary=None)
    assert "--remote-debugging-port" in hint
    assert "BU_CDP_URL" in hint


def test_doctor_warns_about_a_home_too_long_for_a_unix_socket():
    hint = cli.chrome_hint(binary=None, home="/tmp/" + "x" * 120)
    assert "AF_UNIX" in hint or "too long" in hint
