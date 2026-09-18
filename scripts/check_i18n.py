"""Check that every translated README still matches the English one.

Structure, commands and numbers must agree; the prose is expected to differ. Run with `--check`
in CI; without it, the same report is printed and the exit code still says whether it passed.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGLISH = ROOT / "README.md"
TRANSLATIONS = ("docs/i18n/README.ko.md", "docs/i18n/README.ja.md", "docs/i18n/README.zh-CN.md")
# Thousands separators, dollar amounts, and ratios written with the multiplication sign.
TIMES = "\u00d7"
NUMBER = re.compile(rf"\b\d{{1,3}}(?:,\d{{3}})+|\$\d+\.\d{{4,}}|\b\d+\.\d{{1,2}}{TIMES}")


def headings(text):
    return re.findall(r"^## (.+)$", text, re.MULTILINE)


def commands(text):
    """Every shell line inside a fenced sh block, which must be identical in every language."""
    found = []
    for block in re.findall(r"```sh\n(.*?)```", text, re.DOTALL):
        for line in block.splitlines():
            stripped = line.split("#")[0].strip()
            if stripped:
                found.append(stripped)
    return found


def numbers(text):
    return sorted(set(NUMBER.findall(text)))


def compare(english, other):
    """Everything that must match between the English README and a translation."""
    problems = []
    if len(headings(english)) != len(headings(other)):
        problems.append(f"{len(headings(other))} sections against {len(headings(english))} in English")
    if commands(english) != commands(other):
        missing = [line for line in commands(english) if line not in commands(other)]
        extra = [line for line in commands(other) if line not in commands(english)]
        if missing:
            problems.append(f"missing commands: {missing}")
        if extra:
            problems.append(f"commands that are not in the English README: {extra}")
    if numbers(english) != numbers(other):
        missing = [item for item in numbers(english) if item not in numbers(other)]
        extra = [item for item in numbers(other) if item not in numbers(english)]
        if missing:
            problems.append(f"missing numbers: {missing}")
        if extra:
            problems.append(f"numbers that are not in the English README: {extra}")
    return problems


def report(paths=TRANSLATIONS):
    """One (path, problems) pair per translation."""
    english = ENGLISH.read_text()
    return [(name, compare(english, (ROOT / name).read_text())) for name in paths]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check_i18n", description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="kept for symmetry; the exit code always says")
    parser.parse_args(argv)
    failed = False
    for name, problems in report():
        if problems:
            failed = True
            print(f"{name}:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
        else:
            print(f"{name}: in sync with README.md")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
