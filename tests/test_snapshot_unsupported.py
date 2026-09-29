"""What no operation can do is not offered as something a press could do instead."""

import pytest

pytestmark = pytest.mark.browser


def labels(page):
    return [action["label"] for action in page["actions"]]


def test_row_actions_painted_only_under_the_pointer_are_not_offered(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/row-hover-actions.html")
    assert "Archive" not in labels(page)
    assert "Delete" not in labels(page)


def test_a_menu_that_opens_on_the_right_button_is_not_offered_and_neither_are_its_rows(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/context-menu.html")
    assert not {"Move to trash", "Rename", "📊 budget.xlsx"} & set(labels(page))


def test_a_frame_from_another_origin_is_one_element_that_says_where_it_is_served_from(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/payment-frame.html")
    frame = next(element for element in page["elements"] if element["role"] == "frame")
    port = fixture_server.rsplit(":", 1)[1]
    assert (frame["label"], frame["host"]) == ("Secure card payment input frame", f"localhost:{port}")
    assert not [action for action in page["actions"] if "Card number" in action["label"]]
