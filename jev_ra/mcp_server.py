"""MCP stdio server. One browser session per process, shared by every tool."""

import logging
import time

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .agent import Agent
from .browser import actions
from .browser.session import Session, StalePage
from .config import load
from .decide.client import DecisionClient, JevError
from .extract import MODES, extract
from .search import MAX_PAGES, search

logger = logging.getLogger(__name__)

SUMMARY_TEXT_CHARS = 1500
OBSERVE_TEXT_CHARS = 3000
INSTRUCTIONS = """Drive a real Chrome. browser_open first, then browser_run for a whole goal,
or the single-step tools when you want to steer. Supply `values` for anything that must be typed:
without them a TYPE_TEXT step comes back as an escalation instead of a guess."""


class Browser:
    """Lazily opened session plus the decision client the agent shares."""

    def __init__(self, config=None, session_factory=None, decide=None):
        self.config = config or load()
        self.session_factory = session_factory or (lambda: Session(self.config))
        self.decide = decide
        self.session = None
        self.client = None

    def open(self):
        """Open the shared session, creating it on first use."""
        if self.session is None:
            self.session = self.session_factory()
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

    def close(self):
        """Close the session and the decision client this server holds."""
        if self.session is not None:
            self.session.close()
            self.session = None
        if self.client is not None:
            self.client.close()
            self.client = None


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

    def guarded(call):
        try:
            return call()
        except StalePage as error:
            raise ToolError(f"The page changed before the action ran: {error}") from None
        except LookupError as error:
            raise ToolError(str(error)) from None
        except JevError as error:
            raise ToolError(str(error)) from None

    @mcp.tool()
    def browser_open(url: str) -> dict:
        """Open a URL in the shared browser session and summarise the page."""
        started = time.perf_counter()
        session = browser.open()
        return summary(guarded(lambda: session.open(url)), started, session)

    @mcp.tool()
    def browser_run(goal: str, values: dict[str, str] | None = None, max_steps: int | None = None) -> dict:
        """Pursue a whole goal on the current page. Supply values for anything that must be typed."""
        started = time.perf_counter()
        agent = browser.agent()
        return run_result(guarded(lambda: agent.run(goal, values=values, max_steps=max_steps)), started)

    @mcp.tool()
    def browser_act(instruction: str, values: dict[str, str] | None = None) -> dict:
        """Take one decided step towards an instruction on the current page."""
        started = time.perf_counter()
        agent = browser.agent()
        return run_result(guarded(lambda: agent.act(instruction, values=values)), started)

    @mcp.tool()
    def browser_search(query: str, goal: str | None = None, max_pages: int = MAX_PAGES) -> dict:
        """Search the web, read the best results in parallel tabs, and rank them against the goal."""
        started = time.perf_counter()
        session = browser.open()
        decide = browser.decider()
        payload = guarded(
            lambda: search(query, goal, max_pages, config=browser.config, decide=decide, session=session)
        )
        payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        return payload

    @mcp.tool()
    def browser_observe(max_elements: int | None = None) -> dict:
        """List the observed controls and the visible text of the current page."""
        started = time.perf_counter()
        session = browser.require()
        page = guarded(session.observe)
        space = actions.build(page, max_elements or session.max_elements)
        return {
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "text": page.get("text", "")[:OBSERVE_TEXT_CHARS],
            "elements": [element_line(element) for element in space.elements],
            "omitted": space.omitted,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }

    @mcp.tool()
    def browser_extract(mode: str = "text") -> dict:
        """Pull structured page data from the DOM: text, elements, links, tables or main."""
        started = time.perf_counter()
        session = browser.require()
        if mode not in MODES:
            raise ToolError(f"mode must be one of {', '.join(MODES)}")
        payload = guarded(lambda: extract(session, mode))
        payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        return payload

    @mcp.tool()
    def browser_click(ref: str) -> dict:
        """Click one observed element by its ref."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().click(ref)), started, session)

    @mcp.tool()
    def browser_type(ref: str, text: str) -> dict:
        """Type text into one observed field by its ref."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().type(ref, text)), started, session)

    @mcp.tool()
    def browser_select(ref: str, option: str) -> dict:
        """Select an observed dropdown option by its value or label."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().select(ref, option)), started, session)

    @mcp.tool()
    def browser_scroll(direction: str = "down") -> dict:
        """Scroll the page one viewport step up or down."""
        started = time.perf_counter()
        session = browser.require()
        if direction not in {"up", "down"}:
            raise ToolError("direction must be up or down")
        return summary(guarded(lambda: browser.stepper().scroll(direction)), started, session)

    @mcp.tool()
    def browser_press(key: str) -> dict:
        """Press Enter, Escape or Tab."""
        started = time.perf_counter()
        session = browser.require()
        try:
            page = guarded(lambda: browser.stepper().press(key))
        except ValueError as error:
            raise ToolError(str(error)) from None
        return summary(page, started, session)

    @mcp.tool()
    def browser_wait() -> dict:
        """Wait a moment and observe again."""
        started = time.perf_counter()
        session = browser.require()
        return summary(guarded(lambda: browser.stepper().wait()), started, session)

    @mcp.tool()
    def browser_screenshot() -> Image:
        """Capture the current viewport as a JPEG."""
        session = browser.require()
        return Image(data=guarded(session.screenshot), format="jpeg")

    @mcp.tool()
    def browser_close() -> dict:
        """Close the browser session held by this server."""
        started = time.perf_counter()
        browser.require()
        browser.close()
        return {"ok": True, "elapsed_ms": round((time.perf_counter() - started) * 1000)}

    return mcp


def main():
    """Run the stdio MCP server."""
    logging.basicConfig(level=logging.WARNING)
    build_server().run("stdio")
