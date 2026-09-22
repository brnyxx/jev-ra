"""MCP stdio server. One browser session per process, shared by every tool."""

import logging
import os
import signal
import sys
import threading
import time

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .agent import Agent
from .browser import MAX_ELEMENTS, actions
from .browser.session import Session
from .config import MAX_PAGES_LIMIT, MAX_STEPS_LIMIT, MAX_VALUE_CHARS, MAX_VALUES, clamp, load
from .decide.client import DecisionClient
from .errors import ChromeError, JevRaError, render
from .extract import MODES, extract
from .search import MAX_PAGES, search

logger = logging.getLogger(__name__)

SUMMARY_TEXT_CHARS = 1500
# mcp dispatches sync tool bodies through anyio.to_thread, so nothing stops two of them landing on
# the one session this server holds: one target, one element cache, one pending-input record. Long
# enough that a tool queued behind a quick observe still runs; short enough that a client waiting
# on a whole browser_run is told to wait rather than left hanging.
BUSY_TIMEOUT_S = 0.5
BUSY = "busy: another tool is still running on this session; wait for it or call browser_close"
OBSERVE_TEXT_CHARS = 3000
INSTRUCTIONS = """Drive a real Chrome. browser_open first, then browser_run for a whole goal,
or the single-step tools when you want to steer. Supply `values` for anything that must be typed:
without them a TYPE_TEXT step comes back as an escalation instead of a guess."""


def hints(read_only=False, idempotent=False, open_world=True):
    """MCP tool annotations.

    Nothing here deletes or overwrites anything the user owns, so no tool is destructive; tools that
    act on a live site are open-world and, when a second call would act again, not idempotent.
    """
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=False,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


class Browser:
    """Lazily opened session plus the decision client the agent shares."""

    def __init__(self, config=None, session_factory=None, decide=None):
        self.config = config or load()
        self.lock = threading.RLock()
        self.session_factory = session_factory or (lambda profile=None: Session(self.config, profile=profile))
        self.decide = decide
        self.session = None
        self.client = None
        self.profile = None

    def guarded(self, call):
        """Run one tool body alone on this session, in the sentence every other surface uses."""
        if not self.lock.acquire(timeout=BUSY_TIMEOUT_S):
            raise ToolError(BUSY)
        try:
            return call()
        except ChromeError as error:
            # The browser this session was attached to is gone. Keeping the session would answer
            # every later call with the same refusal, browser_open included; dropping it here is
            # what lets the next browser_open start a Chrome and carry on.
            self.dropped()
            raise ToolError(render(error)) from None
        except (JevRaError, LookupError) as error:
            raise ToolError(render(error)) from None
        finally:
            self.lock.release()

    def open(self, profile=None):
        """Open the shared session on a profile, creating it on first use."""
        if profile is not None and self.profile is not None and profile != self.profile:
            raise ToolError(
                f"This server is driving the {self.profile!r} profile. "
                f"Call browser_close and start a server of its own for {profile!r}: "
                "browser-harness pins one browser per process."
            )
        if self.session is None:
            self.session = self.session_factory(profile=profile or self.profile)
            self.profile = profile or self.profile
        return self.session

    def require(self):
        """The open session, or a ToolError telling the caller to open one."""
        if self.session is None:
            raise ToolError("No browser session is open. Call browser_open first.")
        return self.session

    def decider(self):
        """The decision callable, creating the client only when it is really needed."""
        if self.decide is not None:
            return self.decide
        if self.client is None:
            self.client = DecisionClient(self.config)
        return self.client.decide

    def agent(self):
        """An agent bound to the shared session and the decision model."""
        return Agent(session=self.require(), config=self.config, decide=self.decider())

    def stepper(self):
        """An agent for the direct tools: they move the browser without asking Jev anything."""
        return Agent(session=self.require(), config=self.config, decide=refuse)

    def dropped(self):
        """Forget the session. Its browser is gone, so the next open has to build another."""
        self.session = None

    def close(self):
        """Close the session and the decision client this server holds."""
        if self.session is not None:
            try:
                self.session.close()
            finally:
                self.session = None
        if self.client is not None:
            try:
                self.client.close()
            finally:
                self.client = None


def checked_values(values):
    """The caller's values, or a ToolError naming the limit they went past.

    Unlike the numbers, these cannot be clamped: silently dropping half a host's values would fill
    the wrong fields, so an oversized payload is refused before anything is typed or posted.
    """
    if not values:
        return values
    if len(values) > MAX_VALUES:
        raise ToolError(f"values takes at most {MAX_VALUES} entries; {len(values)} were supplied")
    total = sum(len(str(name)) + len(str(text)) for name, text in values.items())
    if total > MAX_VALUE_CHARS:
        raise ToolError(f"values takes at most {MAX_VALUE_CHARS} characters in all; {total} were supplied")
    return values


def refuse(_state, _questions):
    """Guard for tools that must never reach the decision model."""
    raise ToolError("This tool never calls the decision model")


def element_line(element):
    """Render one observed element as `[ref] role label · value`."""
    line = " ".join(part for part in (f"[{element['ref']}]", element.get("role"), element.get("label")) if part)
    value = element.get("value")
    return f"{line} · {value}" if value else line


def summary(page, started, session):
    """The short page summary every navigating tool returns."""
    space = actions.build(page, session.max_elements)
    return {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text": page.get("text", "")[:SUMMARY_TEXT_CHARS],
        "elements": len(space.elements),
        "omitted": space.omitted,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


def run_result(result, started):
    """A Result as JSON, timed from the tool call rather than the run."""
    payload = result.as_dict()
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    return payload


def build_server(browser=None):
    """Build the MCP server and register every browser tool on it."""
    browser = browser or Browser()
    mcp = MCPServer("jev-ra", version=__version__, instructions=INSTRUCTIONS)

    guarded = browser.guarded

    @mcp.tool(annotations=hints(idempotent=True))
    def browser_open(url: str, profile: str | None = None) -> dict:
        """Open a URL in the shared browser session. A named profile keeps its own cookies."""
        started = time.perf_counter()

        def opened():
            session = browser.open(profile)
            return summary(session.open(url), started, session)

        return guarded(opened)

    @mcp.tool(annotations=hints())
    def browser_run(goal: str, values: dict[str, str] | None = None, max_steps: int | None = None) -> dict:
        """Pursue a whole goal on the current page. Supply values for anything that must be typed."""
        started = time.perf_counter()
        values = checked_values(values)
        steps = clamp(max_steps, 1, MAX_STEPS_LIMIT, "max_steps")
        agent = browser.agent()
        return run_result(guarded(lambda: agent.run(goal, values=values, max_steps=steps)), started)

    @mcp.tool(annotations=hints())
    def browser_act(instruction: str, values: dict[str, str] | None = None) -> dict:
        """Take one decided step towards an instruction on the current page."""
        started = time.perf_counter()
        values = checked_values(values)
        agent = browser.agent()
        return run_result(guarded(lambda: agent.act(instruction, values=values)), started)

    @mcp.tool(annotations=hints(idempotent=True))
    def browser_search(query: str, goal: str | None = None, max_pages: int = MAX_PAGES) -> dict:
        """Search the web, read the best results in parallel tabs, and rank them against the goal."""
        started = time.perf_counter()
        pages = clamp(max_pages, 1, MAX_PAGES_LIMIT, "max_pages")
        decide = browser.decider()
        payload = guarded(
            lambda: search(
                query,
                goal,
                pages,
                config=browser.config,
                decide=decide,
                session_factory=browser.session_factory,
            )
        )
        payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        return payload

    @mcp.tool(annotations=hints(read_only=True, idempotent=True, open_world=False))
    def browser_observe(max_elements: int | None = None) -> dict:
        """List the observed controls and the visible text of the current page."""
        started = time.perf_counter()
        session = browser.require()
        wanted = clamp(max_elements, 1, MAX_ELEMENTS, "max_elements")
        page = guarded(session.observe)
        space = actions.build(page, wanted or session.max_elements)
        return {
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "text": page.get("text", "")[:OBSERVE_TEXT_CHARS],
            "elements": [element_line(element) for element in space.elements],
            "omitted": space.omitted,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }

    @mcp.tool(annotations=hints(read_only=True, idempotent=True, open_world=False))
    def browser_extract(mode: str = "text") -> dict:
        """Pull structured page data from the DOM: text, elements, links, tables or main."""
        started = time.perf_counter()
        session = browser.require()
        if mode not in MODES:
            raise ToolError(f"mode must be one of {', '.join(MODES)}")
        payload = guarded(lambda: extract(session, mode))
        payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        return payload

    @mcp.tool(annotations=hints())
    def browser_click(ref: str) -> dict:
        """Click one observed element by its ref."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().click(ref)), started, session)

    @mcp.tool(annotations=hints())
    def browser_type(ref: str, text: str) -> dict:
        """Type text into one observed field by its ref."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().type(ref, text)), started, session)

    @mcp.tool(annotations=hints(idempotent=True))
    def browser_select(ref: str, option: str) -> dict:
        """Select an observed dropdown option by its value or label."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().select(ref, option)), started, session)

    @mcp.tool(annotations=hints())
    def browser_scroll(direction: str = "down") -> dict:
        """Scroll the page one viewport step up or down."""
        started = time.perf_counter()
        session = browser.require()
        if direction not in {"up", "down"}:
            raise ToolError("direction must be up or down")
        return summary(guarded(lambda: browser.stepper().scroll(direction)), started, session)

    @mcp.tool(annotations=hints())
    def browser_press(key: str) -> dict:
        """Press Enter, Escape or Tab."""
        started = time.perf_counter()
        session = browser.require()
        try:
            page = guarded(lambda: browser.stepper().press(key))
        except ValueError as error:
            raise ToolError(str(error)) from None
        return summary(page, started, session)

    @mcp.tool(annotations=hints(read_only=True, idempotent=True, open_world=False))
    def browser_wait() -> dict:
        """Wait a moment and observe again."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().wait()), started, session)

    @mcp.tool(annotations=hints(read_only=True, idempotent=True, open_world=False))
    def browser_screenshot() -> Image:
        """Capture the current viewport as a JPEG."""
        session = browser.require()
        return Image(data=guarded(session.screenshot), format="jpeg")

    @mcp.tool(annotations=hints(idempotent=True, open_world=False))
    def browser_close() -> dict:
        """Close the browser session held by this server."""
        started = time.perf_counter()

        def closed():
            browser.require()
            browser.close()
            return {"ok": True, "elapsed_ms": round((time.perf_counter() - started) * 1000)}

        return guarded(closed)

    return mcp


def leave(code=0):
    """Exit now. Everything this process held has already been released."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def main():
    """Run the stdio MCP server."""
    logging.basicConfig(level=logging.WARNING)
    browser = Browser()

    def terminate(_number, _frame):
        # Raising SystemExit here instead would unwind through the transport's task group, which
        # answers it with a forty-line "unhandled errors in a TaskGroup" on stderr, and then the
        # interpreter would wait at exit for the worker thread blocked in the stdin read. Both
        # were measured against a real stdio client. Nothing here needs that unwinding.
        browser.close()
        leave(0)

    # A client that goes away sends SIGTERM and nothing else. Without this the process dies where
    # it stands and leaves its Chrome and its target behind for whoever looks at the machine next.
    signal.signal(signal.SIGTERM, terminate)
    try:
        build_server(browser).run("stdio")
    finally:
        browser.close()
