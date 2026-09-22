"""Run one corpus task many times on one session and report what drifted.

A single run says whether a task passed. The tenth run on the same Chrome says whether the task
still passes after the session has been used: a page that only works on a fresh profile, a decision
that needs the run to be new, a session that leaks listeners or focus. This runs the same task N
times on one `Session`, classifies every attempt the way the corpus does, and exits 1 if any attempt
raised.

The same session can be soaked with calls instead of a task: `--calls 100` makes 100 tool calls
and reports the process's RSS growth and whether any page target was opened along the way.

Usage:
    uv run python scripts/soak.py --task wikipedia_godel --runs 10
    uv run python scripts/soak.py --calls 100
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import resource
except ImportError:
    resource = None

from jev_ra.agent import Agent
from jev_ra.bench import percentile
from jev_ra.browser.session import Session
from jev_ra.config import load
from jev_ra.corpus import TEXT_CHARS, classify, load_tasks
from jev_ra.decide.client import DecisionClient

RSS_LIMIT_MB = 50.0


def task_named(name, tasks=None):
    """The corpus task with this name, or a SystemExit naming what lists the names."""
    for task in tasks if tasks is not None else load_tasks():
        if task.name == name:
            return task
    raise SystemExit(f"unknown corpus task {name!r}; run `uv run jev-ra corpus run --list`")


def run_once(task, session, config, decide):
    """One attempt at the task on an existing session, classified the way the corpus classifies."""
    started = time.perf_counter()
    row = {"task": task.name, "family": task.family}
    try:
        agent = Agent(session=session, config=config, decide=decide)
        result = agent.run(task.goal, values=task.values, max_steps=task.max_steps, url=task.url)
    except Exception as error:
        row.update(
            status="raised",
            reason=type(error).__name__,
            raised=type(error).__name__,
            decisions=0,
            cost=0.0,
            url=task.url,
            site_error=False,
            text="",
            elements=[],
        )
    else:
        row.update(
            status=result.status,
            reason=result.reason,
            decisions=result.decisions,
            cost=result.cost,
            url=result.url,
            site_error=result.site_error,
            text=(result.final_page.get("text") or "")[:TEXT_CHARS],
            elements=result.final_page.get("elements") or [],
        )
    row["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    row["passed"], row["why"] = classify(task, row)
    return row


def summarise(rows):
    """Pass count, seconds, decisions and the reasons seen, over the attempts of one task soak."""
    passed = [row for row in rows if row["passed"]]
    times = [row["elapsed_ms"] for row in rows]
    decisions = [row["decisions"] for row in rows]
    reasons = {}
    for row in rows:
        if row["passed"]:
            continue
        key = row.get("raised") or row.get("reason") or row["status"]
        reasons[key] = reasons.get(key, 0) + 1
    return {
        "runs": len(rows),
        "passed": len(passed),
        "median_s": round(statistics.median(times) / 1000, 2) if times else None,
        "p95_s": round(percentile(times, 0.95) / 1000, 2) if times else None,
        "decisions_median": round(statistics.median(decisions)) if decisions else None,
        "decisions_total": sum(decisions),
        "reasons": dict(sorted(reasons.items(), key=lambda item: item[1], reverse=True)),
        "raised": sum(1 for row in rows if row.get("raised")),
        "site_error": sum(1 for row in rows if row.get("site_error")),
    }


def report(summary, name):
    """The task soak as printable lines."""
    lines = [f"soak {name}: {summary['runs']} run(s) on one session"]
    lines.append(f"  passed {summary['passed']}/{summary['runs']}")
    lines.append(f"  seconds: median {summary['median_s']}, p95 {summary['p95_s']}")
    lines.append(f"  decisions: median {summary['decisions_median']}, total {summary['decisions_total']}")
    lines.append("  reasons: " + (", ".join(f"{key} x{value}" for key, value in summary["reasons"].items()) or "none"))
    lines.append(f"  site errors: {summary['site_error']}")
    lines.append(f"  raised: {summary['raised']}")
    return lines


def rss_bytes():
    """This process's peak resident set in bytes, or None where the platform will not say.

    Peak memory only ever climbs, so growth in the peak is the conservative version of growth in
    what the process holds right now: under the limit there is under it here.
    """
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage if sys.platform == "darwin" else usage * 1024


def page_targets():
    """How many page targets the daemon behind this session can see."""
    from browser_harness.helpers import cdp

    infos = cdp("Target.getTargets").get("targetInfos") or []
    return sum(1 for info in infos if info.get("type") == "page")


def calls_summary(calls, before_rss, after_rss, before_tabs, after_tabs, limit_mb=RSS_LIMIT_MB):
    """The leak arithmetic of one calls soak: RSS growth, tabs, and whether either check failed."""
    growth_mb = None if before_rss is None or after_rss is None else round((after_rss - before_rss) / 1e6, 2)
    return {
        "calls": calls,
        "rss_growth_mb": growth_mb,
        "limit_mb": limit_mb,
        "tabs_before": before_tabs,
        "tabs_after": after_tabs,
        "leaked": (growth_mb is not None and growth_mb > limit_mb) or after_tabs > before_tabs,
    }


def soak_calls(session, calls):
    """N tool calls on one session, with RSS and page targets measured around them."""
    before_rss, before_tabs = rss_bytes(), page_targets()
    for _ in range(calls):
        session.observe()
    return calls_summary(calls, before_rss, rss_bytes(), before_tabs, page_targets())


def calls_report(summary):
    """The calls soak as printable lines."""
    growth = "unmeasurable on this platform" if summary["rss_growth_mb"] is None else f"{summary['rss_growth_mb']} MB"
    return [
        f"soak calls: {summary['calls']} tool call(s) on one session",
        f"  rss growth: {growth} (limit {summary['limit_mb']} MB)",
        f"  tabs: {summary['tabs_before']} before, {summary['tabs_after']} after",
    ]


def task_soak(name, runs):
    """Soak one corpus task and return 1 when an attempt raised."""
    task = task_named(name)
    config = load()
    if not config.api_key:
        raise SystemExit("The soak runs against the live web and needs a Jev key.")
    client = DecisionClient(config)
    session = Session(config)
    try:
        rows = [run_once(task, session, config, client.decide) for _ in range(runs)]
    finally:
        session.close()
        client.close()
    summary = summarise(rows)
    print("\n".join(report(summary, task.name)))
    return 1 if summary["raised"] else 0


def calls_soak(calls):
    """Soak one session with tool calls and return 1 when memory or tabs leaked."""
    session = Session(load())
    try:
        summary = soak_calls(session, calls)
    finally:
        session.close()
    print("\n".join(calls_report(summary)))
    return 1 if summary["leaked"] else 0


def main(argv=None):
    """Soak a task or a session, whichever the arguments ask for."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", help="a corpus task name, such as wikipedia_godel")
    parser.add_argument("--runs", type=int, default=10, help="how many attempts on the one session (default 10)")
    parser.add_argument("--calls", type=int, help="instead of a task: this many tool calls on one session")
    arguments = parser.parse_args(argv)
    if arguments.calls is not None:
        return calls_soak(arguments.calls)
    if arguments.task is None:
        parser.error("--task <id> or --calls <n> is required")
    return task_soak(arguments.task, arguments.runs)


if __name__ == "__main__":
    raise SystemExit(main())
