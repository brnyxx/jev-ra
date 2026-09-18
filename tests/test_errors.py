"""One taxonomy, one sentence per failure, the same on every surface."""

import asyncio

import pytest
from mcp import Client

from jev_ra import cli, config, errors
from jev_ra.mcp_server import Browser, build_server
from tests.test_agent import FakeSession

TAXONOMY = (
    errors.ConfigError,
    errors.ChromeError,
    errors.JevError,
    errors.JevAuthError,
    errors.JevUnavailable,
    errors.JevBadResponse,
    errors.StalePage,
    errors.Escalated,
)

EVERY_ERROR = (errors.JevRaError, *TAXONOMY)


class RaisingSession:
    """A session that refuses every open with one error, for surface mapping."""

    def __init__(self, error):
        self.error = error

    def open(self, _url):
        raise self.error

    def close(self):
        pass


@pytest.mark.parametrize("kind", TAXONOMY)
def test_every_error_is_a_jev_ra_error_with_a_next_step(kind):
    error = kind("something went wrong")
    assert isinstance(error, errors.JevRaError)
    assert error.next_step
    assert error.next_step.endswith(".")
    assert error.render() == f"something went wrong {error.next_step}"


def test_the_next_step_can_be_overridden_per_error():
    error = errors.ConfigError("No viewport.", next_step="Set JEV_RA_VIEWPORT.")
    assert error.render() == "No viewport. Set JEV_RA_VIEWPORT."


def test_render_falls_back_to_str_for_foreign_errors():
    assert errors.render(LookupError("No click action for e9")) == "No click action for e9"
    assert errors.render(errors.StalePage("The page moved.")) == (
        "The page moved. Observe the page again before acting on it."
    )


def test_a_stale_page_is_still_a_value_error_for_older_callers():
    assert isinstance(errors.StalePage("x"), ValueError)


def test_the_specific_errors_keep_their_families():
    assert issubclass(errors.JevAuthError, errors.JevError)
    assert issubclass(errors.JevUnavailable, errors.JevError)
    assert issubclass(errors.JevBadResponse, errors.JevError)
    from jev_ra.text import NeedsValue

    assert issubclass(NeedsValue, errors.Escalated)


def test_a_missing_key_names_the_variable_to_export():
    rendered = errors.ConfigError("No Jev API key found in JEV_RA_API_KEY.").render()
    assert "OPENROUTER_API_KEY" in rendered
    assert "jev-ra doctor" in rendered


def test_a_missing_chrome_says_how_to_start_one():
    rendered = errors.ChromeError("No Chrome answered.").render()
    assert "--remote-debugging-port" in rendered
    assert "BU_CDP_URL" in rendered


def failing_tool_call(server, name, **arguments):
    """The tool's own sentence, with the SDK's `Error executing tool X:` framing removed."""

    async def once():
        async with Client(server, raise_exceptions=False) as client:
            return await client.call_tool(name, arguments)

    result = asyncio.run(once())
    assert result.is_error
    text = result.content[0].text
    prefix = f"Error executing tool {name}: "
    assert text.startswith(prefix), text
    return text[len(prefix) :]


def test_the_mcp_error_text_equals_the_cli_error_text(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "Session", lambda *_a, **_k: FakeSession())
    cli.main(["open", "http://127.0.0.1/form.html"])
    capsys.readouterr()
    assert cli.main(["click", "e9"]) == 1
    from_cli = capsys.readouterr().err.strip()

    fake = FakeSession()
    server = build_server(Browser(config=config.load({}), session_factory=lambda: fake, decide=None))

    async def opened():
        async with Client(server, raise_exceptions=False) as client:
            await client.call_tool("browser_open", {"url": "http://127.0.0.1/form.html"})

    asyncio.run(opened())
    from_mcp = failing_tool_call(server, "browser_click", ref="e9")
    assert from_cli == from_mcp == "No click action for e9 on this page"


def test_a_closed_session_says_the_same_thing_on_both_surfaces(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert cli.main(["observe"]) == 1
    from_cli = capsys.readouterr().err.strip()
    assert from_cli == "No open session. Run `jev-ra open URL` first."

    server = build_server(Browser(config=config.load({}), session_factory=FakeSession, decide=None))
    from_mcp = failing_tool_call(server, "browser_observe")
    assert from_mcp == "No browser session is open. Call browser_open first."


@pytest.mark.parametrize("kind", EVERY_ERROR)
def test_the_cli_exits_1_with_the_rendered_error(kind, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    error = kind("something went wrong")
    monkeypatch.setattr(cli, "Session", lambda *_a, **_k: RaisingSession(error))
    assert cli.main(["open", "http://127.0.0.1/form.html"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == error.render()


@pytest.mark.parametrize("kind", EVERY_ERROR)
def test_the_mcp_error_payload_carries_the_rendered_error(kind, tmp_path):
    error = kind("something went wrong")
    browser = Browser(
        config=config.load({}, path=tmp_path / "config.json"),
        session_factory=lambda: RaisingSession(error),
        decide=None,
    )
    server = build_server(browser)
    assert failing_tool_call(server, "browser_open", url="http://127.0.0.1/form.html") == error.render()
