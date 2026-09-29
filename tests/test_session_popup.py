"""A window a page opens is followed into, and left again when it closes itself."""

import time

import pytest

from jev_ra.browser import session as session_module

pytestmark = pytest.mark.browser

FIXTURE = "/sites/popup-signin.html"


def action_for(page, label):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == "click")


def signed_in(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Continue with Acme ID"), page)
    return session.observe()


def test_the_window_a_click_opens_is_where_the_next_observation_is(session, fixture_server):
    page = signed_in(session, fixture_server)
    assert page["url"].endswith("/sites/popup-consent.html")
    assert [e["label"] for e in page["elements"]] == ["Cancel", "Allow"]


def test_a_window_that_closes_itself_hands_the_run_back_to_its_opener(session, fixture_server):
    page = signed_in(session, fixture_server)
    started = time.monotonic()
    session.act(action_for(page, "Allow"), page)
    page = session.observe()
    assert time.monotonic() - started < session_module.CALL_TIMEOUT_S
    assert page["url"].endswith(FIXTURE)
    assert "Signed in as Ada Lovelace." in page["text"]


def test_a_window_the_run_leaves_open_is_closed_with_the_session(session, fixture_server):
    signed_in(session, fixture_server)
    window = session.target_id
    assert window != session.openers[0][0]
    session.close()
    targets = {info["targetId"] for info in session_module.cdp("Target.getTargets")["targetInfos"]}
    assert window not in targets
