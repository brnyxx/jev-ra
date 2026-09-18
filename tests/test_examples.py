"""The examples run, and the generated usage guide does not drift from the code."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
USAGE = ROOT / "docs" / "USAGE.md"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen_usage():
    return load(ROOT / "scripts" / "gen_usage.py", "gen_usage")


def test_the_committed_usage_guide_matches_the_code(gen_usage):
    assert USAGE.exists(), "run `uv run python scripts/gen_usage.py`"
    assert USAGE.read_text() == gen_usage.build(), (
        "docs/USAGE.md is out of date; run `uv run python scripts/gen_usage.py`"
    )


def test_the_drift_check_passes_on_the_committed_file(gen_usage):
    assert gen_usage.main(["--check"]) == 0


def test_the_usage_guide_documents_every_tool_and_command(gen_usage):
    text = USAGE.read_text()
    for tool in ("browser_open", "browser_run", "browser_search", "browser_extract", "browser_close"):
        assert f"### `{tool}`" in text
    for command in ("run", "search", "observe", "doctor", "bench"):
        assert re.search(rf"^    {command}\b", text, re.MULTILINE)
    assert "| `values` | object[str] \\| none | no | - |" in text


def known_tools(gen_usage):
    import asyncio

    return {tool.name for tool in asyncio.run(gen_usage.tools())}


@pytest.mark.parametrize("name", ["claude_code_search.md", "codex_form_fill.md"])
def test_the_walkthroughs_only_use_tools_and_commands_that_exist(name, gen_usage):
    text = (EXAMPLES / name).read_text()
    used = set(re.findall(r"\b(browser_\w+)\(", text))
    assert used
    assert used <= known_tools(gen_usage)
    assert "uvx jev-ra install" in text


def test_the_install_commands_in_the_walkthroughs_match_what_install_would_run():
    from jev_ra import config
    from jev_ra.cli import install_argv, install_display

    resolved = config.load({"OPENROUTER_API_KEY": "sk-or-v1-x"})
    for agent, name in (("claude", "claude_code_search.md"), ("codex", "codex_form_fill.md")):
        argv = install_argv(agent, "user", resolved, which=lambda binary: None if binary == "jev-ra" else "/bin/x")
        assert install_display(argv, resolved.key_variable) in (EXAMPLES / name).read_text()


@pytest.mark.browser
def test_the_python_api_example_runs_against_the_fixtures():
    example = load(EXAMPLES / "python_api.py", "python_api")
    result = example.on_fixtures()
    assert result.status == "done"
    assert [step["operation"] for step in result.steps] == ["TYPE_TEXT", "TYPE_TEXT", "SELECT", "CLICK"]
    assert [step["text"] for step in result.steps[:2]] == ["Ada Lovelace", "ada@example.com"]
    assert result.text_calls == []
    assert "Order confirmed" in result.final_page["text"]


@pytest.mark.browser
def test_the_python_api_example_exits_zero_from_the_command_line():
    example = load(EXAMPLES / "python_api.py", "python_api_cli")
    assert example.main(["--fixtures"]) == 0


def test_the_usage_guide_does_not_depend_on_the_terminal_it_was_generated_in(gen_usage, monkeypatch):
    monkeypatch.setenv("COLUMNS", "40")
    narrow = gen_usage.build()
    monkeypatch.setenv("COLUMNS", "200")
    wide = gen_usage.build()
    monkeypatch.delenv("COLUMNS")
    bare = gen_usage.build()
    assert narrow == wide == bare


def test_the_help_is_rendered_at_the_width_the_generator_fixes(gen_usage):
    assert gen_usage.cli_help(width=40) != gen_usage.cli_help(width=120)
    assert max(len(line) for line in gen_usage.cli_help().splitlines()) <= gen_usage.HELP_WIDTH
