"""Turn an observed page into the operations, targets and controls a decision may choose from."""

from dataclasses import dataclass

from . import MAX_ELEMENTS

OPERATIONS = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
STATE_KEYS = ("checked", "selected", "expanded")


@dataclass(frozen=True)
class ActionSpace:
    """The operations, targets and controls one observed page offers."""

    elements: list
    targets: dict
    controls: dict
    omitted: int = 0

    def offered(self):
        """Every operation name a decision may choose from."""
        return list(self.targets) + list(self.controls)

    def action(self, operation, target=None):
        """The action behind an operation, or an operation and target pair."""
        if operation in self.controls:
            return self.controls[operation]
        return self.targets[operation][target]

    def describe(self, target, action):
        """Render one target as `[ref] role label · value`."""
        parts = [f"[{target}]", action.get("role") or action["kind"], action.get("label", "")]
        value = action.get("current_value") if action["kind"] == "select" else action.get("value")
        line = " ".join(part for part in parts if part)
        return f"{line} · {value}" if value else line


def build(page, max_elements=MAX_ELEMENTS):
    """Group an observed page into per-operation targets and page controls."""
    elements, seen = [], set()
    for element in page.get("elements", []):
        node = element.get("node")
        if node in seen:
            continue
        seen.add(node)
        elements.append(element)
    omitted = page.get("omitted", 0) + max(0, len(elements) - max_elements)
    elements = elements[:max_elements]
    refs = {element["ref"] for element in elements}
    targets, controls, options = {}, {}, {}
    for action in page.get("actions", []):
        operation = OPERATIONS.get(action["kind"])
        if operation is None:
            controls[action["id"].upper()] = action
            continue
        ref = action["id"]
        if ref not in refs:
            continue
        if operation == "SELECT":
            options[ref] = options.get(ref, 0) + 1
            target = f"{ref}:{options[ref]}"
        else:
            target = ref
        targets.setdefault(operation, {})[target] = action
    return ActionSpace(elements=elements, targets=targets, controls=controls, omitted=omitted)


def element_view(element):
    """The per-element row sent to Jev: identity and meaning, never geometry."""
    view = {"ref": element["ref"], "role": element.get("role"), "label": element.get("label", "")}
    value = element.get("value")
    if value:
        view["value"] = value
    for key in STATE_KEYS:
        if key in element:
            view[key] = element[key]
    return view
