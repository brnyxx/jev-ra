"""The transport boundary: a daemon that stops answering is a jev-ra error, not a stray one."""

import pytest

from jev_ra import config
from jev_ra.browser import session as session_module
from jev_ra.errors import ChromeError, JevRaError, StalePage


class Bare(session_module.Session):
    def __init__(self):
        self.session_id = "s1"
        self.cache = {}
        self.after_input = None


@pytest.fixture
def bare():
    return Bare()


def test_a_daemon_that_stops_answering_reads_as_a_chrome_error(bare, monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError("Runtime.evaluate timed out after 5s waiting for the daemon")

    monkeypatch.setattr(session_module, "cdp", timeout)
    with pytest.raises(ChromeError) as caught:
        bare.call("Runtime.evaluate", expression="1")
    assert "Runtime.evaluate" in caught.value.render()
    assert "BU_CDP_URL" in caught.value.render()


def test_a_closed_socket_reads_as_a_chrome_error_too(bare, monkeypatch):
    def refused(*_args, **_kwargs):
        raise ConnectionRefusedError(61, "Connection refused")

    monkeypatch.setattr(session_module, "cdp", refused)
    with pytest.raises(ChromeError):
        bare.call("Page.navigate", url="https://example.com")


def test_every_transport_failure_is_one_the_callers_already_handle(bare, monkeypatch):
    monkeypatch.setattr(session_module, "cdp", lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("x")))
    with pytest.raises(JevRaError):
        bare.call("DOM.getDocument")


def test_a_slow_page_gets_a_longer_budget_than_a_plain_call(bare, monkeypatch):
    seen = []

    def record(method, session_id=None, _response_timeout=None, **params):
        seen.append((method, _response_timeout))
        return {"result": {"value": "complete"}}

    monkeypatch.setattr(session_module, "cdp", record)
    bare.call("Page.bringToFront")
    bare.evaluate("document.readyState")
    plain = dict((method, budget) for method, budget in seen)
    assert plain["Page.bringToFront"] == session_module.CALL_TIMEOUT_S
    assert plain["Runtime.evaluate"] == session_module.EVALUATE_TIMEOUT_S
    assert session_module.EVALUATE_TIMEOUT_S > session_module.CALL_TIMEOUT_S


def test_the_corpus_turns_a_dead_browser_into_a_row_not_a_crash(monkeypatch):
    from jev_ra import corpus

    class Dead:
        def __init__(self, _config=None):
            pass

        def close(self):
            pass

    class Agent:
        def __init__(self, **_kwargs):
            pass

        def run(self, *_args, **_kwargs):
            raise ChromeError("Chrome stopped answering during Runtime.evaluate.")

    monkeypatch.setattr(corpus, "Session", Dead)
    monkeypatch.setattr(corpus, "Agent", Agent)
    task = corpus.Task(name="t", family="f", url="https://example.com", goal="do it.")
    row = corpus.run_task(task, config=None, decide=lambda *_: {})
    assert row["status"] == "error" and row["reason"] == "ChromeError"


def test_a_document_that_moved_reads_as_stale_not_as_a_dead_browser(bare, monkeypatch):
    def moved(*_args, **_kwargs):
        raise RuntimeError({"code": -32000, "message": "Inspected target navigated or closed"})

    monkeypatch.setattr(session_module, "cdp", moved)
    with pytest.raises(StalePage):
        bare.call("Runtime.evaluate", expression="1")


def test_any_other_refusal_is_still_a_chrome_error(bare, monkeypatch):
    def refused(*_args, **_kwargs):
        raise RuntimeError({"code": -32601, "message": "'Fake.method' wasn't found"})

    monkeypatch.setattr(session_module, "cdp", refused)
    with pytest.raises(ChromeError):
        bare.call("Fake.method")


def test_one_slow_answer_is_waited_out_rather_than_ending_the_run(bare, monkeypatch):
    calls = []

    def slow_once(method, session_id=None, _response_timeout=None, **params):
        calls.append(method)
        if len(calls) == 1:
            raise TimeoutError(f"{method} timed out after 5s waiting for the daemon")
        return {"result": {"value": "ok"}}

    monkeypatch.setattr(session_module, "cdp", slow_once)
    assert bare.call("Emulation.setDeviceMetricsOverride", width=1280) == {"result": {"value": "ok"}}
    assert calls == ["Emulation.setDeviceMetricsOverride"] * 2


def test_a_daemon_that_keeps_timing_out_still_gives_up(bare, monkeypatch):
    calls = []

    def always(method, **_kwargs):
        calls.append(method)
        raise TimeoutError("timed out after 5s waiting for the daemon")

    monkeypatch.setattr(session_module, "cdp", always)
    with pytest.raises(ChromeError):
        bare.call("Page.navigate", url="https://example.com")
    assert len(calls) == 2


def counting_timeout(fail_times):
    calls = []

    def cdp(method, session_id=None, _response_timeout=None, **params):
        calls.append(method)
        if len(calls) <= fail_times:
            raise TimeoutError(f"{method} timed out after 5s waiting for the daemon")
        return {"ok": True}

    cdp.calls = calls
    return cdp


def test_a_read_only_call_is_asked_once_more_when_chrome_answers_late(bare, monkeypatch):
    cdp = counting_timeout(1)
    monkeypatch.setattr(session_module, "cdp", cdp)
    assert bare.call("Runtime.evaluate", expression="1") == {"ok": True}
    assert cdp.calls == ["Runtime.evaluate", "Runtime.evaluate"]


def test_input_is_never_dispatched_twice_because_the_answer_was_slow(bare, monkeypatch):
    cdp = counting_timeout(1)
    monkeypatch.setattr(session_module, "cdp", cdp)
    with pytest.raises(ChromeError):
        bare.call("Input.dispatchMouseEvent", type="mousePressed", x=1, y=1)
    assert cdp.calls == ["Input.dispatchMouseEvent"]


def test_typed_text_is_never_inserted_twice_either(bare, monkeypatch):
    cdp = counting_timeout(1)
    monkeypatch.setattr(session_module, "cdp", cdp)
    with pytest.raises(ChromeError):
        bare.call("Input.insertText", text="hoodie")
    assert cdp.calls == ["Input.insertText"]


@pytest.mark.parametrize("method", ["focused", "focus"])
def test_a_node_that_is_not_an_observed_id_never_reaches_the_page(bare, method, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the page was evaluated with an unchecked node")

    monkeypatch.setattr(session_module, "cdp", refuse)
    for smuggled in ("1); alert(1)//", 1.0, None, True, "12"):
        with pytest.raises(ValueError):
            getattr(bare, method)(smuggled)


def recording_cdp(fails_on):
    """A cdp that answers the setup calls and refuses the named one."""
    calls = []

    def cdp(method, session_id=None, _response_timeout=None, **params):
        calls.append((method, params))
        if method == fails_on:
            raise RuntimeError({"code": -32000, "message": "Session with given id not found."})
        if method == "Target.createTarget":
            return {"targetId": "t1"}
        if method == "Target.attachToTarget":
            return {"sessionId": "s1"}
        return {}

    cdp.calls = calls
    return cdp


@pytest.fixture
def no_chrome_needed(monkeypatch):
    monkeypatch.setattr(session_module, "ensure_chrome", lambda **_k: ("http://127.0.0.1:9222", "BU_CDP_URL"))
    monkeypatch.setattr(session_module, "ensure_daemon", lambda *_a, **_k: None)
    monkeypatch.setattr(session_module, "verify_attached", lambda *_a, **_k: None)


def test_a_target_whose_setup_fails_is_closed_again(monkeypatch, no_chrome_needed):
    cdp = recording_cdp("Emulation.setDeviceMetricsOverride")
    monkeypatch.setattr(session_module, "cdp", cdp)
    with pytest.raises(ChromeError):
        session_module.Session(config=config.load({}))
    assert ("Target.closeTarget", {"targetId": "t1"}) in cdp.calls


def test_a_target_we_only_attached_to_is_left_alone(monkeypatch, no_chrome_needed):
    cdp = recording_cdp("Emulation.setDeviceMetricsOverride")
    monkeypatch.setattr(session_module, "cdp", cdp)
    with pytest.raises(ChromeError):
        session_module.Session(config=config.load({}), target_id="theirs")
    assert not [method for method, _params in cdp.calls if method == "Target.closeTarget"]
