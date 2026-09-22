"""Review every corpus task's verify spec against the goal it is supposed to prove.

A verify spec is the only thing standing between "the run finished" and "the run did the task",
and it drifts in two directions. Too tight, and a run that did the job is recorded as a failure:
two Seoul rows failed on a url the goal never asked for. Too loose, and a run that did nothing is
recorded as a pass, which is worse, because nobody goes looking for it.

Printed, this is the review surface: goal and spec side by side, one task at a time, for a human
to read before a corpus run is believed. With `--check` it is also a gate, and it fails only on
specs that cannot do their job at all - an outcome with nothing to prove it, a spec that is never
consulted, a key that is silently ignored, or a check the task's own starting page already
satisfies.
"""

import argparse
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_ra.corpus import SITES, VERIFY_KEYS, load_tasks

WIDTH = 96


def rendered(spec):
    """One verify spec as a line, in declaration order."""
    return "  ".join(f"{key}={value!r}" for key, value in spec.items()) if spec else "-"


def wrapped(label, value):
    """One labelled line, folded so a long goal stays readable next to its spec."""
    room = WIDTH - 10
    body = str(value)
    lines, current = [], ""
    for word in body.split():
        if current and len(current) + 1 + len(word) > room:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    lines.append(current)
    return "\n".join(f"  {label if index == 0 else '':<8}{line}" for index, line in enumerate(lines))


def faults(task):
    """Everything that stops this task's spec from proving its goal."""
    found = []
    expect = task.expect
    if expect not in {"done", "blocked"} and not expect.startswith("escalate:"):
        found.append(f"expect is {expect!r}, not done, blocked or escalate:<reason>")
    unknown = sorted(set(task.verify) - set(VERIFY_KEYS))
    if unknown:
        found.append(f"verify keys {unknown} are not read by the checker, so they prove nothing")
    if expect == "done" and not task.verify:
        found.append("expect is done with no verify spec, so any finished run passes")
    if expect != "done" and task.verify:
        found.append("verify is never consulted for an outcome other than done")
    for needle in task.verify.get("url_contains", []):
        if needle.lower() in task.url.lower():
            found.append(f"url_contains {needle!r} is already true of the starting address")
    return found


def review(tasks=None):
    """Every task's goal beside its spec, and the faults found across all of them."""
    tasks = tasks if tasks is not None else load_tasks()
    lines, found = [], []
    for task in tasks:
        problems = faults(task)
        found += [f"{task.name}: {problem}" for problem in problems]
        lines.append(f"{task.family}/{task.name}")
        lines.append(wrapped("goal", task.goal))
        lines.append(wrapped("expect", task.expect))
        lines.append(wrapped("verify", rendered(task.verify)))
        for problem in problems:
            lines.append(wrapped("FAULT", problem))
        lines.append("")
    return lines, found


def main(argv=None):
    """Print the review and return 0 when every spec can prove its own goal."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="print only the faults and exit non-zero on any")
    arguments = parser.parse_args(argv)
    tasks = load_tasks()
    lines, found = review(tasks)
    if not arguments.check:
        print("\n".join(lines))
    for problem in found:
        print(problem, file=sys.stderr)
    if not found:
        print(f"{SITES.name}: {len(tasks)} tasks, every spec proves its own goal")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
