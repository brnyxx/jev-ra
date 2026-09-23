"""Where a step's time goes, measured rather than guessed.

Six categories, and they add up: `snapshot_ms` is the CDP evaluate that reads the page,
`actions_ms` is the Python that turns it into an action space and a question set, `decide_ms` is the
HTTP round trip to Jev, `act_ms` is the CDP input, `wait_ms` is the post-action settle, and
`overhead_ms` is whatever is left of the step, which is Python doing everything else.
"""

import time
from contextlib import contextmanager

MEASURED = ("snapshot_ms", "actions_ms", "decide_ms", "act_ms", "wait_ms")
CATEGORIES = (*MEASURED, "overhead_ms")
LABEL_CHARS = 28
COLUMNS = ("n", "operation", "target", *(name[:-3] for name in CATEGORIES), "total")


class StepTimer:
    """Accumulates time per category for one step. Overhead is the remainder, never a measurement."""

    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.started = clock()
        self.spent = dict.fromkeys(MEASURED, 0.0)

    @contextmanager
    def measure(self, category):
        """Charge everything inside the block to one category."""
        key = f"{category}_ms"
        if key not in self.spent:
            raise KeyError(f"{category} is not one of {', '.join(name[:-3] for name in MEASURED)}")
        started = self.clock()
        try:
            yield
        finally:
            self.spent[key] += (self.clock() - started) * 1000

    def add(self, category, milliseconds):
        """Charge a duration something else already measured, such as a decision's own latency."""
        self.spent[f"{category}_ms"] += milliseconds

    def result(self):
        """The per-category milliseconds plus the step total, rounded, and adding up to it."""
        total = (self.clock() - self.started) * 1000
        measured = {name: round(value) for name, value in self.spent.items()}
        # Rounding the parts and then subtracting keeps the categories summing to the total exactly.
        return {**measured, "overhead_ms": max(0, round(total) - sum(measured.values())), "total_ms": round(total)}


class NullTimer:
    """A timer for the paths that do not profile: same interface, no bookkeeping."""

    @contextmanager
    def measure(self, _category):
        """Charge nothing and get out of the way."""
        yield

    def add(self, _category, _milliseconds):
        """Charge nothing."""
        return None

    def result(self):
        """Zeros, so a caller can merge them without checking."""
        return dict.fromkeys((*CATEGORIES, "total_ms"), 0)


def clip(text, limit):
    """One line of at most `limit` characters, with an ellipsis where it was cut."""
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def rows(payload):
    """One row per step: what it was, and the milliseconds each part of it took."""
    return [
        {
            "n": str(step.get("n", "")),
            "operation": step.get("operation", ""),
            "target": clip(step.get("target_label") or step.get("target"), LABEL_CHARS),
            **{name[:-3]: str(step.get(name) or 0) for name in CATEGORIES},
            "total": str(step.get("total_ms") or 0),
        }
        for step in payload.get("steps", [])
    ]


def table(payload):
    """Where one run's time went, step by step, as lines a terminal prints."""
    steps = payload.get("steps") or []
    body = rows(payload)
    summed = totals(steps)
    inside = sum(step.get("total_ms") or 0 for step in steps)
    body.append(
        {
            "n": "",
            "operation": "total",
            "target": f"{len(steps)} step{'' if len(steps) == 1 else 's'}",
            **{name[:-3]: str(summed[name]) for name in CATEGORIES},
            "total": str(inside),
        }
    )
    widths = {name: max(len(name), *(len(row[name]) for row in body)) for name in COLUMNS}
    header = "  ".join(name.ljust(widths[name]) for name in COLUMNS)
    lines = [
        f"run {payload.get('run_id', '')} · {payload.get('status', '')} · {payload.get('reason', '')}",
        "",
        header,
        "-" * len(header),
    ]
    lines += ["  ".join(row[name].ljust(widths[name]) for name in COLUMNS) for row in body]
    wall = payload.get("elapsed_ms", 0)
    outside = max(0, wall - inside)
    lines += ["", f"{wall} ms in the run, {outside} ms of it outside the steps (the first page, and the last)"]
    if payload.get("human_wait_ms"):
        lines.append(f"{payload['human_wait_ms']} ms of the run was waiting for a person to clear a check")
    prefetched = sum(1 for step in steps if step.get("prefetched"))
    if payload.get("speculations"):
        lines.append(f"{prefetched} of {payload['speculations']} decisions were ready before the page was")
    return lines


def totals(steps):
    """Sum every category across a run's steps."""
    summed = dict.fromkeys(CATEGORIES, 0)
    for step in steps:
        for name in CATEGORIES:
            summed[name] += step.get(name) or 0
    return summed


def shares(steps, wall_ms):
    """Each category as a share of wall time, plus what no step accounted for."""
    summed = totals(steps)
    attributed = sum(summed.values())
    rows = [
        {"category": name[:-3], "ms": value, "share": round(value / wall_ms, 4) if wall_ms else None}
        for name, value in summed.items()
    ]
    rows.append(
        {
            "category": "outside steps",
            "ms": max(0, wall_ms - attributed),
            "share": round(max(0, wall_ms - attributed) / wall_ms, 4) if wall_ms else None,
        }
    )
    return rows
