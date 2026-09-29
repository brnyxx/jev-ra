"""The keys a person presses where there is no button: Enter in the field they typed into, Escape out of a dialog."""

import pytest

pytestmark = pytest.mark.browser


def field(page, label):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == "fill")


def key(page, name):
    return next((a for a in page["actions"] if a["kind"] == "press" and a["key"] == name), None)


def test_a_search_box_inside_a_web_component_is_submitted_with_enter(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/shadow-search.html")
    box = field(page, "Search Communities")
    session.act(box, page, text="mechanical keyboards")
    page = session.observe()
    enter = key(page, "Enter")
    assert (enter["node"], enter["label"]) == (box["node"], "Press Enter to submit Search Communities")
    session.act(enter, page)
    session.observe()
    assert session.evaluate("document.getElementById('heading').textContent") == (
        'Search results for "mechanical keyboards"'
    )


def test_a_composer_with_no_send_button_sends_its_message_with_enter(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/chat-composer.html")
    composer = field(page, "Message #deploys")
    session.act(composer, page, text="Deploy 1841 is live.")
    page = session.observe()
    enter = key(page, "Enter")
    assert enter["node"] == composer["node"]
    session.act(enter, page)
    session.observe()
    assert session.evaluate("document.querySelector('#log .message:last-child').textContent") == (
        "you Deploy 1841 is live."
    )


def test_an_empty_composer_offers_nothing_to_send(session, fixture_server):
    session.open(f"{fixture_server}/sites/chat-composer.html")
    session.evaluate("document.querySelector('[role=textbox]').focus()")
    assert key(session.observe(), "Enter") is None


def test_escape_is_offered_while_a_dialog_is_up_and_closes_it(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/search-modal-escape.html")
    escape = key(page, "Escape")
    assert escape["label"] == "Press Escape to close Search the docs"
    assert "node" not in escape
    assert "Pricing" not in [element["label"] for element in page["elements"]]
    session.act(escape, page)
    page = session.observe()
    assert key(page, "Escape") is None
    assert "Pricing" in [element["label"] for element in page["elements"]]


def test_a_page_with_no_dialog_offers_no_escape(session, fixture_server):
    assert key(session.open(f"{fixture_server}/sites/static.html"), "Escape") is None
