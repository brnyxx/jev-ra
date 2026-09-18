"""Check that the demo the landing page replays is the run that was actually recorded.

`docs/assets-site/demo-run.json` is what the page loads; the run it came from lives under
`docs/benchmarks/`. If they drift, the page animates something that never happened. Run with
`--check` in CI; without it, the same report is printed and the exit code still says whether it
passed.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVED = ROOT / "docs" / "assets-site" / "demo-run.json"
RECORDED = ROOT / "docs" / "benchmarks" / "2026-09-18-v0.1" / "demo-run-flights.json"


def shown(path):
    """The path as the repository spells it, or in full when it lies outside."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def problems(served=SERVED, recorded=RECORDED):
    """Everything that stops the served demo from being the recorded run."""
    found = [shown(path) + " is missing" for path in (served, recorded) if not path.exists()]
    if found:
        return found
    try:
        one, two = json.loads(served.read_text()), json.loads(recorded.read_text())
    except json.JSONDecodeError as error:
        return [f"{error}"]
    if one != two:
        found.append(
            f"{shown(served)} is not the run recorded in {shown(recorded)}; "
            "copy the recorded file over it rather than editing either by hand"
        )
    return found


def main(argv=None):
    """Report and return 0 when the served demo matches the recorded run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit non-zero on any difference")
    parser.parse_args(argv)
    found = problems()
    for line in found:
        print(line, file=sys.stderr)
    if not found:
        print(f"{shown(SERVED)}: the recorded run, unchanged")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
