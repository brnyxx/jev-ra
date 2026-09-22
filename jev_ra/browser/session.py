"""One CDP target, observed atomically and driven with trusted input only."""

import base64
import json
import logging
import sys
import time
from urllib.parse import urlsplit

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

from ..config import load
from ..errors import BadUrl, ChromeError, StalePage
from ..profile import NullTimer
from . import MAX_ELEMENTS, QUIET_STATE_JS, guard_expression, marker_expression, snapshot_expression
from .chrome import ensure as ensure_chrome
from .chrome import ready as chrome_ready
from .chrome import verify_attached

logger = logging.getLogger(__name__)

LOAD_TIMEOUT_S = 15.0
# Page.navigate answers when the navigation commits, and the first network navigation of a
# freshly launched profile commits only once Chrome has brought up its network stack. Measured on
# macOS against a profile made a second earlier: 19.5 s for a page served from loopback in the
# same second, then 0.2 s for the next one, over the internet. That is a navigation's budget, not
# a call's, and charging it the five second call budget ended a first run with a timeout.
NAVIGATE_TIMEOUT_S = 45.0
# A single-page app reports the document complete long before it paints anything, and a page with
# nothing to act on reads as BLOCKED. Wait until a control in the viewport is reachable, or -
# only when nothing at all is in view - until one waits below it: a listing legitimately opens a
# screenful above its own sort bar, and waiting for that buys nothing. A portal's loading veil
# leaves its header controls in view and unreachable, so it is still waited out.
PAINT_BUDGET_S = 2.0
PAINTED_JS = """(() => {
  const selector='a[href],button,input,select,textarea,summary,[contenteditable=""],'+
    '[contenteditable="true"],[role="button"],[role="link"],[role="tab"],[role="checkbox"],'+
    '[role="radio"],[role="option"],[role="combobox"],[role="textbox"],[role="searchbox"]';
  const deepest=(x,y)=>{
    let node=document.elementFromPoint(x,y);
    while (node?.shadowRoot) {
      const inner=node.shadowRoot.elementFromPoint(x,y);
      if (!inner || inner===node) break;
      node=inner;
    }
    return node;
  };
  let below=false, shown=0;
  for (const e of document.querySelectorAll(selector)) {
    const r=e.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    if (!e.checkVisibility({checkVisibilityCSS:true})) continue;
    if (e.closest('[aria-hidden="true"],[inert]')) continue;
    if (r.bottom<=0 || r.top>=innerHeight || r.right<=0 || r.left>=innerWidth) { below=true; continue; }
    shown++;
    const top=deepest(r.x+r.width/2, r.y+r.height/2);
    if (top && (top===e || e.contains(top) || top.contains(e) || top.closest('label')?.control===e)) return true;
  }
  // Out of view is not covered, but it is also no proof: a covered viewport with a footer link
  // below it still has nothing to act on, and gov.kr serves exactly that while it loads.
  return below && shown===0;
})()"""
# The daemon's own default budget is 5 s, which a plain call never needs and the snapshot of a
# large page routinely exceeds: oliveyoung.co.kr evaluates for longer than that, and the timeout
# arrived as a transport exception from inside browser_harness rather than as anything a caller
# could handle. Give the evaluating calls room, and turn what is left into ChromeError.
CALL_TIMEOUT_S = 5.0
CALL_ATTEMPTS = 2
# Asking again is only safe where asking twice means the same as asking once. Input never is: a
# mousePressed that answered late still pressed, and a second one is a second click; an insertText
# that answered late still typed, and a second one types the query again. Everything here either
# reads, or settles to the same place whichever way it is reached.
IDEMPOTENT = (
    "Runtime.evaluate",
    "Page.navigate",
    "Page.captureScreenshot",
    "Emulation.setDeviceMetricsOverride",
    "Emulation.setFocusEmulationEnabled",
    "Network.enable",
    "Network.setBlockedURLs",
    "DOM.focus",
    "Runtime.releaseObject",
)
EVALUATE_TIMEOUT_S = 30.0
WAIT_SLEEP_S = 0.1
SETTLE_ATTEMPTS = 10
# A page knows when it stopped changing, and asking it ten times a second is both slower and less
# true than letting it say so. One MutationObserver and one frame counter per document: `last` is
# when the DOM last moved and `count` how often it has, so a wait can be for stillness or for the
# next change. Stillness is 120 ms with nothing navigating; the caller's budget is still the
# ceiling, and a document the browser stops painting is answered by the timeout rather than never.
QUIET_MS = 120
# A click whose answer has not reached the action set yet is given a longer stillness before the
# wait gives up on it: a panel that mounts a beat after the click is preceded by the page moving,
# and only a page that has gone properly still has nothing left to say.
UNANSWERED_QUIET_MS = 400
# A page that never stops moving would hold a single probe for the whole budget and leave nothing
# to read it with, so a probe is asked for a little more than the stillness it waits for.
QUIET_SLICE_MS = 80
QUIESCENCE_JS = (
    """(options => new Promise(resolve => {
  const state = """
    + QUIET_STATE_JS
    + """();
  const started = performance.now(), deadline = started + options.budget_ms, first = state.frames;
  let answered = false;
  const answer = quiet => {
    if (answered) return;
    answered = true;
    resolve({quiet, count: state.count, waited: Math.round(performance.now() - started)});
  };
  const tick = () => {
    if (answered) return;
    state.frames++;
    const now = performance.now();
    // A document that has not moved once since it was first read has nothing to settle; one that
    // has gets the stillness its caller asked for, measured from the last time it moved.
    const still = !state.leaving && document.readyState === 'complete' &&
      (state.count === 0 || now - state.last >= options.quiet_ms) &&
      (options.after === null || state.count > options.after);
    // Two frames, so a document that has only just been handed the input has had one to answer in.
    if (still && state.frames - first >= 2) return answer(true);
    if (now >= deadline) return answer(false);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  // A document the browser has stopped painting runs no frames; the ceiling still has to answer.
  setTimeout(() => answer(false), options.budget_ms + 50);
}))"""
)
# The load is the page's own event, not something to ask about twenty times a second. A navigation
# that replaces the document under the wait destroys the context, which is asked again.
READY_JS = """(options => new Promise(resolve => {
  const done = () => resolve(document.readyState);
  if (document.readyState === 'complete') return done();
  addEventListener('load', done, {once: true});
  setTimeout(done, options.budget_ms);
}))"""
# A frame that just committed its first paint can swallow the first click into it: the resolver's
# hit test passes, the input event lands on the parent, and the field never takes focus. Give the
# focus a moment to arrive on its own, then ask for it directly. Clicking again is not an option:
# a search palette and a date picker both close on the second click, so chasing focus that way
# throws away what the first click opened.
FOCUS_SLEEP_S = 0.05
# After input, keep reading the marker until two readings agree. A single-page app re-renders
# well after its two frames are up, and a half-rendered page reads as one with nothing to do.
QUIET_BUDGET_S = 0.6
# One budget for everything a step waits for. A page that has finished settling says so by going
# still, and one that never does costs what it always did rather than being asked more often.
SETTLE_BUDGET_S = 2.0
# What a click that opens a panel brings: a field, a menu item, an option. A link that blinks
# in and out - Back to top, a scroll helper - is the page catching up, not the click's answer,
# and accepting it would end the wait before the panel mounts.
PANEL_ROLES = frozenset(
    {
        "textbox",
        "searchbox",
        "combobox",
        "listbox",
        "option",
        "menuitem",
        "menuitemradio",
        "menu",
        "dialog",
        "spinbutton",
        "tabpanel",
    }
)
# A url is an instruction to the browser, and only some of them mean "fetch a page". `javascript:`
# runs in whatever document is open and never commits a navigation, so Page.navigate waits out its
# whole budget; `file:` reads the disk, and the text it reads goes to the decision endpoint with
# everything else on the page. The web schemes are what a run is for; a local file is opt-in.
WEB_SCHEMES = frozenset({"http", "https"})
BLANK = "about:blank"
OPEN_MIN_CONTROLS = 4
# The marker, as snapshot.js builds it: origin, address, scroll, size, then the page itself.
MARKER_ORIGIN, MARKER_URL, MARKER_CONTROLS = 0, 1, 8
MARKER_CONTENT = slice(6, None)
# Fonts and media cost bytes and answer nothing. Images are deliberately NOT here: blocking
# them on en.wikipedia.org drops the observed controls from 62 to 34, because real layouts
# size themselves around their images and half the page then falls outside the viewport.
# jev-ra search blocks the heavier list in its reading tabs, where only extracted text is used.
BLOCKED_URLS = (
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.otf",
    "*.eot",
    "*.mp4",
    "*.webm",
    "*.mp3",
    "*.m4a",
    "*.avi",
    "*.mov",
)
# An action with a target is guarded by that target: its identity, its state and the text of the
# block it sits in, plus the page key. The whole-page marker carries every word on the page, so a
# departures board or a price ticker would refuse every action on a page that is working fine.
TARGETED = {"click", "select", "fill", "press"}
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
  // The point the snapshot would have offered it at, hit-tested in the element's own root:
  // elementFromPoint stops at a shadow host otherwise.
  const local=cache.point(e);
  if (!local) return null;
  const [dx,dy]=cache.offset(e), x=local.x+dx, y=local.y+dy;
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

# Whether the observed field itself holds focus, wherever it lives: a document, a shadow root or
# a same-origin frame. Typing is only safe once this is true.
FOCUSED_JS = """(node => {
  const e=window.__jevRa?.nodes.get(node);
  return !!e && (e.ownerDocument.activeElement===e || e.getRootNode()?.activeElement===e);
})"""


class Session:
    """One CDP target: observe it, act on it, and never act on a stale reading of it."""

    def __init__(self, config=None, target_id=None, max_elements=MAX_ELEMENTS, profile=None):
        self.config = config or load()
        self.max_elements = max_elements
        self.profile = profile
        self.after_input = None
        self.before_input = None
        self.moved_from = None
        self.cache = {}
        viewport = self.config.viewport
        self.cdp_url, self.chrome_source = ensure_chrome(
            viewport=(viewport.width, viewport.height), profile=profile, locale=self.config.locale
        )
        ensure_daemon()
        verify_attached(self.cdp_url)
        if self.chrome_source == "launched":
            # We started this Chrome a moment ago. A published debugging port is not a browser
            # that will answer yet, so wait until a target evaluates something before using it.
            chrome_ready()
        created = target_id is None
        self.target_id = (
            cdp("Target.createTarget", url="about:blank", background=True)["targetId"] if created else target_id
        )
        try:
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
            self.speak(self.config.locale)
            self.blocked = self.block_resources() if self.config.block_resources else []
        except Exception:
            # Nobody else has the id of a target whose setup failed, so this is the only chance to
            # close it. A target we were only handed stays open: its owner decides when it goes.
            if created:
                try:
                    cdp("Target.closeTarget", targetId=self.target_id)
                except Exception:
                    logger.warning("Could not close target %s after its setup failed", self.target_id)
            raise

    def speak(self, locale):
        """Ask this target for one language, so an attached Chrome serves what a launched one does.

        Two things say which language a page comes back in, and the launch flags only set them on
        a Chrome jev-ra started itself. `Emulation.setLocaleOverride` moves this target's own
        locale; the site's copy is chosen from `Accept-Language`, which the override leaves alone -
        measured against a loopback echo, an overridden target still asked for the machine's
        language. A browser that refuses either is still a browser that serves pages, so the
        refusal is reported and the run goes on.
        """
        if not locale:
            return False
        spoken = True
        for method, params in (
            ("Emulation.setLocaleOverride", {"locale": locale}),
            ("Network.enable", {}),
            ("Network.setExtraHTTPHeaders", {"headers": {"Accept-Language": locale}}),
        ):
            try:
                self.call(method, **params)
            except (ChromeError, StalePage) as error:
                logger.warning("The browser would not answer %s for %s: %s", method, locale, error)
                spoken = False
        return spoken

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
        attempts = CALL_ATTEMPTS if method in IDEMPOTENT else 1
        for attempt in range(attempts):
            try:
                return cdp(method, session_id=self.session_id, _response_timeout=timeout, **params)
            except (TimeoutError, OSError) as error:
                # A browser with thirty tabs open answers late now and then. One slow answer is
                # not a browser that has gone away, and ending the run over it loses the work.
                if attempt == attempts - 1:
                    raise ChromeError(f"Chrome stopped answering during {method}: {error}") from error
                logger.info("Chrome was slow to answer %s; asking once more", method)
            except RuntimeError as error:
                if any(phrase in str(error).lower() for phrase in MOVED):
                    raise StalePage(f"The page moved during {method}. Observe again.") from error
                raise ChromeError(f"Chrome refused {method}: {error}") from error
        raise ChromeError(f"Chrome stopped answering during {method}")

    def evaluate(self, expression, await_promise=False):
        """Evaluate an expression in the page, refusing a document that moved under it."""
        response = self.call(
            "Runtime.evaluate",
            timeout=EVALUATE_TIMEOUT_S,
            expression=expression,
            returnByValue=True,
            awaitPromise=await_promise,
        )
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def open(self, url):
        """Navigate, wait for the load to finish, and observe."""
        url = check_url(url, self.config)
        self.after_input = None
        self.invalidate()
        self.call("Page.navigate", timeout=NAVIGATE_TIMEOUT_S, url=url)
        self.load()
        self.paint()
        return self.observe()

    def quiet(self, budget_s, after=None, quiet_ms=QUIET_MS):
        """Wait in the page until it stops changing, and say whether it did.

        `{"quiet": ..., "count": ...}`: whether the document went still inside the budget rather
        than running out of it, and how many times it has mutated, which a caller waiting for
        something that has not happened yet passes back as `after`. None when the document moved
        under the probe, which is the answer to observe again.
        """
        options = {"quiet_ms": quiet_ms, "budget_ms": max(0, round(budget_s * 1000)), "after": after}
        try:
            return self.evaluate(f"{QUIESCENCE_JS}({json.dumps(options)})", await_promise=True)
        except StalePage:
            logger.debug("The document changed while waiting for it to go quiet")
            return None

    def load(self, budget=LOAD_TIMEOUT_S):
        """Wait for the document's own load event, or for the load budget to run out."""
        deadline = time.monotonic() + budget
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            expression = f"{READY_JS}({json.dumps({'budget_ms': round(remaining * 1000)})})"
            try:
                if self.evaluate(expression, await_promise=True) == "complete":
                    return True
            except StalePage:
                logger.debug("The document was replaced while waiting for it to load")

    def paint(self, budget=PAINT_BUDGET_S):
        """Wait until there is something on the page to act on, or the budget runs out.

        A document that reports itself complete can still be a loading screen: a portal paints a
        cover over every control it has drawn, and a snapshot of it observes nothing, which reads
        as a page with nothing to act on. Nothing new arrives while the DOM is still, so what is
        waited for between readings is the page's own next mutation rather than a fixed sleep.
        """
        deadline = time.monotonic() + budget
        seen = None
        while True:
            try:
                if self.evaluate(PAINTED_JS):
                    return True
            except StalePage:
                logger.debug("The document changed while waiting for it to paint")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            answer = self.quiet(remaining, after=seen)
            if answer is None:
                continue
            if not answer["quiet"]:
                return False
            seen = answer["count"]

    def settle(self):
        """Wait out the effect of the last input before observing again."""
        action, self.after_input = self.after_input, None
        was, self.moved_from = self.moved_from, None
        before, self.before_input = self.before_input, None
        if action is None:
            return
        # Read-only, and only after the action was already recorded: navigation may cut it short.
        # It awaits a promise the page resolves, so it is an evaluating call and gets an
        # evaluating call's budget; a page that takes even longer than that is still only a page
        # this run waited for, so the timeout is logged and the step goes on to read the marker.
        try:
            self.call(
                "Runtime.evaluate",
                timeout=EVALUATE_TIMEOUT_S,
                expression=f"{SETTLE_JS}({json.dumps(action)})",
                awaitPromise=True,
                returnByValue=True,
            )
        except (ChromeError, RuntimeError) as error:
            logger.debug("Post-input settle was interrupted: %s", error)
        self.wait_out(action, was, before)

    def wait_out(self, action, was, before):
        """One budget and one reading per turn for everything a step waits for.

        Three waits used to run here one after another, each on its own clock and its own
        deadline: the route an address had already moved to, whatever the click opened, and the
        page going quiet. They are three questions about successive readings of the same marker,
        so read it, answer all three, and then wait for the page itself to say it has changed or
        stopped changing rather than asking again on a timer. Two identical readings of a page
        that is not moving end the wait, whatever the input was; a page that never stops moving
        costs the budget it always did.
        """
        opens = bool(before) and action.get("kind") == "click" and action.get("role") == "button"
        deadline = time.monotonic() + SETTLE_BUDGET_S
        expression = marker_expression(self.max_elements)
        previous, opened, differed = None, not opens, False
        ready, still, count = None, False, None
        while True:
            try:
                marker = self.evaluate(expression)
            except StalePage:
                return
            if not marker:
                return
            if not opened:
                controls = control_set(marker[MARKER_CONTROLS])
                fresh = controls - before[1]
                # A control that changes its own state is the page answering the click, even when
                # nothing new appears next to it; a link that blinks in has no earlier self.
                refs = {control[0] for control in before[1]}
                differs = (
                    marker[MARKER_URL] != before[0]
                    or any(control[0] in refs for control in fresh)
                    or len(controls ^ before[1]) >= OPEN_MIN_CONTROLS
                    or any(control[1] in PANEL_ROLES for control in fresh)
                )
                opened, differed = differs and differed, differs
            caught_up = routed(marker, was)
            if marker == previous and caught_up and (opened or still):
                return
            if opened and caught_up:
                if ready is None:
                    ready = time.monotonic()
                elif time.monotonic() - ready >= QUIET_BUDGET_S:
                    return
            # Two identical readings of a page that is not moving: only its next change can answer
            # what this wait is still asking, so that is what the next turn waits for.
            after = count if still and marker == previous else None
            previous = marker
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            # A click whose answer has already shown up in a reading only has to stop moving; one
            # that has shown nothing yet is given longer, because a panel that mounts a beat later
            # is preceded by the page moving and only a page gone properly still has nothing more.
            stillness = QUIET_MS if opened or differed else UNANSWERED_QUIET_MS
            # Waiting for a change that has not happened yet has nothing else to interrupt it, so
            # it may have the rest of the budget; waiting for stillness leaves room to read again.
            budget = remaining if after is not None else min(remaining, (stillness + QUIET_SLICE_MS) / 1000)
            answer = self.quiet(budget, after=after, quiet_ms=stillness)
            still = answer is not None and answer["quiet"]
            count = answer["count"] if answer is not None else None

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
        if action is not None and action.get("kind") in {"scroll", "wait"}:
            # These touch no element, so the words on the page cannot invalidate them - and a
            # page still loading is exactly when a wait is wanted. The document is the freshness
            # a scroll or a wait needs.
            return self.evaluate("location.href") == page.get("url")
        return self.evaluate(marker_expression(self.max_elements)) == page["marker"]

    def act(self, action, page, text=None, timer=None):
        """Execute one observed action, re-checking freshness immediately before input."""
        with (timer or NullTimer()).measure("act"):
            return self.execute(action, page, text)

    def execute(self, action, page, text=None):
        """The action itself: guard, then trusted input."""
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        self.before_input = (page.get("url", ""), control_set(page.get("elements")))
        kind = action["kind"]
        if kind == "wait":
            time.sleep(WAIT_SLEEP_S)
        elif kind == "press":
            self.submit(action)
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
        self.moved_from = page.get("marker") if kind != "wait" else None
        self.invalidate()
        return {"executed": action["id"], "kind": kind, "text": text}

    def hover(self, node):
        """Move the pointer onto one observed node, without pressing anything."""
        if type(node) is not int:
            raise ValueError("Invalid observed node")
        target = self.evaluate(f"{RESOLVE_JS}({json.dumps({'node': node, 'kind': 'click'})})")
        if target is None:
            raise StalePage("Target changed or is covered. Observe again.")
        self.call("Input.dispatchMouseEvent", type="mouseMoved", x=target["x"], y=target["y"])
        self.after_input = {"id": f"hover-{node}", "kind": "hover", "node": node}
        self.invalidate()
        return {"executed": f"hover-{node}", "kind": "hover"}

    def input(self, action, text):
        """Resolve the target's live geometry, hit-test it, and dispatch trusted input."""
        if type(action.get("node")) is not int:
            raise ValueError("Invalid observed node")
        if action["kind"] == "fill" and not isinstance(text, str):
            raise ValueError("TYPE_TEXT needs a string; none was supplied")
        if action["kind"] == "select":
            if self.evaluate(f"{RESOLVE_JS}({json.dumps(action)})") is None:
                raise StalePage("Dropdown execution was not confirmed. Observe again.")
            return
        self.click(self.resolve(action))
        if action["kind"] == "fill" and not self.focused(action["node"]):
            time.sleep(FOCUS_SLEEP_S)
            if not self.focused(action["node"]) and not self.focus(action["node"]):
                raise StalePage("The field never took focus. Observe again.")
        if action["kind"] == "fill":
            self.select_all()
            self.call("Input.insertText", text=text)

    def resolve(self, action):
        """The target's live top-level coordinates, or a stale page when it moved or is covered."""
        target = self.evaluate(f"{RESOLVE_JS}({json.dumps(action)})")
        if target is None:
            raise StalePage("Target changed or is covered. Observe again.")
        return target

    def click(self, target):
        """A pointer move and two trusted mouse events at the resolved point."""
        # A pointer arrives before it presses. Menus that open on hover and nothing else - a
        # shop's category bar, a docs site's version picker - never open for a click alone, and
        # the pointer stays where it was put, so the next observation sees what opened.
        self.call("Input.dispatchMouseEvent", type="mouseMoved", x=target["x"], y=target["y"])
        for event in ("mousePressed", "mouseReleased"):
            self.call(
                "Input.dispatchMouseEvent",
                type=event,
                x=target["x"],
                y=target["y"],
                button="left",
                clickCount=1,
            )

    def focused(self, node):
        """Whether the observed field itself holds focus."""
        return bool(self.evaluate(f"({FOCUSED_JS})({observed(node)})"))

    def focus(self, node):
        """Ask the browser to focus one observed node, and say whether it now holds focus."""
        node = observed(node)
        handle = self.call(
            "Runtime.evaluate",
            timeout=EVALUATE_TIMEOUT_S,
            expression=f"window.__jevRa?.nodes.get({observed(node)})",
            returnByValue=False,
        )
        object_id = (handle.get("result") or {}).get("objectId")
        if not object_id:
            return False
        try:
            self.call("DOM.focus", objectId=object_id)
        except ChromeError:
            logger.info("The browser would not focus the observed field")
            return False
        finally:
            self.call("Runtime.releaseObject", objectId=object_id)
        return self.focused(node)

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

    def submit(self, action):
        """Send the key to the field that was observed, or to nothing at all.

        A key lands on whatever holds focus when it is pressed. Between the reading that offered
        this and the press, a page can move focus to another field that also holds a value, and
        the guard sees no difference: same controls, same text, same values. Ask the one question
        that separates them right before the key goes out.
        """
        node = action.get("node")
        if node is not None and not self.focused(node):
            raise StalePage("The field lost focus before it could be submitted. Observe again.")
        self.press(action.get("key", "Enter"))

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


def check_url(url, config):
    """The url a session may navigate to, or a refusal naming the scheme it would not open."""
    text = (url or "").strip()
    scheme = urlsplit(text).scheme.lower()
    if scheme in WEB_SCHEMES or text.lower() == BLANK:
        return text
    if scheme == "file":
        if config.allow_file_urls:
            return text
        raise BadUrl(
            "jev-ra does not open file: URLs, and the file's text would go to the decision endpoint.",
            next_step="Set JEV_RA_ALLOW_FILE_URLS=1 if you meant to read a local file.",
        )
    if scheme:
        raise BadUrl(f"jev-ra does not open {scheme}: URLs.")
    raise BadUrl(f"{text!r} names no scheme.")


def observed(node):
    """One observed node id, or a refusal. Nothing else is ever written into an expression."""
    if type(node) is not int:
        raise ValueError("Only an observed node id is ever put into an expression")
    return node


# What a click can change about a control without adding or removing one: a menu button flips
# aria-expanded, a filter flips checked, a tab flips selected, a panel relabels what is already
# there. None of that reaches the action list, which carries only an id and a kind, so the state
# has to be read from the element view the snapshot builds beside it.
CONTROL_KEYS = ("ref", "role", "label", "value", "checked", "selected", "expanded", "current")


def control_set(elements):
    """The identity and state of every control a page offers, for comparing two readings of it."""
    return frozenset(tuple(element.get(key) for key in CONTROL_KEYS) for element in elements or ())


def routed(marker, was):
    """Whether the page has caught up with an address a single-page app already moved it to."""
    return (
        not was
        or marker[MARKER_ORIGIN] != was[MARKER_ORIGIN]
        or marker[MARKER_URL] == was[MARKER_URL]
        or marker[MARKER_CONTENT] != was[MARKER_CONTENT]
    )
