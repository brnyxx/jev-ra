"""Open shadow roots and same-origin frames are part of the same observed page."""

import pytest

pytestmark = pytest.mark.browser


def labels(page):
    return [element["label"] for element in page["elements"]]


def by_label(page, label):
    return next(element for element in page["elements"] if element["label"] == label)


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def test_controls_inside_an_open_shadow_root_are_listed_with_refs(session, fixture_server):
    page = session.open(f"{fixture_server}/shadow.html")
    assert "Light button" in labels(page)
    assert "Newest first" in labels(page)
    assert "Shadow query" in labels(page)
    shadow = by_label(page, "Newest first")
    assert shadow["ref"].startswith("e")
    assert shadow["nested"] is True
    assert by_label(page, "Light button").get("nested") is None


def test_a_shadow_button_is_clickable_through_its_ref(session, fixture_server):
    page = session.open(f"{fixture_server}/shadow.html")
    session.act(action_for(page, "Newest first", "click"), page)
    assert session.evaluate("document.getElementById('status').textContent") == "Sorted: Newest first"


def test_a_control_two_shadow_roots_down_is_reachable(session, fixture_server):
    page = session.open(f"{fixture_server}/shadow.html")
    assert "Buy deeply" in labels(page)
    session.act(action_for(page, "Buy deeply", "click"), page)
    assert session.evaluate("document.getElementById('status').textContent") == (
        "Bought from two shadow roots down"
    )


def test_typing_into_a_shadow_field_works(session, fixture_server):
    page = session.open(f"{fixture_server}/shadow.html")
    session.act(action_for(page, "Shadow query", "fill"), page, text="lipstick")
    value = session.evaluate("document.querySelector('sort-bar').shadowRoot.getElementById('query').value")
    assert value == "lipstick"


def test_shadow_text_reaches_the_page_text(session, fixture_server):
    page = session.open(f"{fixture_server}/shadow.html")
    assert "Newest first" in page["text"]


def test_same_origin_frame_controls_are_listed_and_clickable(session, fixture_server):
    page = session.open(f"{fixture_server}/iframe.html")
    assert "Outer button" in labels(page)
    assert "Frame button" in labels(page)
    assert by_label(page, "Frame button")["nested"] is True
    session.act(action_for(page, "Frame button", "click"), page)
    inner = session.evaluate(
        "document.getElementById('same-origin').contentDocument"
        ".getElementById('inner-status').textContent"
    )
    assert inner == "Frame button pressed"


def test_typing_into_a_same_origin_frame_field_works(session, fixture_server):
    page = session.open(f"{fixture_server}/iframe.html")
    session.act(action_for(page, "Frame field", "fill"), page, text="Zurich")
    value = session.evaluate(
        "document.getElementById('same-origin').contentDocument.getElementById('frame-field').value"
    )
    assert value == "Zurich"


def test_a_cross_origin_frame_is_one_opaque_element(session, fixture_server):
    page = session.open(f"{fixture_server}/iframe.html")
    frames = [element for element in page["elements"] if element["role"] == "frame"]
    assert [element["label"] for element in frames] == ["Cross origin frame"]
    # The readable frame is traversed instead of offered, so it is not in the list.
    assert "Same origin frame" not in labels(page)


def test_acting_on_a_cross_origin_frame_does_not_raise(session, fixture_server):
    page = session.open(f"{fixture_server}/iframe.html")
    frame = next(a for a in page["actions"] if a["label"] == "Cross origin frame")
    assert session.act(frame, page)["executed"] == frame["id"]
    assert session.observe()["url"].endswith("/iframe.html")
