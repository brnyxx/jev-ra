"""One CDP target, observed atomically and driven with trusted input only."""

import base64
import json
import logging
import sys
import threading
import time
from collections import deque
from concurrent.futures import Future, wait
from urllib.parse import urlsplit

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp, drain_events

from ..config import load
from ..errors import BadUrl, BadValue, ChromeError, DialogOpen, StalePage
from ..profile import NullTimer
from . import CHALLENGE_JS, MAX_ELEMENTS, QUIET_STATE_JS, guard_expression, marker_expression, snapshot_expression
from .chrome import ensure as ensure_chrome
from .chrome import ready as chrome_ready
from .chrome import verify_attached
from .present import Presenter

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
# leaves its header controls in view and unreachable, so it is still waited out. A check on screen
# is everything the page will show until a person answers it, and its controls live in frames the
# page cannot reach, so there is nothing more to wait for.
PAINT_BUDGET_S = 2.0
PAINTED_JS = (
    """(() => {
  if (("""
    + CHALLENGE_JS
    + """)()) return true;
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
)
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
# A JavaScript dialog holds the page's script until someone answers it, and every call the page
# itself has to answer waits for as long as it stays open: a click on a button that asks
# confirm() used to wait out the whole call budget and end the run as a browser that stopped
# answering. A call still waiting after this long is asked whether a dialog is what holds it.
DIALOG_CHECK_S = 0.05
# What the page itself answers. The browser answers everything else while a dialog is up, which
# is how the dialog gets answered at all.
RENDERER = ("Runtime.", "Input.", "DOM.", "Page.captureScreenshot")
# What else a dialog can hold: a navigation waits for the page it leaves to agree to be left.
HELD = (*RENDERER, "Page.navigate", "Page.reload")
# How many events one session keeps between two readings of them. The daemon keeps 500 for the
# whole browser; a session reads its own at least once a call that waits.
EVENTS_KEPT = 1000
# What each kind of dialog is answered with, in the order Chrome draws its buttons. A before-unload
# dialog says Chrome's own sentence; the page's words are never shown for it.
DIALOG_ANSWERS = {
    "alert": (("accept", "OK"),),
    "confirm": (("accept", "OK"), ("dismiss", "Cancel")),
    "prompt": (("accept", "OK"), ("dismiss", "Cancel")),
    "beforeunload": (("accept", "Leave"), ("dismiss", "Cancel")),
}
LEAVE_TEXT = "Leave site?\nChanges you made may not be saved."
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
      (options.after === null || state.count > options.after ||
        (options.origin !== undefined && performance.timeOrigin !== options.origin));
    // Two ticks, so a document that has only just been handed the input has had one to answer in.
    if (still && state.frames - first >= 2) return answer(true);
    if (now >= deadline) return answer(false);
    schedule();
  };
  // A page that is not being painted runs no animation frames: Chrome on Linux gives a background
  // target none at all, measured on the CI runner as every settle costing its whole budget. So the
  // tick runs on a timer, at frame pace, and a frame that does arrive only makes it come sooner.
  let pending = null;
  const schedule = () => {
    if (pending !== null) return;
    pending = setTimeout(() => { pending = null; tick(); }, 16);
    requestAnimationFrame(() => { if (pending !== null) { clearTimeout(pending); pending = null; tick(); } });
  };
  schedule();
  // The ceiling still has to answer even if no tick ever ran.
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
# A document is parsed long before it has loaded: the load event waits for every image on the page,
# and the words and controls a decision reads are there before most of them arrive.
PARSED_JS = """(options => new Promise(resolve => {
  const done = () => resolve(document.readyState);
  if (document.readyState !== 'loading') return done();
  document.addEventListener('DOMContentLoaded', done, {once: true});
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
# A link can ask a single-page app for a route the page answers after the click. Give that
# address one chance to arrive before the controls and text are read as the click's answer.
ROUTE_BUDGET_S = 0.8
# One budget for everything a step waits for. A page that has finished settling says so by going
# still, and one that never does costs what it always did rather than being asked more often.
SETTLE_BUDGET_S = 2.0
# A step that loaded another document is read once that document has arrived: words showing in the
# viewport or, where the viewport has no words, a control in reach. Two identical readings end a
# step's wait, and an empty shell, a lone spinner or a screen of words still at opacity 0 reads the
# same every time until it paints. Measured on the public benchmark: qatarairways.com's help page
# was still loading and blank when the step read it at 1.4 s; traderjoes.com's store search was a
# spinner at 0.3 s and painted at 0.4 s; espn.com laid its standings out at opacity 0 behind a
# painted logo at 0.7 s and showed them at 1.9 s. Each of those runs ended BLOCKED or scrolled past
# the answer. Words are enough on their own: a form's receipt or an API's JSON has nothing to press
# and is finished, and a page still streaming its markup is readable once it shows some, which
# reuters.com's section pages do seconds before they finish loading. Words below the fold are not
# waited for; a page that has not arrived by the budget is read as it stands. open() keeps its own
# wait for a first control, which a run's first page needs and pays for once.
ARRIVAL_BUDGET_S = 5.0
ARRIVAL_POLL_MS = 50
ARRIVED_JS = (
    """(options => new Promise(resolve => {
  const painted = () => """
    + PAINTED_JS
    + """;
  const words = () => {
    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let veiled = false;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (!parent || !node.textContent.trim() || parent.closest('script,style,noscript,template')) continue;
      range.selectNodeContents(node);
      const r = range.getBoundingClientRect();
      if (!r.width || !r.height || r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth)
        continue;
      if (parent.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return 'shown';
      veiled = true;
    }
    return veiled ? 'veiled' : 'none';
  };
  const started = performance.now();
  const check = () => {
    const waited = Math.round(performance.now() - started);
    const said = words();
    if (said === 'shown' || (said === 'none' && painted())) return resolve({arrived: true, waited});
    if (waited >= options.budget_ms) return resolve({arrived: false, waited});
    setTimeout(check, options.poll_ms);
  };
  check();
}))"""
)
ROUTE_WAIT_JS = """(options => new Promise(resolve => {
  const started = performance.now();
  const check = () => {
    if (location.href !== options.url) return resolve(true);
    if (performance.now() - started >= options.budget_ms) return resolve(false);
    setTimeout(check, 16);
  };
  check();
}))"""
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
# A route is answered by its title, rendered text or elements, not by links whose hrefs changed
# with the address or by page-key bookkeeping that can move before the view has rendered.
MARKER_CONTENT = slice(6, 9)
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
# What the daemon says about a session whose target has gone. For a window this session followed
# that is the window closing, which is how a sign-in pop-up ends; for the only page it has, it is
# the browser losing the page, and that stays a Chrome error.
CLOSED = "session with given id not found"
KEYS = {
    "Enter": (13, "Enter", "\r"),
    "Escape": (27, "Escape", ""),
    "Tab": (9, "Tab", ""),
}

# The element a keystroke lands on: the focused element, followed into open shadow roots and
# same-origin frames.
ACTIVE_JS = """(() => {
  let active=document.activeElement;
  for (;;) {
    let inner=active?.shadowRoot?.activeElement ?? null;
    if (!inner && active?.tagName==='IFRAME') { try { inner=active.contentDocument?.activeElement; } catch {} }
    if (!inner || inner===active) return active;
    active=inner;
  }
})"""

# Code-owned node ids refer to observed elements. A decision never supplies a selector.
RESOLVE_JS = (
    """(action => {
  const cache=window.__jevRa;
  const e=cache?.nodes.get(action.node);
  // Laid out and kept by the accessibility tree; transparency is settled by the hit test below,
  // which is the same rule the snapshot used when it offered this target.
  if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
      !e.checkVisibility({checkVisibilityCSS:true})) return null;
  if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
  // A link that asks for a new tab would open one this run is not driving, and the page it was
  // clicked on reads exactly as it did before - three of those in a row is a run that stopped on
  // a link it chose correctly the first time. gov.cn opens its whole navigation this way. The
  // run has one tab, so the link is followed in it. _self already means this one.
  if (action.kind==='click' && e.tagName==='A' && e.target && e.target!=='_self') e.removeAttribute('target');
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
  // Where focus stands before a field is pressed, so a press that moves it can be told apart
  // from one that was dropped and left it where it was.
  if (action.kind==='fill') cache.focusBefore=("""
    + ACTIVE_JS
    + """)();
  return {x,y};
})"""
)

# Two frames settle ordinary input; a combobox gets up to 200 ms for real suggestions. What the
# promise resolves with is the page itself: the wait after an input and the first reading of what
# the input did are the same round trip, so the observation rides the action back.
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

# A field the browser draws itself takes its value the way its own picker gives it one: set on the
# element, then announced with the input and change events a picker fires. The setter is the
# element's own prototype's, because a framework that tracks a controlled input's value hears a
# plain assignment as no change at all. Whether the browser would keep the value is asked first,
# of a detached input of the same kind and scale, so a refused value never touches the page: a
# date the browser cannot read becomes empty, a colour black, and a slider rounds and clamps.
SET_JS = """(args => {
  const cache=window.__jevRa, e=cache?.nodes.get(args.node);
  if (!e?.isConnected || e.disabled || e.readOnly || !e.checkVisibility({checkVisibilityCSS:true}) ||
      !cache.point(e)) return null;
  const text=args.text.trim(), probe=e.ownerDocument.createElement('input');
  probe.type=e.type;
  for (const key of ['min', 'max', 'step'])
    if (e.getAttribute(key) !== null) probe.setAttribute(key, e.getAttribute(key));
  probe.value=text;
  const took = e.type==='color' ? probe.value===text.toLowerCase() :
    e.type==='range' ? text!=='' && Number(probe.value)===Number(text) : probe.value!=='' || text==='';
  if (!took) return {took, min: e.min || '0', max: e.max || '100', step: e.step || '1'};
  e.focus();
  Object.getOwnPropertyDescriptor(e.ownerDocument.defaultView.HTMLInputElement.prototype, 'value').set.call(e, text);
  e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
  return {took};
})"""
# What a field the browser draws itself takes, said the way a caller has to supply it.
FORMATS = {
    "date": "a date as yyyy-mm-dd, like 2026-10-05",
    "time": "a time as HH:MM on a 24-hour clock, like 19:30",
    "datetime-local": "a date and time as yyyy-mm-ddTHH:MM, like 2026-10-05T19:30",
    "month": "a month as yyyy-mm, like 2026-10",
    "week": "a week as yyyy-Www, like 2026-W41",
    "color": "a colour as #rrggbb, like #ff6600",
}

# Whether the observed field itself holds focus, wherever it lives: a document, a shadow root or
# a same-origin frame. Typing is only safe once this is true. A frame keeps its own focused
# element after the page around it has moved focus elsewhere, so what counts is where a key
# would land now, followed from the top.
FOCUSED_JS = (
    """(node => {
  const e=window.__jevRa?.nodes.get(node);
  return !!e && ("""
    + ACTIVE_JS
    + """)()===e;
})"""
)
# Whether pressing the observed field moved focus onto another text field, which is where a
# person's keystrokes now go. A flight search's origin opens a dialog over the form with an input
# of its own and focuses it; forcing focus back onto the covered field types the value where
# nothing reads it. Focus that did not move - a dropped click, a field that kept it - is not this.
HANDED_JS = (
    """(node => {
  const cache=window.__jevRa, e=cache?.nodes.get(node), active=("""
    + ACTIVE_JS
    + """)();
  if (!e || !active || active===e || active===cache.focusBefore || active.readOnly || active.disabled) return false;
  if (active.isContentEditable || active.tagName==='TEXTAREA') return true;
  return active.tagName==='INPUT' && !['checkbox','radio','button','submit','reset','image','file','hidden',
    'password','range','color'].includes(active.type);
})"""
)


class Inbox:
    """The daemon's one queue of CDP events, read on behalf of every session in this process.

    Reading the queue empties it of every event there is, whoever it belongs to, so a session that
    read it for itself threw away what the others were waiting for: a search reads its result pages
    in parallel tabs, and each tab learns what its own page did only from events. Every session here
    is handed what was addressed to it - or, for what the browser says about a session rather than
    through it, such as its target going away, what names it - and the rest is dropped.
    """

    def __init__(self, kept=EVENTS_KEPT):
        self.lock = threading.Lock()
        self.kept = kept
        self.boxes = {}

    def open(self, session_id):
        """Start keeping the events addressed to one session."""
        with self.lock:
            self.boxes.setdefault(session_id, deque(maxlen=self.kept))

    def close(self, session_id):
        """Stop keeping a session's events."""
        with self.lock:
            self.boxes.pop(session_id, None)

    def take(self, session_id):
        """Every event addressed to this session since it last asked, oldest first."""
        with self.lock:
            for event in drain_events():
                about = event.get("session_id") or (event.get("params") or {}).get("sessionId")
                box = self.boxes.get(about)
                if box is not None:
                    box.append(event)
            box = self.boxes.get(session_id)
            if box is None:
                return []
            taken = list(box)
            box.clear()
            return taken


INBOX = Inbox()


class Session:
    """One CDP target: observe it, act on it, and never act on a stale reading of it."""

    # Handed each reading a wait takes that could turn out to be the one observed, for a caller
    # that can start work before the page has proven it will stay that way. The observation that
    # follows is still the settled reading, taken exactly as it always was. A caller sets it for
    # the duration of one open or observation; a session nobody listens to never calls anything.
    preview = None
    # The JavaScript dialog holding the page, as Chrome announced it, or None. While one is open it
    # is the page: observing shows its message and its answers, and answering it is an action.
    dialog = None
    dialogs = 0
    title = ""
    # The windows the page had already opened before the last input, which it did not just open.
    windows_before = None
    # Whether Chrome said the target under this session went away: a window that closed itself.
    detached = False
    # The file chooser the last input opened, as Chrome announced it, or None. The chooser itself
    # was cancelled; what it asked for is the page's question to whoever holds the file.
    chooser = None

    def __init__(self, config=None, target_id=None, max_elements=MAX_ELEMENTS, profile=None):
        self.config = config or load()
        self.max_elements = max_elements
        self.profile = profile
        self.after_input = None
        self.before_input = None
        self.moved_from = None
        self.settled = None
        self.cache = {}
        self.http_status = None
        self.frame_id = None
        # The pages this session left for a window one of them opened, newest last, to return to
        # when that window closes.
        self.openers = []
        viewport = self.config.viewport
        self.cdp_url, self.chrome_source = ensure_chrome(
            viewport=(viewport.width, viewport.height),
            profile=profile,
            locale=self.config.locale,
            proxy=self.config.proxy,
        )
        ensure_daemon()
        verify_attached(self.cdp_url)
        self.presenter = Presenter(self, notify=self.config.notify)
        if self.chrome_source == "launched":
            # We started this Chrome a moment ago. A published debugging port is not a browser
            # that will answer yet, so wait until a target evaluates something before using it.
            chrome_ready()
        created = target_id is None
        self.target_id = (
            cdp("Target.createTarget", url="about:blank", background=True)["targetId"] if created else target_id
        )
        try:
            self.attach(self.target_id)
        except Exception:
            # Nobody else has the id of a target whose setup failed, so this is the only chance to
            # close it. A target we were only handed stays open: its owner decides when it goes.
            if created:
                try:
                    cdp("Target.closeTarget", targetId=self.target_id)
                except Exception:
                    logger.warning("Could not close target %s after its setup failed", self.target_id)
            raise

    def attach(self, target_id):
        """Attach to one target and set it up the way every page this session drives is set up."""
        self.session_id = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
        self.detached = False
        INBOX.open(self.session_id)
        try:
            # Chrome tells only the sessions that listen to the page domain that a dialog opened,
            # and only they can answer it.
            self.call("Page.enable")
            # A file chooser is a window of the operating system, which nothing here drives and a
            # headless browser cannot even show. It is cancelled the way a person dismissing it
            # would, and the page's question comes back as an event instead.
            self.call("Page.setInterceptFileChooserDialog", enabled=True, cancel=True)
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
            self.speak(self.config.locale)
            self.blocked = self.block_resources() if self.config.block_resources else []
        except Exception:
            INBOX.close(self.session_id)
            raise

    def windows(self):
        """The pages the target this session is on has opened."""
        return {
            info["targetId"]
            for info in cdp("Target.getTargets")["targetInfos"]
            if info.get("type") == "page" and info.get("openerId") == self.target_id
        }

    def follow(self, target_id):
        """Go where a person's attention goes when a page opens a window: into it.

        A sign-in or payment provider answers in a window of its own and tells the page that opened
        it when it is done; the page it came from reads exactly as before until then. The page this
        session was on is kept, to return to once the window closes.
        """
        logger.info("The page opened a window; following it")
        self.openers.append((self.target_id, self.session_id, self.frame_id, self.http_status, self.title))
        self.target_id, self.frame_id, self.http_status, self.dialog = target_id, None, None, None
        self.invalidate()
        self.attach(target_id)
        self.load()
        self.paint()

    def returned(self):
        """Whether the window this session followed has closed, which puts it back on its opener."""
        if not self.openers:
            return False
        try:
            cdp("Target.getTargetInfo", targetId=self.target_id)
            return False
        except RuntimeError:
            logger.info("The window closed; back on the page that opened it")
        INBOX.close(self.session_id)
        self.target_id, self.session_id, self.frame_id, self.http_status, self.title = self.openers.pop()
        self.dialog, self.detached = None, False
        self.after_input = self.moved_from = self.before_input = None
        self.invalidate()
        self.events()
        return True

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
        self.settled = None
        self.cache.clear()

    def call(self, method, timeout=CALL_TIMEOUT_S, leave=False, **params):
        """One CDP call on this target's session, with a budget the caller can widen.

        A call the page has to answer is never sent while a dialog holds the page, and one that a
        dialog starts holding, or whose target closes, while it waits is given up on: see
        `answered`. `leave` lets a
        navigation the caller asked for leave a page that asks whether it may be left.
        """
        if self.dialog is not None and method.startswith(RENDERER):
            raise DialogOpen(f"A {self.dialog['type']} dialog holds the page, so {method} was not sent.")
        attempts = CALL_ATTEMPTS if method in IDEMPOTENT else 1
        for attempt in range(attempts):
            try:
                if not method.startswith(HELD):
                    return cdp(method, session_id=self.session_id, _response_timeout=timeout, **params)
                return self.answered(method, timeout, leave, params)
            except (TimeoutError, OSError) as error:
                # A browser with thirty tabs open answers late now and then. One slow answer is
                # not a browser that has gone away, and ending the run over it loses the work.
                if attempt == attempts - 1:
                    raise ChromeError(f"Chrome stopped answering during {method}: {error}") from error
                logger.info("Chrome was slow to answer %s; asking once more", method)
            except RuntimeError as error:
                said = str(error).lower()
                if any(phrase in said for phrase in MOVED):
                    raise StalePage(f"The page moved during {method}. Observe again.") from error
                if self.openers and CLOSED in said:
                    raise StalePage(f"The window closed during {method}. Observe again.") from error
                raise ChromeError(f"Chrome refused {method}: {error}") from error
        raise ChromeError(f"Chrome stopped answering during {method}")

    def answered(self, method, timeout, leave, params):
        """The answer to a call a dialog can hold, or what the dialog that is holding it means.

        The call is sent from a thread of its own, so that while it waits this one can read what
        the page announced. Input that a dialog is holding has landed - the dialog is what it did -
        so it counts as sent. Anything else the dialog holds is refused as a page that moved, and a
        before-unload dialog that holds a navigation the caller asked for is answered by leaving.
        """
        answer = Future()

        def ask():
            try:
                answer.set_result(cdp(method, session_id=self.session_id, _response_timeout=timeout, **params))
            except BaseException as error:
                answer.set_exception(error)

        threading.Thread(target=ask, name=f"jev-ra {method}", daemon=True).start()
        while not wait([answer], timeout=DIALOG_CHECK_S).done:
            self.events()
            if self.detached:
                # A call pending on a target that goes away is never answered at all.
                if self.openers:
                    raise StalePage(f"The window closed during {method}. Observe again.")
                raise ChromeError(f"The page this session drives closed during {method}.")
            if self.dialog is None:
                continue
            if method.startswith("Input."):
                return {}
            if leave and self.dialog["type"] == "beforeunload":
                logger.info("Leaving a page that asked to be kept, because the caller asked to go")
                self.reply({"dialog": "accept"})
                continue
            raise DialogOpen(f"A {self.dialog['type']} dialog opened during {method}.")
        return answer.result()

    def events(self):
        """Read what the browser announced about this target since the last time, and keep what matters.

        The status of the main document is the last one it was served with. A dialog is open from
        the moment Chrome says so until Chrome says it closed; the next one is a new dialog.
        """
        try:
            events = INBOX.take(self.session_id)
        except (RuntimeError, TimeoutError, OSError) as error:
            logger.info("The browser would not report its events: %s", error)
            return
        for event in events:
            method, params = event.get("method"), event.get("params") or {}
            if method == "Page.javascriptDialogOpening":
                self.dialogs += 1
                self.dialog = {**params, "id": self.dialogs}
            elif method == "Page.javascriptDialogClosed":
                self.dialog = None
            elif method in {"Inspector.detached", "Target.detachedFromTarget"}:
                self.detached = True
            elif method == "Page.fileChooserOpened":
                self.chooser = params
            elif method == "Network.responseReceived" and params.get("type") == "Document":
                if self.frame_id and params.get("frameId") != self.frame_id:
                    continue
                status = (params.get("response") or {}).get("status")
                if isinstance(status, int):
                    self.http_status = status

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

    def reading(self):
        """The marker as the page stands, or None when it will not be read right now."""
        try:
            return self.evaluate(marker_expression(self.max_elements))
        except StalePage:
            return None

    def read_status(self):
        """The HTTP status of this session's main document, from the events the browser queued.

        A 502 is served as a body like any other, so the page itself cannot say which status it
        arrived with; the network events can. Only this session's main-frame document responses
        count, and the last one wins, so a redirect chain ends on the answer the site settled on.
        """
        self.events()
        return self.http_status

    def observed(self, page):
        """One snapshot payload with the status the site answered its document with.

        A file chooser the last input opened stays part of every reading until the next input.
        """
        if not page.get("dialog"):
            self.title = page.get("title", "")
        page = {**page, "http_status": self.read_status()}
        chooser = self.chooser
        return {**page, "file_chooser": self.asked_file(chooser)} if chooser is not None else page

    def asked_file(self, chooser):
        """What a file chooser the page opened asked for: one file or several, and of which kinds."""
        asked = {"multiple": chooser.get("mode") == "selectMultiple"}
        node = chooser.get("backendNodeId")
        if node is None:
            return asked
        try:
            described = self.call("DOM.describeNode", backendNodeId=node, depth=0)
        except (ChromeError, StalePage):
            return asked
        attributes = (described.get("node") or {}).get("attributes") or []
        accept = dict(zip(attributes[::2], attributes[1::2], strict=True)).get("accept", "").strip()
        return {**asked, "accept": accept} if accept else asked

    def dialog_page(self):
        """The open dialog as the page in front of the page."""
        viewport = self.config.viewport
        return dialog_page(self.dialog, self.title, viewport.width, viewport.height)

    def reply(self, action, text=None):
        """Answer the open dialog the way an observed action says, or keep what was typed into it."""
        dialog = self.dialog
        if dialog is None:
            raise StalePage("No dialog is open to answer. Observe again.")
        if action["dialog"] == "text":
            self.dialog = {**dialog, "text": text}
            return
        accept = action["dialog"] == "accept"
        params = {"accept": accept}
        if accept and dialog["type"] == "prompt":
            params["promptText"] = prompt_text(dialog)
        self.dialog = None
        try:
            self.call("Page.handleJavaScriptDialog", **params)
        except ChromeError as error:
            raise StalePage(f"The {dialog['type']} dialog was already gone. Observe again.") from error

    def open(self, url):
        """Navigate, wait for the load to finish, and observe."""
        url = check_url(url, self.config)
        self.after_input = None
        # Events still queued belong to the page this call is leaving; the status that matters is
        # what the new document is served with, and read_status only keeps the latest answer.
        self.read_status()
        # An address that names a fragment may be answered by the router of the document already
        # open rather than by a new one, and then there is a view to wait for. Read where the page
        # stands before asking for it; an address without a fragment never pays for this.
        was = self.reading() if urlsplit(url).fragment else None
        self.invalidate()
        moved = self.call("Page.navigate", timeout=NAVIGATE_TIMEOUT_S, leave=True, url=url)
        self.frame_id = moved.get("frameId") or self.frame_id
        if moved.get("errorText"):
            # A navigation the browser itself refused never had a response, so no status of an
            # earlier document may stand in for it.
            logger.info("The browser could not open %s: %s", url, moved["errorText"])
            self.http_status = None
        started = time.monotonic()
        self.glimpse()
        self.load(LOAD_TIMEOUT_S - (time.monotonic() - started))
        self.paint()
        # A same-document navigation is answered without a loader: nothing reloaded, so the
        # document was complete before the call and stays complete, and readyState says nothing
        # about the view the fragment names. Changing the part after the # is a navigation like
        # any other, and gets the wait the navigation a click starts already gets.
        if was and not moved.get("loaderId"):
            self.wait_out({"kind": "navigate"}, was, None)
        return self.observe()

    def glimpse(self, budget=LOAD_TIMEOUT_S):
        """Hand a reading of a document that has parsed but not yet loaded to whoever can use one.

        The load is still waited for, and the page is still observed once it is done: this reading
        is only a head start for a caller that confirms, character for character, that the loaded
        page reads the same. A document that is already complete has no load left to overlap.
        """
        if self.preview is None:
            return
        expression = f"{PARSED_JS}({json.dumps({'budget_ms': round(budget * 1000)})})"
        try:
            if self.evaluate(expression, await_promise=True) != "interactive" or not self.evaluate(PAINTED_JS):
                return
            reading = self.evaluate(snapshot_expression(self.max_elements))
        except StalePage:
            logger.debug("The document was replaced while it was being glimpsed")
            return
        if reading and not reading.get("leaving"):
            self.preview(reading)

    def reload(self, timer=None):
        """Ask for the current document again, wait for it, and observe."""
        self.after_input = None
        self.invalidate()
        self.call("Page.reload", timeout=NAVIGATE_TIMEOUT_S, leave=True)
        self.load()
        self.paint()
        return self.observe(timer)

    def quiet(self, budget_s, after=None, quiet_ms=QUIET_MS, origin=None):
        """Wait in the page until it stops changing, and say whether it did.

        `{"quiet": ..., "count": ...}`: whether the document went still inside the budget rather
        than running out of it, and how many times it has mutated, which a caller waiting for
        something that has not happened yet passes back as `after`. A document other than the one
        born at `origin` counts as changed whatever its count, which started again at nothing. None
        when the document moved under the probe, which is the answer to observe again.
        """
        options = {"quiet_ms": quiet_ms, "budget_ms": max(0, round(budget_s * 1000)), "after": after}
        if origin is not None:
            options["origin"] = origin
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
            if remaining <= 0 or self.dialog is not None:
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
            if remaining <= 0 or self.dialog is not None:
                return False
            answer = self.quiet(remaining, after=seen)
            if answer is None:
                continue
            if not answer["quiet"]:
                return False
            seen = answer["count"]

    def settle(self, timer=None):
        """Wait out the effect of the last input before observing again."""
        timer = timer or NullTimer()
        action, self.after_input = self.after_input, None
        was, self.moved_from = self.moved_from, None
        before, self.before_input = self.before_input, None
        windows, self.windows_before = self.windows_before, None
        if action is None:
            return
        opened = self.windows() - windows if windows is not None else set()
        if opened:
            self.follow(min(opened))
            return
        if action["kind"] == "wait":
            # A wait was chosen because something has not arrived yet: the next batch of a feed,
            # the results a search is still fetching. What it waits for is the page's next change
            # after the reading it was chosen on, then the settling any other step gets.
            with timer.measure("wait"):
                self.quiet(
                    SETTLE_BUDGET_S,
                    after=action.get("mutations"),
                    quiet_ms=0,
                    origin=was[MARKER_ORIGIN] if was else None,
                )
        # Read-only, and only after the action was already recorded: navigation may cut it short.
        first = None
        settling = f"{SETTLE_JS}({json.dumps(action)}).then(() => {snapshot_expression(self.max_elements)})"
        with timer.measure("wait"):
            try:
                first = self.evaluate(settling, await_promise=True)
            except (StalePage, ChromeError, RuntimeError) as error:
                # A page that outlasts even the evaluating budget is still only a page this run
                # waited for: the timeout is logged and the step goes on to read the marker.
                logger.debug("Post-input settle was interrupted: %s", error)
        self.wait_out(action, was, before, first, timer)
        if was:
            self.arrive(was, timer)

    def arrive(self, was, timer):
        """Wait for a document the input loaded to arrive, when the step's wait ended before it did.

        A reading that already shows words has arrived, wherever it is, and is kept without asking
        the page anything more; so is one on the document the step started on. A document that
        replaces itself while this waits is asked again until the budget runs out.
        """
        reading, self.settled = self.settled, None
        if reading and reading.get("text"):
            self.settled = reading
            return
        try:
            origin = reading["marker"][MARKER_ORIGIN] if reading else self.evaluate("performance.timeOrigin")
        except StalePage:
            origin = None
        if origin == was[MARKER_ORIGIN]:
            self.settled = reading
            return
        deadline = time.monotonic() + ARRIVAL_BUDGET_S
        with timer.measure("wait"):
            while True:
                if self.dialog is not None or self.detached:
                    # A dialog holds the page, and a window that closed itself has none: neither
                    # is a document on its way, and the reading after this says which it was.
                    return
                options = {"budget_ms": max(0, round((deadline - time.monotonic()) * 1000)), "poll_ms": ARRIVAL_POLL_MS}
                try:
                    answer = self.evaluate(f"{ARRIVED_JS}({json.dumps(options)})", await_promise=True)
                except StalePage:
                    answer = None
                if answer is not None:
                    if answer["arrived"] and not answer["waited"]:
                        self.settled = reading
                    return
                if time.monotonic() >= deadline:
                    return

    def wait_out(self, action, was, before, first=None, timer=None):
        """One budget and one reading per turn for everything a step waits for.

        Three waits used to run here one after another, each on its own clock and its own
        deadline: the route an address had already moved to, whatever the click opened, and the
        page going quiet. They are three questions about successive readings of the same marker,
        so read it, answer all three, and then wait for the page itself to say it has changed or
        stopped changing rather than asking again on a timer. Two identical readings of a page
        that is not moving end the wait, whatever the input was; a page that never stops moving
        costs the budget it always did.
        """
        timer = timer or NullTimer()
        opens = bool(before) and action.get("kind") == "click" and action.get("role") == "button"
        deadline = time.monotonic() + SETTLE_BUDGET_S
        expression = snapshot_expression(self.max_elements)
        previous, opened, differed = None, not opens, False
        ready, still, count, reading = None, False, None, first
        if action.get("kind") == "click" and action.get("href") and was and action["href"] != was[MARKER_URL]:
            route_budget = min(ROUTE_BUDGET_S, max(0.0, deadline - time.monotonic()))
            if route_budget:
                try:
                    route_options = json.dumps({"url": was[MARKER_URL], "budget_ms": round(route_budget * 1000)})
                    changed = self.evaluate(
                        f"{ROUTE_WAIT_JS}({route_options})",
                        await_promise=True,
                    )
                except StalePage:
                    changed = True
                if changed:
                    reading = None
        while True:
            if reading is None:
                with timer.measure("snapshot"):
                    try:
                        reading = self.evaluate(expression)
                    except StalePage:
                        return
            if not reading:
                return
            marker = reading["marker"]
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
                # The page this wait ended on is the page the step observes; reading it again is
                # a second evaluation of the same document for the same answer.
                self.settled = reading
                return
            # A reading that shows the input's effect and has caught up with its address is what
            # the rest of this wait may well end on: the page only has to hold still to confirm it.
            # A document already on its way out never is.
            if self.preview is not None and caught_up and not reading.get("leaving") and marker not in (previous, was):
                self.preview(reading)
            if opened and caught_up:
                if ready is None:
                    ready = time.monotonic()
                elif time.monotonic() - ready >= QUIET_BUDGET_S:
                    # Out of patience rather than proven still, but this reading was taken a moment
                    # ago and nothing has been waited for since: it is the page as it stands, and
                    # reading it again would only say the same thing later.
                    self.settled = reading
                    return
            # Two identical readings of a page that is not moving: only its next change can answer
            # what this wait is still asking, so that is what the next turn waits for.
            after = count if still and marker == previous else None
            previous = marker
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.settled = reading
                return
            # A click whose answer has already shown up in a reading only has to stop moving; one
            # that has shown nothing yet is given longer, because a panel that mounts a beat later
            # is preceded by the page moving and only a page gone properly still has nothing more.
            stillness = QUIET_MS if opened or differed else UNANSWERED_QUIET_MS
            # Waiting for a change that has not happened yet has nothing else to interrupt it, so
            # it may have the rest of the budget; waiting for stillness leaves room to read again.
            budget = remaining if after is not None else min(remaining, (stillness + QUIET_SLICE_MS) / 1000)
            with timer.measure("wait"):
                answer = self.quiet(budget, after=after, quiet_ms=stillness)
            still = answer is not None and answer["quiet"]
            count = answer["count"] if answer is not None else None
            reading = None

    def observe(self, timer=None):
        """One atomic reading of the page: text, elements, actions, guards and marker."""
        timer = timer or NullTimer()
        self.returned()
        self.settle(timer)
        # A window that closes itself does so while its last input is still settling.
        self.returned()
        with timer.measure("snapshot"):
            settled, self.settled = self.settled, None
            if self.dialog is not None:
                return self.observed(self.dialog_page())
            if settled is not None:
                return self.observed(settled)
            for attempt in range(SETTLE_ATTEMPTS):
                try:
                    page = self.evaluate(snapshot_expression(self.max_elements))
                except DialogOpen:
                    return self.observed(self.dialog_page())
                except StalePage:
                    page = None
                if page is not None:
                    return self.observed(page)
                if attempt < SETTLE_ATTEMPTS - 1:
                    time.sleep(WAIT_SLEEP_S if attempt else 0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        """Whether the observed page still describes what is about to be acted on."""
        if action is not None and action.get("dialog"):
            self.events()
            return self.dialog is not None and page.get("marker") == self.dialog_page()["marker"]
        # A key that names no field - Escape out of a dialog - is fresh while the whole page is.
        if action is not None and action.get("kind") in TARGETED and "node" in action:
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
        self.chooser = None
        kind = action["kind"]
        # Any input can open a window - a button, a key, even the answer to a confirm - and the
        # windows already open before it are not what it opened.
        self.windows_before = self.windows() if kind not in {"wait", "scroll"} else None
        if action.get("dialog"):
            self.reply(action, text)
        elif kind == "press":
            self.submit(action)
        elif kind == "scroll":
            point = self.wheel(action)
            self.call("Input.dispatchMouseEvent", type="mouseWheel", deltaX=0, deltaY=action["delta"], **point)
        elif kind != "wait":
            self.input(action, text)
        # A wait sends nothing: waiting is what the settle after it does, for the page's next change.
        self.after_input = {**action, "mutations": page.get("mutations")} if kind == "wait" else action
        self.moved_from = page.get("marker")
        self.invalidate()
        return {"executed": action["id"], "kind": kind, "text": text}

    def wheel(self, action):
        """Where the wheel goes for a scroll: a point from which it moves the box the action names.

        A scroll without a box is the document's, and the middle of the viewport is where it has
        always gone when the page gives no better point.
        """
        node = action.get("node")
        box = "null" if node is None else observed(node)
        point = self.evaluate(f"window.__jevRa?.wheel({box}, {json.dumps(action['delta'])}) ?? null")
        if point is not None:
            return {"x": point["x"], "y": point["y"]}
        if node is not None:
            raise StalePage("The box that scrolls is gone. Observe again.")
        viewport = self.config.viewport
        return {"x": viewport.width // 2, "y": viewport.height // 2}

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
        if action["kind"] == "fill" and action.get("format"):
            self.set_value(action, text)
            return
        self.click(self.resolve(action))
        if self.dialog is not None:
            return
        if action["kind"] == "fill" and not self.focused(action["node"]):
            time.sleep(FOCUS_SLEEP_S)
            if not self.focused(action["node"]) and not self.handed(action["node"]) and not self.focus(action["node"]):
                raise StalePage("The field never took focus. Observe again.")
        if action["kind"] == "fill":
            self.select_all()
            self.call("Input.insertText", text=text)

    def set_value(self, action, text):
        """Give a field the browser draws itself its value, or say what it takes when it will not keep it."""
        answer = self.evaluate(f"{SET_JS}({json.dumps({'node': observed(action['node']), 'text': text})})")
        if answer is None:
            raise StalePage("Target changed or is covered. Observe again.")
        if answer["took"]:
            return
        kind = action["format"]
        takes = FORMATS.get(kind) or (f"a number from {answer['min']} to {answer['max']} in steps of {answer['step']}")
        raise BadValue(f"{action.get('label') or 'The field'} takes {takes}, and {text!r} is not one.")

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
            if self.dialog is not None:
                return
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

    def handed(self, node):
        """Whether pressing the observed field moved focus onto another text field to type into."""
        return bool(self.evaluate(f"({HANDED_JS})({observed(node)})"))

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
            if self.dialog is not None:
                break
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

    def front(self):
        """Bring this target's tab to the front, and its window back when it was minimized.

        Whoever is at the machine is about to be asked to look at this page. Neither call is worth
        a run: a browser that will not raise its window is still a browser showing the page.
        """
        try:
            self.call("Page.bringToFront")
            window = cdp("Browser.getWindowForTarget", targetId=self.target_id)
            if (window.get("bounds") or {}).get("windowState") == "minimized":
                cdp("Browser.setWindowBounds", windowId=window["windowId"], bounds={"windowState": "normal"})
        except (ChromeError, StalePage, RuntimeError, TimeoutError, OSError, KeyError) as error:
            logger.info("The browser would not bring the page to the front: %s", error)

    def screenshot(self):
        """The current viewport as JPEG bytes."""
        shot = self.call("Page.captureScreenshot", timeout=EVALUATE_TIMEOUT_S, format="jpeg", quality=72)
        return base64.b64decode(shot["data"])

    def close(self):
        """Close the target this session owns, and any window it followed out of it."""
        INBOX.close(self.session_id)
        while self.openers:
            try:
                cdp("Target.closeTarget", targetId=self.target_id)
            except RuntimeError:
                logger.info("The window this session followed had already closed")
            self.target_id, self.session_id, *_rest = self.openers.pop()
            INBOX.close(self.session_id)
        if self.target_id:
            cdp("Target.closeTarget", targetId=self.target_id)
            self.target_id = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def prompt_text(dialog):
    """What a prompt answers with: what was typed into it, or what it offered to begin with."""
    return dialog.get("text", dialog.get("defaultPrompt") or "")


def dialog_page(dialog, title, width, height):
    """A JavaScript dialog observed the way a person meets it: what it says, and its answers.

    It is the page in front of the page, as a consent wall is, and the only thing a run can do while
    it is up. Chrome heads it with the host that asked; a prompt adds the field it asks to fill. Its
    controls are named nodes of the dialog's own rather than of the page, and answering one is
    `Page.handleJavaScriptDialog`, never input sent to a page that is not listening.
    """
    url = dialog.get("url", "")
    said = LEAVE_TEXT if dialog["type"] == "beforeunload" else dialog.get("message", "")
    host = urlsplit(url).netloc
    text = f"{host} says\n{said}" if host else said
    offered = []
    if dialog["type"] == "prompt":
        offered.append(("text", "textbox", "fill", dialog.get("message") or "Answer", prompt_text(dialog)))
    offered += [(answer, "button", "click", label, "") for answer, label in DIALOG_ANSWERS[dialog["type"]]]
    elements, actions = [], []
    for index, (answer, role, kind, label, value) in enumerate(offered, 1):
        ref, node = f"e{index}", f"dialog:{answer}"
        elements.append({"node": node, "ref": ref, "role": role, "label": label, "value": value})
        actions.append(
            {"id": ref, "node": node, "role": role, "kind": kind, "label": label, "value": value, "dialog": answer}
        )
    fields = [["dialog:text", prompt_text(dialog)]] if dialog["type"] == "prompt" else []
    # Laid out as a page's marker is - origin, address, scroll, size, then the page itself - so a
    # reading of the dialog compares with a reading of the page the way two page readings do.
    marker = [f"dialog:{dialog['id']}", url, 0, 0, width, height, title, text, elements, actions, fields]
    return {
        "url": url,
        "title": title,
        "w": width,
        "h": height,
        "text": text,
        "doc_text": text,
        "scroll": {"y": 0, "height": height},
        "elements": elements,
        "actions": actions,
        "marker": marker,
        "page_key": [marker[0], url, 0, 0, width, height, fields],
        "guards": {},
        "omitted": 0,
        "dialog": dialog["type"],
    }


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
