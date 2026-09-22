"""A field that opens an editor of its own and moves focus into it has handed the typing over."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/field-opens-editor.html"


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def value(session, element_id):
    return session.evaluate(f"document.getElementById('{element_id}').value")


def test_typing_into_a_field_that_opens_its_own_editor_types_into_the_editor(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Where from?", "fill"), page, text="Zurich")
    page = session.observe()
    assert value(session, "editing") == "Zurich"
    assert value(session, "origin") == "Busan"
    assert value(session, "destination") == ""
    options = [element["label"] for element in page["elements"] if element["role"] == "option"]
    assert options == ["Zurich", "Zurich Airport (ZRH)"]


def test_a_dropped_click_does_not_type_into_the_field_that_already_held_focus(session, fixture_server):
    session.click = lambda _target: None
    page = session.open(fixture_server + FIXTURE)
    session.act(action_for(page, "Passenger name", "fill"), page, text="Ada Lovelace")
    assert value(session, "passenger") == "Ada Lovelace"
    assert value(session, "destination") == ""
