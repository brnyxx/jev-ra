import time

import pytest

from jev_ra.browser import marker_expression, snapshot_expression

pytestmark = pytest.mark.browser


def evaluate(call, expression, await_promise=False):
    response = call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
    assert not response.get("exceptionDetails"), response.get("exceptionDetails")
    return response.get("result", {}).get("value")


def load(call, url):
    call("Page.navigate", url=url)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if evaluate(call, "document.readyState") == "complete":
            return evaluate(call, snapshot_expression())
    raise AssertionError(f"{url} did not finish loading")


def by_label(page, label):
    return next(element for element in page["elements"] if element["label"] == label)


def test_form_elements_carry_roles_labels_and_refs(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/form.html")
    assert page["title"] == "Booking form"
    assert (page["w"], page["h"]) == (1280, 900)
    assert [element["ref"] for element in page["elements"]][:3] == ["e1", "e2", "e3"]
    assert by_label(page, "City")["role"] == "textbox"
    assert by_label(page, "City")["value"] == "Zurich"
    assert by_label(page, "Email")["role"] == "textbox"
    assert by_label(page, "Guests")["role"] == "spinbutton"
    assert by_label(page, "Cabin")["role"] == "combobox"
    assert by_label(page, "Refundable")["checked"] == "false"
    assert page["omitted"] == 0


def test_unsafe_disabled_and_readonly_controls_are_constrained(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/form.html")
    labels = [element["label"] for element in page["elements"]]
    assert "Unavailable" not in labels
    assert not any("never expose this" in str(element.get("value")) for element in page["elements"])
    kinds = {action["kind"] for action in page["actions"] if action["label"] == "Reference"}
    assert kinds == {"click"}
    assert {action["kind"] for action in page["actions"] if action["label"] == "City"} == {"fill"}


def test_editable_fields_offer_fill_and_an_open_click(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/form.html")
    city = by_label(page, "City")["ref"]
    kinds = {action["kind"] for action in page["actions"] if action["id"] == city}
    assert kinds == {"fill", "click"}
    assert any(action["label"] == "Open City" for action in page["actions"])


def test_select_offers_one_action_per_available_option(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/form.html")
    options = [action for action in page["actions"] if action["kind"] == "select"]
    assert [action["value"] for action in options] == ["business"]
    assert options[0]["label"] == "Cabin → Business"
    assert options[0]["current_value"] == "Economy"


def test_an_unlabelled_select_is_named_by_its_selection_not_its_option_list(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/sites/select-options.html")
    select = by_label(page, "Select a country")
    assert select["value"] == "Select a country"
    options = [action for action in page["actions"] if action["kind"] == "select"]
    assert options[0]["label"] == "Select a country → Argentina"
    assert all(len(action["label"]) < 60 for action in options)


def test_enter_is_offered_once_a_focused_field_holds_text(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/sites/enter-submit.html")
    assert not any(action["id"] == "press_enter" for action in page["actions"])
    evaluate(cdp_target, "document.getElementById('q').focus()")
    assert not any(action["id"] == "press_enter" for action in evaluate(cdp_target, snapshot_expression())["actions"])
    evaluate(cdp_target, "document.getElementById('q').value='red shoes'")
    armed = evaluate(cdp_target, snapshot_expression())["actions"]
    press = next(action for action in armed if action["id"] == "press_enter")
    assert (press["kind"], press["key"]) == ("press", "Enter")


def test_links_are_observed_with_their_text(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/list.html")
    links = [element for element in page["elements"] if element["role"] == "link"]
    assert [element["label"] for element in links] == ["Booking form", "Autocomplete", "External reference"]
    assert "hidden" not in page["text"].lower()
    assert "On incompleteness" in page["text"]


def test_marker_is_stable_across_a_no_op_and_changes_after_typing(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/form.html")
    evaluate(cdp_target, "document.getElementById('city').style.transform='translateX(40px)'")
    assert evaluate(cdp_target, marker_expression()) == page["marker"]
    evaluate(cdp_target, "document.getElementById('city').value='London'")
    assert evaluate(cdp_target, marker_expression()) != page["marker"]


def test_guards_are_captured_per_node_and_go_null_when_hidden(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/form.html")
    submit = by_label(page, "Search flights")
    assert page["guards"][str(submit["node"])][2] == "Search flights"
    evaluate(cdp_target, "document.getElementById('submit').style.display='none'")
    reread = evaluate(cdp_target, f"window.__jevRa.guard(window.__jevRa.nodes.get({submit['node']}))")
    assert reread is None


def test_element_cap_reports_the_omitted_remainder(fixture_server, cdp_target):
    load(cdp_target, f"{fixture_server}/list.html")
    page = evaluate(cdp_target, snapshot_expression(max_elements=2))
    assert len(page["elements"]) == 2
    assert page["omitted"] >= 1
    assert {action["id"] for action in page["actions"] if action["kind"] == "click"} <= {"e1", "e2"}


def test_scroll_actions_appear_only_when_the_page_can_scroll(fixture_server, cdp_target):
    page = load(cdp_target, f"{fixture_server}/form.html")
    ids = {action["id"] for action in page["actions"]}
    assert "wait" in ids
    assert "scroll_up" not in ids
