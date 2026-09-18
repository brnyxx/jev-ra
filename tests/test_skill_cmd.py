"""`jev-ra skill` hands an agent the guide, and the guide's commands have to be real."""

import json
import re
from pathlib import Path

import pytest

from jev_ra import cli

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
AGENT_INSTALL = ROOT / "docs" / "AGENT_INSTALL.md"


def commands_in(text):
    """Every shell line inside a fenced block, minus comments and continuations."""
    found = []
    for block in re.findall(r"```sh\n(.*?)```", text, re.DOTALL):
        joined = block.replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.split("#")[0].strip()
            if line:
                found.append(line)
    return found


def subcommands():
    parser = cli.build_parser()
    actions = [action for action in parser._subparsers._group_actions if hasattr(action, "choices")]
    return set(actions[0].choices)


def test_skill_prints_agents_md_byte_for_byte(capsys):
    assert cli.main(["skill"]) == 0
    assert capsys.readouterr().out == AGENTS.read_text()


def test_skill_json_carries_the_same_text(capsys):
    assert cli.main(["skill", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "jev-ra"
    assert payload["text"] == AGENTS.read_text()


def test_the_guide_travels_with_the_wheel():
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    included = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert included["AGENTS.md"] == "jev_ra/AGENTS.md"


@pytest.mark.parametrize("path", [AGENTS, AGENT_INSTALL])
def test_every_jev_ra_command_in_the_guide_is_a_real_subcommand(path):
    known = subcommands()
    seen = 0
    for line in commands_in(path.read_text()):
        match = re.match(r"^(?:uvx |uv run |npx -y )?jev-ra(?:@[\w.]+)? (\w[\w-]*)", line)
        if not match:
            continue
        seen += 1
        assert match.group(1) in known, f"{path.name} uses `jev-ra {match.group(1)}`, which does not exist"
    assert seen >= 3, f"{path.name} shows no jev-ra commands at all"


def test_the_guide_only_names_tools_the_server_has():
    import asyncio

    from mcp import Client

    from jev_ra.mcp_server import build_server

    async def listing():
        async with Client(build_server()) as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    known = asyncio.run(listing())
    for path in (AGENTS, AGENT_INSTALL):
        used = set(re.findall(r"\b(browser_\w+)", path.read_text()))
        assert used <= known, f"{path.name} names {sorted(used - known)}"


def test_the_guide_never_tells_an_agent_to_print_the_key():
    text = AGENTS.read_text()
    assert "Never print the key" in text
    assert "sk-or-" not in text.replace("`OPENROUTER_API_KEY`", "")


def test_the_install_guide_covers_every_host_the_guide_claims():
    text = AGENT_INSTALL.read_text()
    for host in ("Claude Code", "Codex", "Cursor", "Cline", "Devin"):
        assert f"## {host}" in text or host in text
    assert "jev-ra skill >" in text
