"""A menu that opens on hover needs a pointer that moves, which is what a person has."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/hover-menu.html"


def labels(page):
    return [element["label"] for element in page["elements"]]


def test_the_menu_is_closed_until_something_hovers_it(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "스킨케어" not in labels(page)


def test_hovering_a_menu_opens_it(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    trigger = next(e for e in page["elements"] if e["label"] == "카테고리")
    session.hover(trigger["node"])
    page = session.observe()
    assert "스킨케어" in labels(page)


def test_and_the_item_it_reveals_can_be_clicked(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    trigger = next(e for e in page["elements"] if e["label"] == "카테고리")
    session.hover(trigger["node"])
    page = session.observe()
    action = next(a for a in page["actions"] if a["label"] == "스킨케어" and a["kind"] == "click")
    session.act(action, page)
    assert "dispCatNo=1000" in session.observe()["url"]


def test_a_click_arrives_with_the_pointer_so_the_menu_it_opens_is_seen(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    action = next(a for a in page["actions"] if a["label"] == "카테고리" and a["kind"] == "click")
    session.act(action, page)
    assert "스킨케어" in labels(session.observe())


def test_hovering_refuses_anything_that_is_not_an_observed_node(session, fixture_server):
    session.open(fixture_server + FIXTURE)
    with pytest.raises(ValueError, match="observed node"):
        session.hover("#trigger")
