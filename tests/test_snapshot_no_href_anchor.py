"""Anchors without destinations are controls only when the page makes them interactive."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/no-href-anchor.html"
INTERACTIVE = {"Role region", "Focusable region", "Handler region", "Pointer region"}


def test_only_interactive_anchors_without_href_are_offered(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    labels = {element["label"] for element in page["elements"]}
    assert labels >= INTERACTIVE
    assert "Plain text" not in labels


def test_an_anchor_handler_can_be_invoked_by_its_observed_ref(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    action = next(action for action in page["actions"] if action.get("label") == "Handler region")
    session.act(action, page)
    after = session.observe()
    assert "Handler region selected" in after["text"]
