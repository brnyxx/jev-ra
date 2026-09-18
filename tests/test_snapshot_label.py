"""A control with no pixels of its own is reachable through the label that has them."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/label-toggle.html"


def labels(page):
    return [element["label"] for element in page["elements"]]


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def test_a_label_standing_in_for_an_invisible_control_is_offered(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "153 languages" in labels(page)
    offered = next(e for e in page["elements"] if e["label"] == "153 languages")
    assert offered["role"] == "checkbox"
    assert offered["checked"] == "false"


def test_clicking_it_opens_what_it_controls(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "153 languages", "click"), page)
    page = session.observe()
    assert "한국어" in labels(page)
    assert next(e for e in page["elements"] if e["label"] == "153 languages")["checked"] == "true"


def test_an_ordinary_form_label_is_not_offered_twice(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert labels(page).count("Full name") == 1
    assert next(e for e in page["elements"] if e["label"] == "Full name")["role"] == "textbox"


def test_a_transparent_control_that_still_catches_the_pointer_is_offered(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    offered = [e for e in page["elements"] if e["label"] == "Tools"]
    assert len(offered) == 1
    assert offered[0]["role"] == "checkbox"
    session.act(action_for(page, "Tools", "click"), page)
    assert session.evaluate("document.getElementById('tools-btn').checked") is True


def test_something_hidden_with_opacity_and_nothing_else_stays_hidden(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert not [e for e in page["elements"] if e["label"] == "Page information"]
