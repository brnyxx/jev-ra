"""Benchmarks: offline fixture tasks always, the three live tasks on request, both against the recorded baseline."""

import contextlib
import functools
import json
import logging
import shutil
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import __version__
from ..agent import Agent
from ..browser.session import Session
from ..config import load
from ..decide.client import DecisionClient
from ..profile import shares
from . import verify as predicates
from .scripted import scripted

logger = logging.getLogger(__name__)

PAGES = Path(__file__).with_name("pages")
BASELINE_GLOB = "docs/benchmarks/*-browser-use-baseline"
FLASH_MODEL = "google/gemini-3-flash-preview"
ACCEPTANCE_RATIO = 3.0


@dataclass(frozen=True)
class OfflineTask:
    """A local fixture task whose decisions are scripted, not asked."""

    key: str
    page: str
    goal: str
    plan: tuple
    values: dict = field(default_factory=dict)
    max_steps: int = 8


@dataclass(frozen=True)
class LiveTask:
    """A real task, with the predicate that decides whether it was actually done."""

    key: str
    goal: str
    verify: object
    url: str = ""
    query: str = ""
    page: str = ""
    kind: str = "run"
    values: dict = field(default_factory=dict)
    max_steps: int = 25
    max_pages: int = 3


OFFLINE_TASKS = (
    OfflineTask(
        key="form_fill",
        page="checkout.html",
        goal="Place an order for Ada Lovelace at ada@example.com with express shipping.",
        plan=(
            ("TYPE_TEXT", "Full name", "name"),
            ("TYPE_TEXT", "Email", "email"),
            ("SELECT", "Shipping → Express", None),
            ("CLICK", "Place order", None),
        ),
        values={"name": "Ada Lovelace", "email": "ada@example.com"},
    ),
    OfflineTask(
        key="catalog_sort",
        page="catalog.html",
        goal="Sort this catalog by newest first.",
        # The sort bar sits below the fold, so the run has to scroll before it can click.
        plan=(("SCROLL_DOWN", "Scroll down", None), ("CLICK", "Newest first", None)),
    ),
)

LIVE_TASKS = (
    LiveTask(
        key="wikipedia",
        url="https://en.wikipedia.org/wiki/Main_Page",
        goal="Find and open the Wikipedia article about Godel incompleteness theorems.",
        values={"search_query": "Godel incompleteness theorems"},
        verify=predicates.wikipedia,
    ),
    LiveTask(
        key="flights",
        url="https://www.google.com/travel/flights",
        goal=("Search one-way flights from Zurich to London departing 2026-09-20 and show the list of results."),
        values={"origin": "Zurich", "destination": "London", "departure_date": "2026-09-20"},
        verify=predicates.flights,
    ),
    LiveTask(
        key="oliveyoung_sort",
        url=(
            "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do"
            "?dispCatNo=100000100010014&trackingCd=Cat100000100010014_Small"
        ),
        goal="Sort this product list by 신상품순.",
        verify=predicates.oliveyoung_sort,
    ),
    LiveTask(
        key="search_fact",
        kind="search",
        query="Python 3.12 release date",
        goal="What year was Python 3.12 released? Cite the page that says it.",
        verify=predicates.search_fact,
        max_pages=3,
    ),
    LiveTask(
        key="form_fill",
        page="checkout.html",
        goal="Place an order for Ada Lovelace at ada@example.com with express shipping.",
        values={"name": "Ada Lovelace", "email": "ada@example.com"},
        verify=predicates.form_fill,
        max_steps=8,
    ),
)


@contextlib.contextmanager
def serve(directory=PAGES):
    """Serve the bench fixture pages on loopback for the duration of the block."""
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = server.server_address
    try:
        yield f"http://{address[0]}:{address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class QuietHandler(SimpleHTTPRequestHandler):
    """A fixture server that does not narrate every request."""

    def log_message(self, format, *args):
        """Swallow the request log the base class would print to stderr."""


def repo_root(start=None):
    """The repository root, when jev-ra is running from a checkout."""
    for parent in [Path(start or __file__).resolve(), *Path(start or __file__).resolve().parents]:
        if (parent / "docs").is_dir() and (parent / "pyproject.toml").exists():
            return parent
    return None


def baseline_dir(root=None):
    """The recorded browser-use baseline directory, when there is one."""
    root = root or repo_root()
    if root is None:
        return None
    return next(iter(sorted(Path(root).glob(BASELINE_GLOB))), None)


def load_baseline(directory=None):
    """Recorded browser-use rows as {task: {variant: row}}; variant is 'flash' or the model name."""
    directory = directory or baseline_dir()
    rows = {}
    if directory is None or not Path(directory).is_dir():
        return rows
    for path in sorted(Path(directory).glob("*.jsonl")):
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("error") or not row.get("wall_ms"):
                continue
            variant = "flash" if row.get("flash_mode") else row.get("model", path.stem)
            rows.setdefault(row["task"], {})[variant] = row
    return rows


def flash_baseline(directory=None):
    """The flash_mode wall time per task, from the recorded rows."""
    return {
        task: variants["flash"]["wall_ms"] for task, variants in load_baseline(directory).items() if "flash" in variants
    }


def ratio_rows(summary, baseline=None):
    """One row per task: our median, the flash_mode ms, the ratio and whether it clears the bar.

    A task with no recorded browser-use row has no ratio; it still has to verify on every run.
    """
    baseline = flash_baseline() if baseline is None else baseline
    rows = []
    for item in summary:
        reference = baseline.get(item["task"])
        ours = item.get("median_ms")
        ratio = round(reference / ours, 2) if reference and ours else None
        verified_every_run = item.get("success_rate") == 1.0
        rows.append(
            {
                "task": item["task"],
                "jev_ra_ms": ours,
                "flash_mode_ms": reference,
                "ratio": ratio,
                "success_rate": item.get("success_rate"),
                "runs": item.get("runs"),
                "decisions": item.get("median_decisions"),
                "cost": item.get("median_cost"),
                "passed": verified_every_run and (ratio is None or ratio >= ACCEPTANCE_RATIO),
            }
        )
    return rows


VERIFY_TEXT_CHARS = 4000


def measure(agent, task, url, values, max_steps):
    """Run one task once and say whether the page shows it was done."""
    started = time.perf_counter()
    result = agent.run(task.goal, values=values, max_steps=max_steps, url=url)
    row = {
        "task": task.key,
        "status": result.status,
        "reason": result.reason,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "steps": len(result.steps),
        "decisions": result.decisions,
        "text_calls": len(result.text_calls),
        "cost": result.cost,
        "url": result.url,
        "text": (result.final_page.get("text") or "")[:VERIFY_TEXT_CHARS],
        "elements": result.final_page.get("elements") or [],
        "profile": result.steps,
    }
    return verified(row, getattr(task, "verify", None))


def verified(row, verify):
    """A run only counts when the page says the task was done."""
    row["ok"] = bool(verify(row)) if verify else row.get("status") == "done"
    if not row["ok"] and row.get("status") == "done":
        row["reason"] = "finished but the page does not show the task done"
    return row


def median(values):
    """The median of the values, rounded, or None when there are none."""
    return round(statistics.median(values)) if values else None


def percentile(values, fraction=0.9):
    """The nearest-rank percentile of the values, rounded, or None."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return round(ordered[index])


def summarise(rows):
    """Per task: medians over the runs that actually worked, plus the success rate over all of them."""
    summary = {}
    for row in rows:
        summary.setdefault(row["task"], []).append(row)
    table = []
    for task, runs in summary.items():
        good = [run for run in runs if run.get("ok")]
        times = [run["elapsed_ms"] for run in good]
        table.append(
            {
                "task": task,
                "runs": len(runs),
                "successes": len(good),
                "success_rate": round(len(good) / len(runs), 3) if runs else 0.0,
                "median_ms": median(times),
                "p90_ms": percentile(times),
                "median_steps": median([run["steps"] for run in good]),
                "median_decisions": median([run["decisions"] for run in good]),
                "median_cost": round(statistics.median([run["cost"] for run in good]), 6) if good else None,
                "text_calls": sum(run.get("text_calls", 0) for run in runs),
                "failures": sorted({run.get("reason") or run.get("status") for run in runs if not run.get("ok")}),
            }
        )
    return table


def run_offline(config=None, tasks=OFFLINE_TASKS, session=None, runs=1):
    """Time the fixture tasks with scripted decisions and no network."""
    config = config or load()
    owned = session is None
    session = session or Session(config)
    measured = []
    try:
        with serve() as base:
            for _attempt in range(runs):
                for task in tasks:
                    # A scripted plan answers by position, so asking it a question ahead of time
                    # would spend a step of the plan on a page that has not happened yet.
                    agent = Agent(session=session, config=config, decide=scripted(task.plan), prefetch=False)
                    measured.append(measure(agent, task, f"{base}/{task.page}", task.values, task.max_steps))
    finally:
        if owned:
            session.close()
    return measured


def measure_search(task, config, decide):
    """Run one search task once and score what it found."""
    from ..search import search as run_search

    session = Session(config)
    started = time.perf_counter()
    try:
        payload = run_search(
            task.query,
            task.goal,
            task.max_pages,
            config=config,
            decide=decide,
            session=session,
            session_factory=lambda: Session(config),
        )
    finally:
        session.close()
    row = {
        "task": task.key,
        "status": "done" if payload["results"] else "blocked",
        "reason": "",
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "steps": len(payload["results"]),
        "decisions": payload["decisions"],
        "text_calls": 0,
        "cost": payload["cost"],
        "url": payload["engine"],
        "results": [
            {"url": item.get("url", ""), "text": (item.get("text") or "")[:VERIFY_TEXT_CHARS]}
            for item in payload["results"]
        ],
    }
    return verified(row, task.verify)


def run_live(config=None, tasks=LIVE_TASKS, runs=1):
    """Run the live tasks against the real web, `runs` times each."""
    config = config or load()
    if not config.api_key:
        raise RuntimeError("bench --live needs a Jev key. Set OPENROUTER_API_KEY, then run `jev-ra doctor`.")
    client = DecisionClient(config)
    measured = []
    try:
        with serve() as base:
            for attempt in range(runs):
                for task in tasks:
                    logger.info("run %s/%s: %s", attempt + 1, runs, task.key)
                    if task.kind == "search":
                        measured.append(measure_search(task, config, client.decide))
                        continue
                    session = Session(config)
                    try:
                        agent = Agent(session=session, config=config, decide=client.decide)
                        url = f"{base}/{task.page}" if task.page else task.url
                        measured.append(measure(agent, task, url, task.values, task.max_steps))
                    finally:
                        session.close()
    finally:
        client.close()
    return measured


def profile_rows(measured):
    """Where the time went across every step of every run, and what share of wall time that is."""
    steps = [step for row in measured for step in row.get("profile") or []]
    wall = sum(row.get("elapsed_ms") or 0 for row in measured)
    return shares(steps, wall)


def profile_table(measured):
    """The same thing as a markdown table, with the share rendered as a percentage."""
    rows = [
        {"category": row["category"], "ms": row["ms"], "share": f"{row['share']:.1%}" if row["share"] else "-"}
        for row in profile_rows(measured)
    ]
    return markdown_table(rows, ("category", "ms", "share"))


def markdown_table(rows, columns=None):
    """Render rows as a markdown table of the given columns."""
    columns = columns or list(rows[0]) if rows else []
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join("" if row.get(key) is None else str(row.get(key)) for key in columns) + " |")
    return "\n".join(lines)


BROWSER_USE_PIN = "browser-use==0.13.10"


def uv_command():
    """The uv executable, which is what knows how to make a browser-use environment."""
    found = shutil.which("uv")
    if not found:
        raise RuntimeError("uv is not on PATH; the browser-use baseline needs it to build its environment.")
    return found


def run_baseline(runs=1, model=FLASH_MODEL, flash=True, directory=None, out_dir=None):
    """Re-run the recorded browser-use script in its own environment, `runs` times.

    The script writes its rows next to itself, so it is copied into `out_dir` first: the recorded
    baseline is a historical record and must not gain rows from a later run.
    """
    directory = Path(directory or baseline_dir() or "")
    script = directory / "bench.py"
    if not script.exists():
        raise RuntimeError(f"No browser-use bench script at {script}")
    out_dir = Path(out_dir or directory.parent / f"{date.today().isoformat()}-v{__version__}")
    out_dir.mkdir(parents=True, exist_ok=True)
    copy = out_dir / "bench.py"
    copy.write_text(script.read_text())
    completed = []
    for attempt in range(runs):
        logger.info("browser-use baseline run %s/%s", attempt + 1, runs)
        finished = subprocess.run(
            [
                uv_command(),
                "run",
                "--no-project",
                "--with",
                BROWSER_USE_PIN,
                "python",
                str(copy),
                model,
                "flash" if flash else "default",
            ],
            capture_output=True,
            text=True,
        )
        completed.append(
            {
                "returncode": finished.returncode,
                "stdout": finished.stdout,
                "stderr": finished.stderr[-2000:],
            }
        )
        if finished.returncode != 0:
            break
    return completed
