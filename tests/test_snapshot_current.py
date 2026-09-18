"""The active item in a group has to be observable, or no "switch to X" goal can be verified."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/sort-bar.html"


def by_label(page, label):
    return next(element for element in page["elements"] if element["label"] == label)


def test_a_state_class_on_the_wrapping_item_marks_the_active_sort(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert by_label(page, "신상품순").get("current") == "true"
    assert "current" not in by_label(page, "인기순")
    assert "current" not in by_label(page, "낮은가격순")


def test_aria_current_marks_the_page_you_are_on(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert by_label(page, "2").get("current") == "true"
    assert "current" not in by_label(page, "1")


def test_a_selected_tab_is_already_reported_and_stays_that_way(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert by_label(page, "Details")["selected"] == "true"
    assert by_label(page, "Reviews")["selected"] == "false"


def test_the_word_active_in_ordinary_prose_marks_nothing(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert all("current" not in element for element in page["elements"] if element["role"] != "link"
               or element["label"] not in {"신상품순", "2"})
