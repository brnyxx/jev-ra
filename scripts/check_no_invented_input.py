"""Fail a corpus results file whose runs typed text the task never supplied.

The core contract of a run is that every string that reaches a page came from the host agent's
`values`, never from the model. The corpus runner writes one row per attempt to
`corpus/results/<date>.jsonl` with the steps it took, and each step records the operation and the
text it typed. This reads that file and fails any TYPE_TEXT step whose text is not one of the
task's values, and any row whose steps cannot be read at all - a row that proves nothing is not
a row that proves the contract held.

Usage: uv run python scripts/check_no_invented_input.py corpus/results/2026-09-22.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_ra.corpus import load_tasks

TYPED = "TYPE_TEXT"


def tasks_by_name():
    """Every corpus task, keyed by name."""
    return {task.name: task for task in load_tasks()}


def read_rows(path):
    """The rows in a jsonl file, and a fault for every line that is not a JSON object."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        return [], [f"{path} is unreadable: {error}"]
    rows, found = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            found.append(f"{path}:{number} is not JSON ({error})")
            continue
        if not isinstance(row, dict):
            found.append(f"{path}:{number} is not a JSON object")
            continue
        rows.append(row)
    return rows, found


def row_faults(row, tasks, where):
    """Every way one row cannot vouch for its typed input."""
    name = row.get("task") or "?"
    task = tasks.get(name)
    if task is None:
        return [f"{where}: {name} is not a task in corpus/sites.toml, so its input cannot be checked"]
    if "trace" not in row:
        return [f"{where}: {name} carries no step trace, so what it typed cannot be checked"]
    supplied = sorted({value for value in task.values.values()})
    found = []
    for number, step in enumerate(row["trace"] or [], 1):
        if not isinstance(step, dict) or step.get("operation") != TYPED:
            continue
        text = step.get("text")
        if text not in supplied:
            found.append(f"{where}: {name} step {number} typed {text!r}, which is not one of the values it was given")
    return found


def faults(rows, tasks):
    """Every unverifiable row and every typed string that is not one of the task's values."""
    found = []
    for number, row in enumerate(rows, 1):
        found += row_faults(row, tasks, f"row {number}")
    return found


def typed_steps(rows):
    """How many TYPE_TEXT steps the rows hold, so a clean file says how much it proved."""
    return sum(
        1
        for row in rows
        for step in row.get("trace") or []
        if isinstance(step, dict) and step.get("operation") == TYPED
    )


def main(argv=None):
    """Check one results file and return 0 when every typed string was supplied."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="a corpus results jsonl, such as corpus/results/2026-09-22.jsonl")
    arguments = parser.parse_args(argv)
    rows, found = read_rows(arguments.path)
    found += faults(rows, tasks_by_name())
    for problem in found:
        print(problem, file=sys.stderr)
    verdict = "FAIL" if found else "PASS"
    counted = f"{len(rows)} row(s), {typed_steps(rows)} TYPE_TEXT step(s), {len(found)} fault(s)"
    print(f"{verdict}: {arguments.path}: {counted}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
