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
# A check a person has to answer, as the page shows it: a vendor's widget that is on screen and has
# not been given its token yet, or a vendor's challenge page. The widgets live in frames the page
# cannot read, so what is read is their container and the response field the vendor fills once
# the check is answered. An invisible widget asks nobody anything and is not one.
CHALLENGE_JS = """(() => {
  const shown = e => { const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && e.checkVisibility({checkVisibilityCSS: true}); };
  const widgets = [
    ['reCAPTCHA', '.g-recaptcha:not([data-size="invisible"])', 'g-recaptcha-response'],
    ['hCaptcha', '.h-captcha:not([data-size="invisible"])', 'h-captcha-response'],
    ['Turnstile', '.cf-turnstile', 'cf-turnstile-response'],
  ];
  for (const [name, selector, field] of widgets)
    for (const box of document.querySelectorAll(selector))
      if (!box.querySelector('.grecaptcha-badge') && shown(box) && !box.querySelector(`[name="${field}"]`)?.value)
        return name;
  if (window._cf_chl_opt || document.querySelector('form#challenge-form[action*="__cf_chl"]'))
    return 'Cloudflare challenge';
  const hold = document.getElementById('px-captcha');
  if (hold && shown(hold)) return 'press and hold';
  if (document.querySelector('iframe#sec-cpt-if, iframe[src*="/_sec/cp_challenge/"]')) return 'Akamai challenge';
  return '';
})"""


def snapshot_expression(max_elements=MAX_ELEMENTS):
    """The snapshot call as an evaluable expression, capped at `max_elements`."""
    options = json.dumps({"max_elements": max_elements})
    return (
        f"(() => {{ const quiet={QUIET_STATE_JS}(); const page=({SNAPSHOT_JS})({options}); "
        f"if (page) {{ page.leaving=quiet.leaving; page.challenge=({CHALLENGE_JS})(); }} return page; }})()"
    )


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
