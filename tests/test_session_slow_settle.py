"""A settle that takes longer than a plain call is a wait, not a browser that has gone away."""

import time

import pytest

from jev_ra.browser import session as session_module

FIXTURE = "/sites/slow-settle.html"


class Bare(session_module.Session):
    def __init__(self):
        self.session_id = "s1"
        self.cache = {}
        self.after_input = None
        self.before_input = None
        self.moved_from = None
        self.max_elements = session_module.MAX_ELEMENTS


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


@pytest.mark.browser
def test_a_settle_promise_that_resolves_after_six_seconds_does_not_raise(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    started = time.monotonic()
    session.act(action_for(page, "Search all fields", "fill"), page, text="graph neural network")
    session.observe()
    elapsed = time.monotonic() - started
    assert elapsed > session_module.CALL_TIMEOUT_S, f"the settle was cut short after {elapsed:.2f}s"
    assert session.evaluate("document.getElementById('q').value") == "graph neural network"


def test_the_settle_gets_the_same_budget_as_every_other_evaluate(monkeypatch):
    budgets = []

    def cdp(method, session_id=None, _response_timeout=None, **params):
        budgets.append(_response_timeout)
        return {"result": {"value": None}}

    monkeypatch.setattr(session_module, "cdp", cdp)
    bare = Bare()
    bare.after_input = {"id": "e1", "kind": "click", "role": "link", "node": 1}
    bare.settle()
    assert budgets[0] == session_module.EVALUATE_TIMEOUT_S


def test_a_settle_the_browser_never_answers_is_still_only_a_wait(monkeypatch):
    def cdp(method, session_id=None, _response_timeout=None, **params):
        if params.get("awaitPromise"):
            raise TimeoutError("Runtime.evaluate timed out")
        return {"result": {"value": None}}

    monkeypatch.setattr(session_module, "cdp", cdp)
    bare = Bare()
    bare.after_input = {"id": "e1", "kind": "click", "role": "link", "node": 1}
    bare.settle()
    assert bare.after_input is None
