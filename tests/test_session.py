import pytest

from jev_ra.browser.session import StalePage

pytestmark = pytest.mark.browser


def action_for(page, label, kind):
    return next(a for a in page["actions"] if a["label"] == label and a["kind"] == kind)


def test_open_returns_the_observed_page(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    assert page["title"] == "Booking form"
    assert page["url"].endswith("/form.html")
    assert any(element["label"] == "Search flights" for element in page["elements"])


def test_click_by_ref_changes_the_marker(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    session.act(action_for(page, "Refundable", "click"), page)
    assert session.evaluate("document.getElementById('refundable').checked") is True
    assert not session.fresh(page)


def test_fill_types_through_trusted_input(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    session.act(action_for(page, "City", "fill"), page, text="London")
    assert session.evaluate("document.getElementById('city').value") == "London"
    assert session.observe()["elements"][0]["value"] == "London"


def test_fill_without_text_is_refused_before_any_input(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    with pytest.raises(ValueError, match="needs a string"):
        session.act(action_for(page, "City", "fill"), page)
    assert session.evaluate("document.getElementById('city').value") == "Zurich"


def test_select_picks_an_observed_option(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    session.act(action_for(page, "Cabin → Business", "select"), page)
    assert session.evaluate("document.getElementById('cabin').value") == "business"


def test_stale_page_when_the_target_guard_differs(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    submit = action_for(page, "Search flights", "click")
    session.evaluate("document.getElementById('submit').textContent='Delete account'")
    with pytest.raises(StalePage, match="Page changed"):
        session.act(submit, page)


def test_unrelated_offscreen_change_keeps_the_click_guard_fresh(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    submit = action_for(page, "Search flights", "click")
    session.evaluate("document.title='Renamed'")
    assert session.fresh(page, submit)
    assert not session.fresh(page)


def test_covered_element_is_rejected_before_input(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    submit = action_for(page, "Search flights", "click")
    session.evaluate(
        "const cover=document.createElement('div');"
        "cover.style.cssText='position:fixed;inset:0;z-index:9999;background:white';"
        "document.body.append(cover)"
    )
    assert session.fresh(page, submit)
    with pytest.raises(StalePage, match="covered"):
        session.act(submit, page)
    assert session.evaluate("document.getElementById('status').textContent") == "Nothing submitted yet."


def test_press_enter_submits_the_form(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    session.act(action_for(page, "City", "fill"), page, text="Lisbon")
    session.press("Enter")
    assert session.evaluate("document.getElementById('status').textContent") == "Submitted Lisbon"


def test_press_rejects_keys_outside_the_supported_set(session):
    with pytest.raises(ValueError, match="press supports"):
        session.press("F5")


def test_fill_waits_for_asynchronous_combobox_suggestions(session, fixture_server):
    page = session.open(f"{fixture_server}/autocomplete.html")
    session.act(action_for(page, "Destination", "fill"), page, text="London")
    after = session.observe()
    assert [element["label"] for element in after["elements"] if element["role"] == "option"] == [
        "London Heathrow",
        "London Gatwick",
    ]


def test_scroll_and_wait_need_no_target(session, fixture_server):
    page = session.open(f"{fixture_server}/list.html")
    assert session.act({"id": "wait", "kind": "wait", "label": "Wait"}, page)["executed"] == "wait"


def test_screenshot_returns_jpeg_bytes(session, fixture_server):
    session.open(f"{fixture_server}/form.html")
    image = session.screenshot()
    assert image[:3] == b"\xff\xd8\xff"
    assert len(image) > 1000
