"""One CDP target, observed atomically and driven with trusted input only."""

import base64
import json
import logging
import sys
import time

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

from ..config import load
from . import MAX_ELEMENTS, guard_expression, marker_expression, snapshot_expression

logger = logging.getLogger(__name__)

LOAD_TIMEOUT_S = 15.0
WAIT_SLEEP_S = 0.1
SETTLE_ATTEMPTS = 10
KEYS = {
    "Enter": (13, "Enter", "\r"),
    "Escape": (27, "Escape", ""),
    "Tab": (9, "Tab", ""),
}

# Code-owned node ids refer to observed elements. A decision never supplies a selector.
RESOLVE_JS = """(action => {
  const e=window.__jevRa?.nodes.get(action.node);
  if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
      !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
  if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
  const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
  if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
  if (!e.contains(document.elementFromPoint(x,y))) return null;
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
  const field=window.__jevRa?.nodes.get(action.node);
  const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
  let frames=0, stopped=false;
  const finish=()=>{stopped=true;resolve()};
  setTimeout(finish, autocomplete ? 200 : 50);
  const ready=()=>{
    if (stopped) return;
    const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
      .split(/\\s+/).filter(Boolean);
    const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
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


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class Session:
    def __init__(self, config=None, target_id=None, max_elements=MAX_ELEMENTS):
        self.config = config or load()
        self.max_elements = max_elements
        self.after_input = None
        ensure_daemon()
        created = target_id is None
        self.target_id = (
            cdp("Target.createTarget", url="about:blank", background=True)["targetId"] if created else target_id
        )
        self.session_id = cdp("Target.attachToTarget", targetId=self.target_id, flatten=True)["sessionId"]
        viewport = self.config.viewport
        self.call(
            "Emulation.setDeviceMetricsOverride",
            width=viewport.width,
            height=viewport.height,
            deviceScaleFactor=1,
            mobile=False,
        )
        # Keep rAF and menus rendering in an owned background tab without stealing focus.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)

    def call(self, method, **params):
        return cdp(method, session_id=self.session_id, **params)

    def evaluate(self, expression, await_promise=False):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def open(self, url):
        self.after_input = None
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + LOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    break
            except StalePage:
                pass
            time.sleep(0.02)
        return self.observe()

    def settle(self):
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

    def observe(self):
        self.settle()
        for attempt in range(SETTLE_ATTEMPTS):
            page = self.evaluate(snapshot_expression(self.max_elements))
            if page is not None:
                return page
            if attempt < SETTLE_ATTEMPTS - 1:
                time.sleep(0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        if action is not None and action.get("kind") in {"click", "select"}:
            node = action["node"]
            current = self.evaluate(guard_expression(node))
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(marker_expression(self.max_elements)) == page["marker"]

    def act(self, action, page, text=None):
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
        return {"executed": action["id"], "kind": kind, "text": text}

    def input(self, action, text):
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
        time.sleep(WAIT_SLEEP_S)
        return {"executed": f"press:{key}", "kind": "press"}

    def screenshot(self):
        return base64.b64decode(self.call("Page.captureScreenshot", format="jpeg", quality=72)["data"])

    def close(self):
        if self.target_id:
            cdp("Target.closeTarget", targetId=self.target_id)
            self.target_id = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
