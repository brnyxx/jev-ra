"""One CDP target, observed atomically and driven with trusted input only."""

import base64
import json
import logging
import sys
import time

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

from ..config import load
from ..errors import ChromeError, StalePage
from ..profile import NullTimer
from . import MAX_ELEMENTS, guard_expression, marker_expression, snapshot_expression
from .chrome import ensure as ensure_chrome

logger = logging.getLogger(__name__)

LOAD_TIMEOUT_S = 15.0
# A single-page app reports the document complete long before it paints anything, and a page with
# nothing to act on reads as BLOCKED. Wait for the document to hold a control anywhere - not just
# in the viewport, since a listing can legitimately open above its own controls.
PAINT_BUDGET_S = 2.0
CONTROLS_JS = (
    "document.querySelectorAll('a[href],button,input,select,textarea,"
    "[role=\"button\"],[role=\"link\"],[contenteditable=\"\"],[contenteditable=\"true\"]').length"
)
# The daemon's own default budget is 5 s, which a plain call never needs and the snapshot of a
# large page routinely exceeds: oliveyoung.co.kr evaluates for longer than that, and the timeout
# arrived as a transport exception from inside browser_harness rather than as anything a caller
# could handle. Give the evaluating calls room, and turn what is left into ChromeError.
CALL_TIMEOUT_S = 5.0
EVALUATE_TIMEOUT_S = 30.0
WAIT_SLEEP_S = 0.1
SETTLE_ATTEMPTS = 10
# After input, keep reading the marker until two readings agree. A single-page app re-renders
# well after its two frames are up, and a half-rendered page reads as one with nothing to do.
QUIET_INTERVAL_S = 0.06
QUIET_BUDGET_S = 0.6
# Fonts and media cost bytes and answer nothing. Images are deliberately NOT here: blocking
# them on en.wikipedia.org drops the observed controls from 62 to 34, because real layouts
# size themselves around their images and half the page then falls outside the viewport.
# jev-ra search blocks the heavier list in its reading tabs, where only extracted text is used.
BLOCKED_URLS = (
    "*.woff", "*.woff2", "*.ttf", "*.otf", "*.eot",
    "*.mp4", "*.webm", "*.mp3", "*.m4a", "*.avi", "*.mov",
)
# An action with a target is guarded by that target: its identity, its state and the text of the
# block it sits in, plus the page key. The whole-page marker carries every word on the page, so a
# departures board or a price ticker would refuse every action on a page that is working fine.
TARGETED = {"click", "select", "fill"}
# The daemon reports a document that moved under a call as a protocol error. It means the same
# thing as any other stale reading - observe again - rather than a browser that has gone away.
MOVED = ("navigated or closed", "context was destroyed", "cannot find context", "no frame for given id")
KEYS = {
    "Enter": (13, "Enter", "\r"),
    "Escape": (27, "Escape", ""),
    "Tab": (9, "Tab", ""),
}

# Code-owned node ids refer to observed elements. A decision never supplies a selector.
RESOLVE_JS = """(action => {
  const cache=window.__jevRa;
  const e=cache?.nodes.get(action.node);
  // Laid out and kept by the accessibility tree; transparency is settled by the hit test below,
  // which is the same rule the snapshot used when it offered this target.
  if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
      !e.checkVisibility({checkVisibilityCSS:true})) return null;
  if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
  const r=e.getBoundingClientRect(), [dx,dy]=cache.offset(e);
  const local={x:r.x+r.width/2, y:r.y+r.height/2};
  const x=local.x+dx, y=local.y+dy;
  if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
  // Hit-test in the element's own root: elementFromPoint stops at a shadow host otherwise.
  const hit=cache.deepest(e.ownerDocument, local.x, local.y);
  if (!cache.reaches(e,hit)) return null;
  if (action.kind==='select') {
    if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
        !o.disabled && !o.closest('optgroup[disabled]'))) return null;
    e.value=action.value;
    e.dispatchEvent(new Event('input',{bubbles:true}));
    e.dispatchEvent(new Event('change',{bubbles:true}));
  }
  return {x,y};
})"""

# Two frames settle ordinary input; a combobox gets up to 200 ms for real suggestions.
SETTLE_JS = """(action => new Promise(resolve => {
  const cache=window.__jevRa;
  const field=cache?.nodes.get(action.node);
  const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
  let frames=0, stopped=false;
  const finish=()=>{stopped=true;resolve()};
  setTimeout(finish, autocomplete ? 200 : 50);
  const ready=()=>{
    if (stopped) return;
    const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
      .split(/\\s+/).filter(Boolean);
    const home=field?.getRootNode() ?? document;
    const named=ids.map(id=>home.getElementById?.(id)).filter(Boolean);
    const roots=named.length ? named : (cache?.roots() ?? [document]);
    const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
    if (++frames>=2 && (!autocomplete || options.some(e=>{
      const r=e.getBoundingClientRect();
      return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
        e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
    }))) finish();
    else requestAnimationFrame(ready);
  };
  requestAnimationFrame(ready);
}))"""


class Session:
    """One CDP target: observe it, act on it, and never act on a stale reading of it."""
    def __init__(self, config=None, target_id=None, max_elements=MAX_ELEMENTS):
        self.config = config or load()
        self.max_elements = max_elements
        self.after_input = None
        self.cache = {}
        viewport = self.config.viewport
        self.cdp_url, self.chrome_source = ensure_chrome(viewport=(viewport.width, viewport.height))
        ensure_daemon()
        created = target_id is None
        self.target_id = (
            cdp("Target.createTarget", url="about:blank", background=True)["targetId"] if created else target_id
        )
        self.session_id = cdp("Target.attachToTarget", targetId=self.target_id, flatten=True)["sessionId"]
        self.call(
            "Emulation.setDeviceMetricsOverride",
            width=viewport.width,
            height=viewport.height,
            deviceScaleFactor=1,
            mobile=False,
        )
        # Keep rAF and menus rendering in an owned background tab without stealing focus.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.blocked = self.block_resources() if self.config.block_resources else []

    def block_resources(self, urls=BLOCKED_URLS):
        """Stop this target fetching the given URL patterns."""
        self.call("Network.enable")
        self.call("Network.setBlockedURLs", urls=list(urls))
        return list(urls)

    def cache_get(self, key):
        """A cached payload for this key, or None."""
        return self.cache.get(key)

    def cache_put(self, key, value):
        """Cache a payload for this key and return it."""
        self.cache[key] = value
        return value

    def invalidate(self):
        """Drop everything cached for the current page."""
        self.cache.clear()

    def call(self, method, timeout=CALL_TIMEOUT_S, **params):
        """One CDP call on this target's session, with a budget the caller can widen."""
        try:
            return cdp(method, session_id=self.session_id, _response_timeout=timeout, **params)
        except (TimeoutError, OSError) as error:
            raise ChromeError(f"Chrome stopped answering during {method}: {error}") from error
        except RuntimeError as error:
            if any(phrase in str(error).lower() for phrase in MOVED):
                raise StalePage(f"The page moved during {method}. Observe again.") from error
            raise ChromeError(f"Chrome refused {method}: {error}") from error

    def evaluate(self, expression, await_promise=False):
        """Evaluate an expression in the page, refusing a document that moved under it."""
        response = self.call("Runtime.evaluate", timeout=EVALUATE_TIMEOUT_S, expression=expression,
                             returnByValue=True, awaitPromise=await_promise)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def open(self, url):
        """Navigate, wait for the load to finish, and observe."""
        self.after_input = None
        self.invalidate()
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    break
            except StalePage:
                pass
            time.sleep(0.02)
        deadline = time.monotonic() + PAINT_BUDGET_S
        while time.monotonic() < deadline:
            try:
                if self.evaluate(CONTROLS_JS):
                    break
            except StalePage:
                logger.debug("The document changed while waiting for it to paint")
            time.sleep(WAIT_SLEEP_S)
        return self.observe()

    def settle(self):
        """Wait out the effect of the last input before observing again."""
        action, self.after_input = self.after_input, None
        if action is None:
            return
        # Read-only, and only after the action was already recorded: navigation may cut it short.
        try:
            self.call(
                "Runtime.evaluate",
                expression=f"{SETTLE_JS}({json.dumps(action)})",
                awaitPromise=True,
                returnByValue=True,
            )
        except RuntimeError:
            logger.debug("Post-input settle was interrupted")
        self.quiesce()

    def quiesce(self):
        """Wait, briefly, until two readings of the page marker agree."""
        deadline = time.monotonic() + QUIET_BUDGET_S
        expression = marker_expression(self.max_elements)
        try:
            previous = self.evaluate(expression)
        except StalePage:
            return
        while time.monotonic() < deadline:
            time.sleep(QUIET_INTERVAL_S)
            try:
                current = self.evaluate(expression)
            except StalePage:
                continue
            if current == previous:
                return
            previous = current

    def observe(self, timer=None):
        """One atomic reading of the page: text, elements, actions, guards and marker."""
        timer = timer or NullTimer()
        with timer.measure("wait"):
            self.settle()
        with timer.measure("snapshot"):
            for attempt in range(SETTLE_ATTEMPTS):
                try:
                    page = self.evaluate(snapshot_expression(self.max_elements))
                except StalePage:
                    page = None
                if page is not None:
                    return page
                if attempt < SETTLE_ATTEMPTS - 1:
                    time.sleep(WAIT_SLEEP_S if attempt else 0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        """Whether the observed page still describes what is about to be acted on."""
        if action is not None and action.get("kind") in TARGETED:
            node = action["node"]
            current = self.evaluate(guard_expression(node))
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(marker_expression(self.max_elements)) == page["marker"]

    def act(self, action, page, text=None, timer=None):
        """Execute one observed action, re-checking freshness immediately before input."""
        with (timer or NullTimer()).measure("act"):
            return self.execute(action, page, text)

    def execute(self, action, page, text=None):
        """The action itself: guard, then trusted input."""
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        kind = action["kind"]
        if kind == "wait":
            time.sleep(WAIT_SLEEP_S)
        elif kind == "scroll":
            viewport = self.config.viewport
            self.call(
                "Input.dispatchMouseEvent",
                type="mouseWheel",
                x=viewport.width // 2,
                y=viewport.height // 2,
                deltaX=0,
                deltaY=action["delta"],
            )
        else:
            self.input(action, text)
        self.after_input = action if kind != "wait" else None
        self.invalidate()
        return {"executed": action["id"], "kind": kind, "text": text}

    def input(self, action, text):
        """Resolve the target's live geometry, hit-test it, and dispatch trusted input."""
        if type(action.get("node")) is not int:
            raise ValueError("Invalid observed node")
        if action["kind"] == "fill" and not isinstance(text, str):
            raise ValueError("TYPE_TEXT needs a string; none was supplied")
        target = self.evaluate(f"{RESOLVE_JS}({json.dumps(action)})")
        if target is None:
            if action["kind"] == "select":
                raise StalePage("Dropdown execution was not confirmed. Observe again.")
            raise StalePage("Target changed or is covered. Observe again.")
        if action["kind"] == "select":
            return
        for event in ("mousePressed", "mouseReleased"):
            self.call(
                "Input.dispatchMouseEvent",
                type=event,
                x=target["x"],
                y=target["y"],
                button="left",
                clickCount=1,
            )
        if action["kind"] == "fill":
            self.select_all()
            self.call("Input.insertText", text=text)

    def select_all(self):
        """Select the focused field's contents so the next insert replaces them."""
        modifiers = 4 if sys.platform == "darwin" else 2
        self.call(
            "Input.dispatchKeyEvent",
            type="keyDown",
            key="a",
            code="KeyA",
            modifiers=modifiers,
            commands=["selectAll"],
        )
        self.call("Input.dispatchKeyEvent", type="keyUp", key="a", code="KeyA", modifiers=modifiers)

    def press(self, key):
        """Press one of the supported keys."""
        if key not in KEYS:
            raise ValueError(f"press supports {', '.join(KEYS)}")
        code, name, text = KEYS[key]
        for event in ("keyDown", "keyUp"):
            self.call(
                "Input.dispatchKeyEvent",
                type=event,
                key=name,
                code=name,
                windowsVirtualKeyCode=code,
                nativeVirtualKeyCode=code,
                **({"text": text} if text and event == "keyDown" else {}),
            )
        self.after_input = None
        self.invalidate()
        time.sleep(WAIT_SLEEP_S)
        return {"executed": f"press:{key}", "kind": "press"}

    def screenshot(self):
        """The current viewport as JPEG bytes."""
        shot = self.call("Page.captureScreenshot", timeout=EVALUATE_TIMEOUT_S, format="jpeg", quality=72)
        return base64.b64decode(shot["data"])

    def close(self):
        """Close the target this session owns."""
        if self.target_id:
            cdp("Target.closeTarget", targetId=self.target_id)
            self.target_id = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
