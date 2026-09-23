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
