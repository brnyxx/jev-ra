"""Scrolling moves what a person scrolls: the page, or the box the page scrolls inside."""

import pytest

pytestmark = pytest.mark.browser


def control(page, name):
    return next((action for action in page["actions"] if action["id"] == name), None)


def labels(page):
    return [element["label"] for element in page["elements"]]


def box_scroll(session, selector):
    return session.evaluate(f"document.querySelector('{selector}').scrollTop")


def test_an_app_shell_that_never_scrolls_its_window_scrolls_its_main_box(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/inner-scroll.html")
    down = control(page, "scroll_down")
    assert down is not None
    assert isinstance(down["node"], int)
    assert "Export all data" not in labels(page)
    session.act(down, page)
    page = session.observe()
    assert box_scroll(session, "main") > 0
    assert page["scroll"]["y"] == 0
    assert "Export all data" in labels(page)


def test_a_box_scrolled_down_can_be_scrolled_back_up(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/inner-scroll.html")
    assert control(page, "scroll_up") is None
    session.act(control(page, "scroll_down"), page)
    page = session.observe()
    session.act(control(page, "scroll_up"), page)
    session.observe()
    assert box_scroll(session, "main") == 0


def test_a_virtualized_list_renders_the_rows_it_is_scrolled_to(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/virtual-list.html")
    for _ in range(3):
        session.act(control(page, "scroll_down"), page)
        page = session.observe()
    assert "INV-0001" not in labels(page)
    assert "INV-0030" in labels(page)


def test_scrolling_a_page_moves_the_page_even_with_a_code_sample_under_the_middle(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/code-sample-scroll.html")
    down = control(page, "scroll_down")
    assert "node" not in down
    session.act(down, page)
    page = session.observe()
    assert page["scroll"]["y"] > 0
    assert box_scroll(session, "pre") == 0


def test_a_page_whose_window_scrolls_offers_the_window_as_it_always_did(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/below-the-fold.html")
    assert control(page, "scroll_down") == {
        "id": "scroll_down",
        "kind": "scroll",
        "label": "Scroll down",
        "delta": 560,
    }
