"""The real-site corpus: run declared tasks against the live web and classify every outcome.

Tasks live in `corpus/sites.toml` so the loader needs nothing but the standard library. Each task
declares what it wants to happen (`expect`) and how to tell from the page that it did (`verify`),
because a run that finishes fast without doing the task is a failure, not a time.
"""

import json
import logging
import statistics
import time
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .agent import Agent
from .bench import markdown_table
from .browser.session import Session
from .config import load
from .decide.client import DecisionClient
from .errors import JevRaError

logger = logging.getLogger(__name__)

__all__ = [
    "PASS_RATE",
    "VERIFY_KEYS",
    "Task",
    "check",
    "classify",
    "families",
    "load_tasks",
    "markdown_table",
    "pass_rate",
    "reasons",
    "run",
    "run_task",
    "summarise",
    "write_results",
]

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "corpus" / "sites.toml"
RESULTS = ROOT / "corpus" / "results"
TEXT_CHARS = 6000
PASS_RATE = 0.9
ACTIVE = {"true", "page", "step", "on"}
QUOTES = "\u2018\u2019\u201a\u201b\u2032\u201c\u201d\u201e\u201f\u2033"
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2212"
SPACES = "\u00a0\u202f\u2009"
TYPESET = str.maketrans(QUOTES + DASHES + SPACES, "'" * 5 + '"' * 5 + "-" * 6 + " " * 3)
# Every key `check` reads. A spec that carries anything else is a typo that proves nothing and
# passes silently, so the review script compares a task's spec against this list.
VERIFY_KEYS = (
    "url_contains",
    "url_not_contains",
    "text_contains",
    "text_any",
    "label_any",
    "active_label",
    "min_text",
)


@dataclass(frozen=True)
class Task:
    """One declared task: where to go, what to achieve, and how the page proves it."""

    name: str
    family: str
    url: str
    goal: str
    expect: str = "done"
    values: dict = field(default_factory=dict)
    verify: dict = field(default_factory=dict)
    max_steps: int = 20

    @property
    def expected_reason(self):
        """The escalation reason this task expects, when it expects one."""
        return self.expect.split(":", 1)[1] if ":" in self.expect else None


def load_tasks(path=None):
    """Every task in the corpus file, in declaration order."""
    data = tomllib.loads(Path(path or SITES).read_text())
    return [Task(**entry) for entry in data.get("task", [])]


def families(tasks):
    """The family names present, in declaration order."""
    seen = []
    for task in tasks:
        if task.family not in seen:
            seen.append(task.family)
    return seen


def typeset(value):
    """A string with typographic punctuation folded back to the characters a spec is typed with."""
    return (value or "").translate(TYPESET)


def check(spec, row):
    """Whether the page satisfies a task's verify spec, and the first thing that failed."""
    url = (row.get("url") or "").lower()
    text = typeset(row.get("text"))
    labels = typeset(" \n".join((element.get("label") or "") for element in row.get("elements") or []))
    for needle in spec.get("url_contains", []):
        if needle.lower() not in url:
            return False, f"url does not contain {needle!r}"
    for needle in spec.get("url_not_contains", []):
        if needle.lower() in url:
            return False, f"url still contains {needle!r}"
    for needle in spec.get("text_contains", []):
        if typeset(needle) not in text:
            return False, f"page text does not contain {needle!r}"
    any_of = spec.get("text_any", [])
    if any_of and not any(typeset(needle) in text for needle in any_of):
        return False, f"page text contains none of {any_of}"
    label_any = spec.get("label_any", [])
    if label_any and not any(typeset(needle) in labels for needle in label_any):
        return False, f"no observed control matches {label_any}"
    if len(text) < spec.get("min_text", 0):
        return False, f"page text is {len(text)} characters, under {spec['min_text']}"
    for label in spec.get("active_label", []):
        if not any(
            typeset(label) in typeset(element.get("label"))
            and any(str(element.get(key, "")).lower() in ACTIVE for key in ("selected", "checked", "expanded"))
            for element in row.get("elements") or []
        ):
            return False, f"{label!r} is not marked active"
    return True, ""


def classify(task, row):
    """Did this run do what the task expected, and if not, what is the shortest true reason."""
    status, reason = row.get("status"), row.get("reason") or ""
    if task.expect.startswith("escalate"):
        wanted = task.expected_reason
        if status not in {"escalate", "blocked"}:
            return False, f"expected escalate:{wanted}, got {status}"
        if wanted and reason != wanted:
            return False, f"expected escalate:{wanted}, got escalate:{reason}"
        return True, ""
    if status != "done":
        return False, f"{status}:{reason}" if reason else status
    return check(task.verify, row)


def step_trace(step):
    """One executed step, as much of it as a results row keeps: what it did and what it typed."""
    return {
        "operation": step.get("operation"),
        "target": step.get("target"),
        "label": step.get("target_label", ""),
        "text": step.get("text"),
    }


def run_task(task, config, decide):
    """One live attempt at one task."""
    session = Session(config)
    started = time.perf_counter()
    try:
        agent = Agent(session=session, config=config, decide=decide)
        result = agent.run(task.goal, values=task.values, max_steps=task.max_steps, url=task.url)
        row = {
            "task": task.name,
            "family": task.family,
            "status": result.status,
            "reason": result.reason,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "steps": len(result.steps),
            "decisions": result.decisions,
            "speculations": result.speculations,
            "prefetched": result.prefetched,
            "text_calls": len(result.text_calls),
            "cost": result.cost,
            "url": result.url,
            "text": (result.final_page.get("text") or "")[:TEXT_CHARS],
            "elements": result.final_page.get("elements") or [],
            "trace": [step_trace(step) for step in result.steps],
        }
    except JevRaError as error:
        row = {
            "task": task.name,
            "family": task.family,
            "status": "error",
            "reason": type(error).__name__,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "steps": 0,
            "decisions": 0,
            "speculations": 0,
            "prefetched": 0,
            "text_calls": 0,
            "cost": 0.0,
            "url": task.url,
            "text": str(error)[:TEXT_CHARS],
            "elements": [],
            "trace": [],
        }
    finally:
        session.close()
    row["passed"], row["why"] = classify(task, row)
    return row


def run(tasks=None, config=None, runs=1, family=None, name=None, decide=None):
    """Run the corpus and return one row per attempt."""
    config = config or load()
    tasks = tasks or load_tasks()
    if family:
        tasks = [task for task in tasks if task.family == family]
    if name:
        tasks = [task for task in tasks if task.name == name]
    if not tasks:
        raise JevRaError("No corpus task matched that selection.")
    if decide is None and not config.api_key:
        raise JevRaError("The corpus runs against the live web and needs a Jev key.")
    client = None
    if decide is None:
        client = DecisionClient(config)
        decide = client.decide
    rows = []
    try:
        for attempt in range(runs):
            for task in tasks:
                logger.info("run %s/%s: %s", attempt + 1, runs, task.name)
                rows.append(run_task(task, config, decide))
    finally:
        if client is not None:
            client.close()
    return rows


def summarise(rows):
    """Per task: how often it passed, how long it took, and why it failed when it did."""
    grouped = {}
    for row in rows:
        grouped.setdefault(row["task"], []).append(row)
    table = []
    for name, attempts in grouped.items():
        good = [row for row in attempts if row["passed"]]
        times = [row["elapsed_ms"] for row in good]
        table.append(
            {
                "task": name,
                "family": attempts[0]["family"],
                "runs": len(attempts),
                "passed": len(good),
                "pass_rate": round(len(good) / len(attempts), 3),
                "median_ms": round(statistics.median(times)) if times else None,
                "decisions": round(statistics.median([row["decisions"] for row in good])) if good else None,
                "cost": round(statistics.median([row["cost"] for row in good]), 6) if good else None,
                "why": sorted({row["why"] for row in attempts if not row["passed"]}),
            }
        )
    return table


def reasons(rows):
    """How often each escalation reason came up, worst first."""
    histogram = {}
    for row in rows:
        if row["passed"]:
            continue
        key = row["why"].split(":")[0] or row["status"]
        histogram[key] = histogram.get(key, 0) + 1
    return dict(sorted(histogram.items(), key=lambda item: item[1], reverse=True))


def pass_rate(rows):
    """The share of attempts that did what their task expected."""
    return round(sum(1 for row in rows if row["passed"]) / len(rows), 4) if rows else 0.0


def write_results(rows, directory=None, today=None):
    """Append every attempt to `corpus/results/<date>.jsonl`, minus the bulky page text."""
    directory = Path(directory or RESULTS)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{(today or date.today()).isoformat()}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            slim = {key: value for key, value in row.items() if key not in {"text", "elements"}}
            handle.write(json.dumps(slim, ensure_ascii=False) + "\n")
    return path
