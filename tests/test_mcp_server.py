import asyncio
import json
import re
import signal
from pathlib import Path

import pytest
from mcp import Client

from jev_ra import config, mcp_server
from jev_ra.decide import Reply
from jev_ra.errors import ChromeError
from jev_ra.mcp_server import Browser, build_server
from tests.test_agent import FakeSession, answer, page

ROOT = Path(__file__).resolve().parents[1]

TOOLS = {
    "browser_open",
    "browser_run",
    "browser_act",
    "browser_observe",
    "browser_search",
    "browser_extract",
    "browser_click",
    "browser_type",
    "browser_select",
    "browser_scroll",
    "browser_press",
    "browser_wait",
    "browser_screenshot",
    "browser_close",
}


def decide_done(state, questions):
    return Reply(
        answers={"operation": answer("DONE"), "goal_achieved": {"noul": 0.95}},
        latency_ms=12,
        usage={"cost": 0.0001},
    )


def server_with(session=None, decide=decide_done):
    fake = session or FakeSession()
    browser = Browser(config=config.load({}), session_factory=lambda: fake, decide=decide)
    return build_server(browser), browser, fake


def call(server, name, **arguments):
    async def once():
        async with Client(server, raise_exceptions=False) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(once())


def payload(result):
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


async def tools_of(server):
    async with Client(server) as client:
        return (await client.list_tools()).tools


def test_the_tool_list_matches_the_design_table():
    server, _browser, _session = server_with()
    tools = asyncio.run(tools_of(server))
    assert {tool.name for tool in tools} == TOOLS
    assert all(tool.description for tool in tools)


HINTS = ("read_only_hint", "destructive_hint", "idempotent_hint", "open_world_hint")
READ_ONLY = {"browser_observe", "browser_extract", "browser_screenshot", "browser_wait"}
CLOSED_WORLD = {"browser_observe", "browser_extract", "browser_screenshot", "browser_wait", "browser_close"}


def test_every_tool_declares_all_four_annotation_hints():
    # MCP tool annotations. Clients and directories (OpenAI's rejects tools missing any of the
    # four) use them to decide what to confirm with the user, so an unset hint is a wrong hint.
    server, _browser, _session = server_with()
    for tool in asyncio.run(tools_of(server)):
        assert tool.annotations is not None, tool.name
        for hint in HINTS:
            assert isinstance(getattr(tool.annotations, hint), bool), (tool.name, hint)
        assert tool.annotations.read_only_hint is (tool.name in READ_ONLY), tool.name
        assert tool.annotations.open_world_hint is (tool.name not in CLOSED_WORLD), tool.name
        assert tool.annotations.destructive_hint is False, tool.name


def test_readme_lists_every_tool():
    server, _browser, _session = server_with()
    registered = {tool.name for tool in asyncio.run(tools_of(server))}
    text = (ROOT / "README.md").read_text()
    section = text.split("## MCP tools", 1)[1].split("## CLI", 1)[0]
    listed = set(re.findall(r"^\| `(browser_\w+)`", section, re.MULTILINE))
    assert listed == registered


def test_browser_open_summarises_the_page():
    server, _browser, _session = server_with()
    result = payload(call(server, "browser_open", url="http://127.0.0.1/form.html"))
    assert result["title"] == "Booking form"
    assert result["elements"] == 2
    assert result["elapsed_ms"] >= 0
    assert len(result["text"]) <= 1500


def test_browser_observe_returns_the_element_table_and_text():
    server, _browser, _session = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    result = payload(call(server, "browser_observe"))
    assert result["elements"] == ["[e1] textbox City", "[e2] button Search flights"]
    assert result["text"] == "Booking form"
    assert result["omitted"] == 0


def test_browser_run_returns_the_result_json():
    server, _browser, _session = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    result = payload(call(server, "browser_run", goal="confirm the page"))
    assert result["status"] == "done"
    assert result["reason"] == "goal_achieved"
    assert result["decisions"] == 1
    assert result["cost"] == pytest.approx(0.0001)
    assert result["elapsed_ms"] >= 0
    assert result["steps"] == []
    assert "final_page" in result


def test_tools_refuse_to_work_on_a_closed_session():
    server, _browser, _session = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    assert payload(call(server, "browser_close"))["ok"] is True
    failed = call(server, "browser_observe")
    assert failed.is_error
    assert "No browser session is open" in failed.content[0].text
    assert call(server, "browser_close").is_error


def test_direct_tools_move_the_browser_without_a_decision():
    calls = []

    def never(state, questions):
        calls.append(questions)
        raise AssertionError("no decision expected")

    server, _browser, fake = server_with(decide=never)
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    assert payload(call(server, "browser_click", ref="e2"))["title"] == "Booking form"
    assert payload(call(server, "browser_type", ref="e1", text="London"))["elements"] == 2
    assert fake.acted == [("e2", "click", None), ("e1", "fill", "London")]
    assert calls == []


def test_an_unknown_ref_comes_back_as_a_tool_error():
    server, _browser, _session = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    failed = call(server, "browser_click", ref="e9")
    assert failed.is_error
    assert "No click action for e9" in failed.content[0].text


def test_extract_rejects_an_unknown_mode():
    server, _browser, _session = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    failed = call(server, "browser_extract", mode="summary")
    assert failed.is_error
    assert "mode must be one of" in failed.content[0].text


class DeadChrome(FakeSession):
    """A session whose Chrome was killed under it: it opened once, and refuses everything after."""

    def open(self, url):
        return page(0)

    def observe(self, timer=None):
        raise ChromeError("Chrome refused Runtime.evaluate: no close frame received")

    def close(self):
        raise ChromeError("Chrome refused Target.closeTarget: no close frame received")


def browser_with(factory):
    browser = Browser(config=config.load({}), session_factory=factory, decide=decide_done)
    return build_server(browser), browser


def test_a_dead_chrome_is_reported_and_its_session_is_dropped():
    server, browser, _session = server_with(session=DeadChrome())
    payload(call(server, "browser_open", url="http://127.0.0.1/form.html"))
    failed = call(server, "browser_observe")
    assert failed.is_error
    assert "no close frame received" in failed.content[0].text
    assert "jev-ra doctor" in failed.content[0].text
    assert browser.session is None


def test_the_open_after_a_dead_chrome_builds_a_new_session():
    built = []

    def factory():
        built.append(FakeSession() if built else DeadChrome())
        return built[-1]

    server, _browser = browser_with(factory)
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    assert call(server, "browser_observe").is_error
    assert payload(call(server, "browser_open", url="http://127.0.0.1/form.html"))["title"] == "Booking form"
    assert len(built) == 2


def test_a_close_that_refuses_still_forgets_the_session():
    server, browser, _session = server_with(session=DeadChrome())
    call(server, "browser_open", url="http://127.0.0.1/form.html")
    failed = call(server, "browser_close")
    assert failed.is_error
    assert "jev-ra doctor" in failed.content[0].text
    assert browser.session is None


def test_a_session_that_cannot_be_built_says_why():
    def factory():
        raise ChromeError("No Chrome, Chromium or Edge found")

    server, _browser = browser_with(factory)
    failed = call(server, "browser_open", url="http://127.0.0.1/form.html")
    assert failed.is_error
    assert "No Chrome, Chromium or Edge found" in failed.content[0].text
    assert "jev-ra doctor" in failed.content[0].text


class FakeBrowser:
    def __init__(self):
        self.closed = 0
        self.holding = True

    def close(self):
        if self.holding:
            self.holding = False
            self.closed += 1


def served(monkeypatch, run):
    """Run main() with a fake Browser, a fake server and no way of really exiting."""
    browser = FakeBrowser()
    handlers = {}
    left = []

    class FakeServer:
        def run(self, transport):
            assert transport == "stdio"
            run(handlers)

    monkeypatch.setattr(mcp_server, "Browser", lambda: browser)
    monkeypatch.setattr(mcp_server, "build_server", lambda given: FakeServer())
    monkeypatch.setattr(mcp_server.signal, "signal", lambda number, handler: handlers.setdefault(number, handler))

    def leave(code=0):
        left.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(mcp_server, "leave", leave)
    return browser, handlers, left


def test_the_server_closes_its_browser_when_the_client_disconnects(monkeypatch):
    browser, _handlers, left = served(monkeypatch, lambda _handlers: None)
    mcp_server.main()
    assert browser.closed == 1
    assert left == []


def test_sigterm_closes_the_browser_and_then_stops_the_process(monkeypatch):
    def terminated(handlers):
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    browser, handlers, left = served(monkeypatch, terminated)
    with pytest.raises(SystemExit):
        mcp_server.main()
    assert signal.SIGTERM in handlers
    assert browser.closed == 1
    assert left == [0]
