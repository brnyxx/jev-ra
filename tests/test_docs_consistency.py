"""The README's tables of reasons, commands and variables, checked against the code."""

import ast
import re
from pathlib import Path

from jev_ra import cli, config

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"
AGENT = ROOT / "jev_ra" / "agent.py"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
RUNBOOK = ROOT / "docs" / "RELEASING.md"


def section(text, title):
    start = text.index(f"## {title}")
    tail = text[start:]
    end = tail.find("\n## ", 1)
    return tail if end == -1 else tail[:end]


def escalation_reasons():
    tree = ast.parse(AGENT.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "escalate":
            for argument in node.args[:1]:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.add(argument.value)
        if isinstance(node, ast.FunctionDef) and node.name == "stuck":
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and child.value is not None:
                    for constant in ast.walk(child.value):
                        if isinstance(constant, ast.Constant) and isinstance(constant.value, str):
                            found.add(constant.value)
    return found


def readme_reasons():
    text = " ".join(section(README.read_text(), "When it hands control back").split())
    match = re.search(r"`reason` is one of ([^.]+)\.", text)
    assert match, "the README no longer lists the escalation reasons in the documented sentence"
    return set(re.findall(r"`([a-z_]+)`", match.group(1)))


def test_the_readme_lists_every_escalation_reason():
    assert readme_reasons() == escalation_reasons()


def agents_reasons():
    table = section(AGENTS.read_text(), "When it escalates")
    return set(re.findall(r"^\| `([a-z_]+)` \|", table, re.MULTILINE))


def test_the_agent_guide_covers_every_escalation_reason():
    assert escalation_reasons() <= agents_reasons()


def parser_commands():
    parser = cli.build_parser()
    actions = [action for action in parser._subparsers._group_actions if hasattr(action, "choices")]
    return {choice.dest: choice.help for choice in actions[0]._choices_actions}


def readme_commands():
    rows = {}
    for line in section(README.read_text(), "CLI").splitlines():
        match = re.match(r"^\| `([\w-]+)", line)
        if match:
            cells = re.split(r"(?<!\\)\|", line)
            rows[match.group(1)] = cells[2].strip()
    return rows


def test_the_readme_lists_every_cli_command_with_its_help():
    assert readme_commands() == parser_commands()


def readme_environment_names():
    names = set()
    for line in section(README.read_text(), "Configuration").splitlines():
        cells = re.split(r"(?<!\\)\|", line)
        if len(cells) >= 3:
            names |= set(re.findall(r"`([A-Z][A-Z0-9_]*)`", cells[1]))
    return names


def source_environment_names():
    names = set()
    for path in (ROOT / "jev_ra").rglob("*.py"):
        text = path.read_text()
        names |= set(re.findall(r"\bJEV_RA_[A-Z_]+\b", text))
        names |= set(re.findall(r"\bBU_CDP_URL\b", text))
    return names


def test_the_readme_environment_table_matches_the_config():
    assert readme_environment_names() == set(config.ENV_VARIABLES)
    assert source_environment_names() <= set(config.ENV_VARIABLES)


def test_the_release_runbook_names_the_workflow_and_its_environments():
    workflow = RELEASE.read_text()
    runbook = RUNBOOK.read_text()
    assert f"`{RELEASE.name}`" in runbook
    environments = re.findall(r"^\s+environment: (\S+)$", workflow, re.MULTILINE)
    assert environments
    assert all(f"`{name}`" in runbook for name in environments)
