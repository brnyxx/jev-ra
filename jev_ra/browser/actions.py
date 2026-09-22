"""Turn an observed page into the operations, targets and controls a decision may choose from."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import MAX_ELEMENTS

OPERATIONS = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
STATE_KEYS = ("checked", "selected", "expanded")
HOSTNAME = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}\b", re.IGNORECASE)
# Labels that belong to the registry rather than to anyone: seoul.go.kr and busan.go.kr are two
# sites, and www.seoul.go.kr is one site with the front page of seoul.go.kr.
SHARED_LABELS = frozenset({"ac", "co", "com", "edu", "go", "gov", "ne", "net", "or", "org"})


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


def site(host):
    """The registrable part of a host: enough to tell one site from another, and no more."""
    host = (host or "").lower()
    labels = host.split(".")
    if len(labels) < 3 or host.replace(".", "").isdigit():
        return host
    return ".".join(labels[-3:] if labels[-2] in SHARED_LABELS else labels[-2:])


def home_sites(url, goal):
    """The sites this run belongs on: the one it is standing on, plus any the goal names."""
    sites = {site(urlsplit(url or "").hostname or "")}
    sites |= {site(match.group(0)) for match in HOSTNAME.finditer(goal or "")}
    return sites - {""}


def elsewhere(page, elements, goal):
    """The refs whose link leaves the sites this run belongs on.

    Leaving the site is almost always wrong: a page with nothing but anchors on it walks off into
    whatever it links to and ends stuck three hops away. Off-site links stay on offer - a goal is
    sometimes exactly one of them - but they are offered after everything still on the site.
    """
    home = home_sites(page.get("url", ""), goal)
    return {element["ref"] for element in elements if element.get("host") and site(element["host"]) not in home}


def build(page, max_elements=MAX_ELEMENTS, goal=""):
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
    away = elsewhere(page, elements, goal)
    ordered = {
        operation: dict(sorted(candidates.items(), key=lambda item: item[1]["id"] in away))
        for operation, candidates in targets.items()
    }
    return ActionSpace(elements=elements, targets=ordered, controls=controls, omitted=omitted)


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
