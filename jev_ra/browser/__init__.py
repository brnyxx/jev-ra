"""Browser core: one snapshot expression, one CDP target, guarded actions."""

import json
from pathlib import Path

SNAPSHOT_JS = Path(__file__).with_name("snapshot.js").read_text()
MAX_ELEMENTS = 250
SCROLL_DELTA = 560


def snapshot_expression(max_elements=MAX_ELEMENTS):
    return f"({SNAPSHOT_JS})({json.dumps({'max_elements': max_elements})})"


def marker_expression(max_elements=MAX_ELEMENTS):
    return f"(() => {{ const page={snapshot_expression(max_elements)}; return page?.marker ?? null; }})()"


def guard_expression(node):
    if type(node) is not int:
        raise ValueError("A guard is only ever taken for an observed node id")
    return (
        "(() => { const cache=window.__jevRa; "
        f"return cache ? [cache.pageKey(), cache.guard(cache.nodes.get({node}))] : null; }})()"
    )
