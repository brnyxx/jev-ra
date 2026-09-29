"""A button that stays pressed says so, and pressing it is an answer the wait can see."""

import pytest

pytestmark = pytest.mark.browser


def chip(page, label):
    return next(element for element in page["elements"] if element["label"] == label)


def test_a_toggle_button_is_read_with_whether_it_is_pressed(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/client-table.html")
    assert chip(page, "In stock")["pressed"] == "false"
    session.act(next(a for a in page["actions"] if a["label"] == "In stock"), page)
    assert chip(session.observe(), "In stock")["pressed"] == "true"
