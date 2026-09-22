"""Say what one corpus site answers this machine: its status, where it lands, and whether it walls.

A corpus task that fails says the site answered something other than the page, and `corpus/egress.md`
is where each answer is recorded. This is how one row is measured: it opens the address once, the
way a corpus run opens it, and reports the main document's HTTP status, the address the open landed
on, the Agent's own wall verdict, and how much the page offered. The wall check is the Agent's, not
a copy of it: the first decision is scripted to finish, so the run stops after the page it opened.

Usage:
    uv run python scripts/check_site.py gov_kr_search
    uv run python scripts/check_site.py https://www.coupang.com/
"""

import argparse
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_ra.agent import Agent
from jev_ra.browser.session import Session
from jev_ra.config import load
from jev_ra.corpus import load_tasks
from jev_ra.decide import Reply
from jev_ra.errors import JevRaError, render

HTTP_STATUS_JS = "performance.getEntriesByType('navigation')[0]?.responseStatus ?? null"


def task_named(name, tasks=None):
    """The corpus task with this name, or a SystemExit naming what lists the names."""
    for task in tasks if tasks is not None else load_tasks():
        if task.name == name:
            return task
    raise SystemExit(f"unknown corpus task {name!r}; run `uv run jev-ra corpus run --list`")


def address(argument, tasks=None):
    """The label and url to check: a corpus task's address, or a url given directly."""
    if "://" in argument:
        return argument, argument
    task = task_named(argument, tasks)
    return task.name, task.url


def scripted_decide(_state, _questions):
    """Finish the run immediately: this check reads the page it opened, not the goal."""
    answers = {"operation": {"choice": "DONE", "confidence": 1.0, "probabilities": {"DONE": 1.0}}}
    return Reply(answers={**answers, "goal_achieved": {"noul": 1.0}}, model="check_site", latency_ms=0)


def open_once(url, session=None, config=None):
    """Open one address and report what the site answered, with the Agent's wall verdict."""
    own = session is None
    config = config or load()
    session = session or Session(config)
    try:
        agent = Agent(session=session, config=config, decide=scripted_decide, prefetch=False)
        result = agent.run("Check what this site answers.", max_steps=1, url=url)
        status = session.evaluate(HTTP_STATUS_JS)
        return {
            "requested": url,
            "url": result.url,
            "status": status if isinstance(status, int) else None,
            "wall": result.detail.get("wall", "") if result.reason == "blocked_by_site" else "",
            "chars": len(result.final_page.get("text") or ""),
            "controls": len(result.final_page.get("elements") or []),
        }
    finally:
        if own:
            session.close()


def report(label, row):
    """The check as printable lines."""
    return [
        f"{label}: {row['requested']}",
        f"  status: {row['status'] if row['status'] is not None else 'unknown'}",
        f"  landed on: {row['url']}",
        f"  wall: {row['wall'] or 'none'}",
        f"  page: {row['chars']} chars, {row['controls']} controls",
    ]


def main(argv=None):
    """Check one address and return 0 when it was opened, walled or not."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("address", help="a corpus task name or a url")
    arguments = parser.parse_args(argv)
    label, url = address(arguments.address)
    try:
        row = open_once(url)
    except JevRaError as error:
        print(f"{label}: {render(error)}", file=sys.stderr)
        return 1
    print("\n".join(report(label, row)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
