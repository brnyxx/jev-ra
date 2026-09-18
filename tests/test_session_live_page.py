"""A page that never stops changing must still be usable, as long as the target has not moved."""

import pytest

from jev_ra.errors import StalePage

pytestmark = pytest.mark.browser

FIXTURE = "/sites/live-ticker.html"


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def test_typing_survives_a_page_whose_text_changes_every_frame(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert session.evaluate("document.getElementById('tick').textContent") != ""
    session.act(action_for(page, "Where from", "fill"), page, text="Zurich")
    assert session.evaluate("document.getElementById('q').value") == "Zurich"


def test_clicking_survives_it_too(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Where from", "fill"), page, text="Zurich")
    page = session.observe()
    session.act(action_for(page, "Search", "click"), page)
    assert "searched: Zurich" in session.observe()["text"]


def test_scrolling_and_waiting_survive_it_too(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    scroll = next(action for action in page["actions"] if action["id"] == "scroll_down")
    session.act(scroll, page)
    assert session.observe()["scroll"]["y"] > 0
    page = session.observe()
    session.act(next(action for action in page["actions"] if action["id"] == "wait"), page)


def test_a_target_that_really_did_move_is_still_refused(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    action = action_for(page, "Where from", "fill")
    session.evaluate("document.getElementById('q').setAttribute('aria-label', 'Where to')")
    with pytest.raises(StalePage):
        session.act(action, page, text="Zurich")


def test_a_navigation_under_the_decision_is_still_refused(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    action = action_for(page, "Where from", "fill")
    session.open(fixture_server + "/form.html")
    with pytest.raises(StalePage):
        session.act(action, page, text="Zurich")
