"""The README's command table, checked against the parser that defines the commands."""

import re
from pathlib import Path

from jev_ra import cli

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
