"""The README's tables, checked against the code they describe."""

import re
from pathlib import Path

from jev_ra import cli, config

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def section(text, title):
    start = text.index(f"## {title}")
    tail = text[start:]
    end = tail.find("\n## ", 1)
    return tail if end == -1 else tail[:end]


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
