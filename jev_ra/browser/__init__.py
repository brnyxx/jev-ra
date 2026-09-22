"""Browser core: one snapshot expression, one CDP target, guarded actions."""

import json
from pathlib import Path

SNAPSHOT_JS = Path(__file__).with_name("snapshot.js").read_text()
MAX_ELEMENTS = 250
SCROLL_DELTA = 560
# The page says when it last changed, so nothing has to ask it ten times a second: one
# MutationObserver and one counter per document. Every reading of the page installs it, because
# the reading an action was chosen from is when the stillness that follows the action starts.
QUIET_STATE_JS = """(() => window.__jevRaQuiet ||= (() => {
  const own = {last: performance.now(), count: 0, frames: 0, leaving: false};
  new MutationObserver(() => { own.last = performance.now(); own.count++; })
    .observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  addEventListener('beforeunload', () => { own.leaving = true; });
  return own;
})())"""


def snapshot_expression(max_elements=MAX_ELEMENTS):
    """The snapshot call as an evaluable expression, capped at `max_elements`."""
    options = json.dumps({"max_elements": max_elements})
    return f"(() => {{ {QUIET_STATE_JS}(); return ({SNAPSHOT_JS})({options}); }})()"


def marker_expression(max_elements=MAX_ELEMENTS):
    """An expression returning only the page marker, for cheap freshness checks."""
    return f"(() => {{ const page={snapshot_expression(max_elements)}; return page?.marker ?? null; }})()"


def guard_expression(node):
    """An expression returning the page key and one node's guard."""
    if type(node) is not int:
        raise ValueError("A guard is only ever taken for an observed node id")
    return (
        "(() => { const cache=window.__jevRa; "
        f"return cache ? [cache.pageKey(), cache.guard(cache.nodes.get({node}))] : null; }})()"
    )
