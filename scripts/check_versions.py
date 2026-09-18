"""Check that every version in the repository agrees, and optionally that a tag matches them.

`uv run python scripts/check_versions.py` compares the four places a version is written down;
`--tag v0.1.0` adds the tag to that comparison.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED = re.compile(r'^export const PINNED = "([^"]+)";$', re.MULTILINE)


def versions():
    """Where a version is written down, and what it says."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    package = json.loads((ROOT / "npm" / "package.json").read_text())["version"]
    launcher = PINNED.search((ROOT / "npm" / "bin" / "jev-ra.js").read_text())
    module = re.search(r'^__version__ = "([^"]+)"$', (ROOT / "jev_ra" / "__init__.py").read_text(), re.MULTILINE)
    return {
        "pyproject.toml": pyproject,
        "npm/package.json": package,
        "npm/bin/jev-ra.js": launcher.group(1) if launcher else None,
        "jev_ra/__init__.py": module.group(1) if module else None,
    }


def disagreements(found, tag=None):
    """Every place whose version differs from pyproject's, plus the tag when one is given."""
    expected = found["pyproject.toml"]
    wrong = [f"{where}: {value}" for where, value in found.items() if value != expected]
    if tag is not None and tag.removeprefix("v") != expected:
        wrong.append(f"tag: {tag}")
    return wrong, expected


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check_versions", description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="a git tag such as v0.1.0; checked against the package version")
    args = parser.parse_args(argv)
    found = versions()
    wrong, expected = disagreements(found, args.tag)
    if wrong:
        print(f"version mismatch, pyproject.toml says {expected}:", file=sys.stderr)
        for line in wrong:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"version {expected} agrees in {', '.join(found)}" + (f" and tag {args.tag}" if args.tag else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
