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
