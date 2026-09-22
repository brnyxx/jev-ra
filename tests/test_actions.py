from jev_ra.browser import actions


def click(ref, node, label, role="button", **extra):
    return {"id": ref, "node": node, "role": role, "kind": "click", "label": label, **extra}


def page_with(elements, action_list, omitted=0):
    return {"elements": elements, "actions": action_list, "omitted": omitted}


def element(ref, node, label, role="button", **extra):
    return {"ref": ref, "node": node, "role": role, "label": label, "rect": {"x": 0, "y": 0, "w": 1, "h": 1}, **extra}


FORM = page_with(
    [
        element("e1", 1, "City", role="textbox", value="Zurich"),
        element("e2", 2, "Cabin", role="combobox", value="Economy"),
        element("e3", 3, "Search flights"),
    ],
    [
        {"id": "e1", "node": 1, "role": "textbox", "kind": "fill", "label": "City", "value": "Zurich"},
        click("e1", 1, "Open City", role="textbox", value="Zurich"),
        {
            "id": "e2",
            "node": 2,
            "role": "combobox",
            "kind": "select",
            "label": "Cabin → Business",
            "value": "business",
            "current_value": "Economy",
        },
        {
            "id": "e2",
            "node": 2,
            "role": "combobox",
            "kind": "select",
            "label": "Cabin → First",
            "value": "first",
            "current_value": "Economy",
        },
        click("e3", 3, "Search flights"),
        {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
        {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
    ],
)


def test_elements_are_deduped_per_node():
    duplicated = page_with([element("e1", 1, "City"), element("e2", 1, "City again")], [])
    assert [item["ref"] for item in actions.build(duplicated).elements] == ["e1"]


def test_editable_elements_offer_both_fill_and_click():
    space = actions.build(FORM)
    assert set(space.targets["TYPE_TEXT"]) == {"e1"}
    assert set(space.targets["CLICK"]) == {"e1", "e3"}
    assert space.targets["CLICK"]["e1"]["label"] == "Open City"


def test_select_targets_are_numbered_per_option():
    space = actions.build(FORM)
    assert list(space.targets["SELECT"]) == ["e2:1", "e2:2"]
    assert space.action("SELECT", "e2:2")["value"] == "first"


def test_controls_are_offered_only_when_the_page_offers_them():
    space = actions.build(FORM)
    assert set(space.controls) == {"SCROLL_DOWN", "WAIT"}
    assert "SCROLL_UP" not in space.offered()
    assert actions.build(page_with([], [])).controls == {}


def test_targets_ignore_actions_whose_element_was_cut():
    space = actions.build(FORM, max_elements=1)
    assert [item["ref"] for item in space.elements] == ["e1"]
    assert set(space.targets["CLICK"]) == {"e1"}
    assert "SELECT" not in space.targets
    assert space.omitted == 2


def test_the_element_cap_accumulates_what_the_snapshot_already_dropped():
    many = page_with([element(f"e{n}", n, f"Item {n}") for n in range(1, 301)], [], omitted=40)
    space = actions.build(many)
    assert len(space.elements) == 250
    assert space.omitted == 90


def test_describe_renders_ref_role_label_and_value():
    space = actions.build(FORM)
    assert space.describe("e1", space.action("TYPE_TEXT", "e1")) == "[e1] textbox City · Zurich"
    assert space.describe("e3", space.action("CLICK", "e3")) == "[e3] button Search flights"
    assert space.describe("e2:1", space.action("SELECT", "e2:1")) == "[e2:1] combobox Cabin → Business · Economy"


def test_element_view_keeps_meaning_and_drops_geometry():
    view = actions.element_view(element("e4", 4, "Refundable", role="checkbox", checked="false"))
    assert view == {"ref": "e4", "role": "checkbox", "label": "Refundable", "checked": "false"}


LINKS = {
    "url": "https://en.wikipedia.org/wiki/Zebra",
    "elements": [
        element("e1", 1, "Learn more", role="link", host="www.iana.org"),
        element("e2", 2, "Reserved names", role="link", host="www.rfc-editor.org"),
        element("e3", 3, "Talk", role="link"),
        element("e4", 4, "한국어", role="link", host="ko.wikipedia.org"),
    ],
    "actions": [
        click("e1", 1, "Learn more", role="link"),
        click("e2", 2, "Reserved names", role="link"),
        click("e3", 3, "Talk", role="link"),
        click("e4", 4, "한국어", role="link"),
    ],
    "omitted": 0,
}


def test_the_registrable_part_is_what_tells_two_sites_apart():
    assert actions.site("en.wikipedia.org") == "wikipedia.org"
    assert actions.site("www.seoul.go.kr") == "seoul.go.kr"
    assert actions.site("example.com") == "example.com"
    assert actions.site("localhost") == "localhost"
    assert actions.site("127.0.0.1") == "127.0.0.1"
    assert actions.site("") == ""


def test_another_language_of_the_same_site_is_not_somewhere_else():
    assert [target for target in actions.build(LINKS).targets["CLICK"]] == ["e3", "e4", "e1", "e2"]


def test_a_goal_that_names_a_host_brings_that_host_home():
    space = actions.build(LINKS, goal="Check what iana.org reserves example.com for.")
    assert [target for target in space.targets["CLICK"]] == ["e1", "e3", "e4", "e2"]


def test_the_goal_is_read_for_hostnames_only():
    assert actions.home_sites("https://en.wikipedia.org/wiki/Zebra", "Open the Korean version") == {"wikipedia.org"}
    assert "iana.org" in actions.home_sites("", "Open iana.org and read it.")


def walled_page(*labels, role="button"):
    """A form with a consent wall over it, the wall's controls carrying the labels given."""
    elements = [element("e1", 1, "City", role="textbox", value=""), element("e2", 2, "Search flights")]
    action_list = [
        {"id": "e1", "node": 1, "role": "textbox", "kind": "fill", "label": "City", "value": ""},
        click("e2", 2, "Search flights"),
        {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560},
        {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
    ]
    for index, label in enumerate(labels, start=3):
        ref = f"e{index}"
        elements.append(element(ref, index, label, role=role, overlay="true"))
        action_list.append(click(ref, index, label, role=role))
    return page_with(elements, action_list)


def offered_labels(space):
    return [action["label"] for candidates in space.targets.values() for action in candidates.values()]


def test_a_wall_that_can_be_accepted_leaves_only_its_accept_on_offer():
    space = actions.build(walled_page("Accept Cookies", "Choose Cookies"))
    assert space.offered() == ["CLICK"]
    assert offered_labels(space) == ["Accept Cookies"]


def test_the_accept_may_be_said_in_the_language_of_the_site():
    for label in ("同意する", "동의", "I agree", "OK"):
        space = actions.build(walled_page(label, "Reject"))
        assert offered_labels(space) == [label], label


def test_a_wall_that_only_refuses_changes_nothing():
    space = actions.build(walled_page("Reject all", "Manage choices"))
    assert "TYPE_TEXT" in space.offered()
    assert "SCROLL_DOWN" in space.offered()


def test_cookies_is_not_an_ok():
    space = actions.build(walled_page("Cookies on this site", "Bookmark"))
    assert "TYPE_TEXT" in space.offered()


def test_a_checkbox_that_agrees_is_a_field_not_a_way_through():
    space = actions.build(walled_page("I agree to the terms", role="checkbox"))
    assert "TYPE_TEXT" in space.offered()


def test_an_accept_that_is_not_on_a_wall_changes_nothing():
    page = walled_page("Accept Cookies")
    for item in page["elements"]:
        item.pop("overlay", None)
    space = actions.build(page)
    assert "TYPE_TEXT" in space.offered()
