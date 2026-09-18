"""Benchmarks: offline fixture tasks always, the three live tasks on request, both against the recorded baseline."""

import contextlib
import functools
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..agent import Agent
from ..browser.session import Session
from ..config import load
from ..decide.client import DecisionClient
from .scripted import scripted

PAGES = Path(__file__).with_name("pages")
BASELINE_GLOB = "docs/benchmarks/*-browser-use-baseline"
FLASH_MODEL = "google/gemini-3-flash-preview"
ACCEPTANCE_RATIO = 3.0


@dataclass(frozen=True)
class OfflineTask:
    key: str
    page: str
    goal: str
    plan: tuple
    values: dict = field(default_factory=dict)
    max_steps: int = 8


@dataclass(frozen=True)
class LiveTask:
    key: str
    url: str
    goal: str
    values: dict = field(default_factory=dict)
    max_steps: int = 25


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
    ),
    LiveTask(
        key="flights",
        url="https://www.google.com/travel/flights",
        goal=(
            "Search one-way flights from Zurich to London departing 2026-09-20 "
            "and show the list of results."
        ),
        values={"origin": "Zurich", "destination": "London", "departure_date": "2026-09-20"},
    ),
    LiveTask(
        key="oliveyoung_sort",
        url=(
            "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do"
            "?dispCatNo=100000100010014&trackingCd=Cat100000100010014_Small"
        ),
        goal="Sort this product list by 신상품순.",
    ),
)


@contextlib.contextmanager
def serve(directory=PAGES):
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def repo_root(start=None):
    for parent in [Path(start or __file__).resolve(), *Path(start or __file__).resolve().parents]:
        if (parent / "docs").is_dir() and (parent / "pyproject.toml").exists():
            return parent
    return None


def baseline_dir(root=None):
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
    return {
        task: variants["flash"]["wall_ms"]
        for task, variants in load_baseline(directory).items()
        if "flash" in variants
    }


def ratio_rows(measured, baseline=None):
    """One row per measured task: our ms, the flash_mode ms, the ratio and whether it clears the bar."""
    baseline = flash_baseline() if baseline is None else baseline
    rows = []
    for item in measured:
        reference = baseline.get(item["task"])
        ratio = round(reference / item["elapsed_ms"], 2) if reference and item["elapsed_ms"] else None
        rows.append(
            {
                "task": item["task"],
                "jev_ra_ms": item["elapsed_ms"],
                "flash_mode_ms": reference,
                "ratio": ratio,
                "status": item.get("status"),
                "steps": item.get("steps"),
                "decisions": item.get("decisions"),
                "cost": item.get("cost", 0.0),
                "passed": bool(ratio and ratio >= ACCEPTANCE_RATIO and item.get("status") == "done"),
            }
        )
    return rows


def measure(agent, task, url, values, max_steps):
    started = time.perf_counter()
    result = agent.run(task.goal, values=values, max_steps=max_steps, url=url)
    return {
        "task": task.key,
        "status": result.status,
        "reason": result.reason,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "steps": len(result.steps),
        "decisions": result.decisions,
        "text_calls": len(result.text_calls),
        "cost": result.cost,
        "url": result.url,
    }


def run_offline(config=None, tasks=OFFLINE_TASKS, session=None):
    config = config or load()
    owned = session is None
    session = session or Session(config)
    measured = []
    try:
        with serve() as base:
            for task in tasks:
                agent = Agent(session=session, config=config, decide=scripted(task.plan))
                measured.append(measure(agent, task, f"{base}/{task.page}", task.values, task.max_steps))
    finally:
        if owned:
            session.close()
    return measured


def run_live(config=None, tasks=LIVE_TASKS):
    config = config or load()
    if not config.api_key:
        raise RuntimeError("bench --live needs a Jev key. Set OPENROUTER_API_KEY, then run `jev-ra doctor`.")
    client = DecisionClient(config)
    measured = []
    try:
        for task in tasks:
            session = Session(config)
            try:
                agent = Agent(session=session, config=config, decide=client.decide)
                measured.append(measure(agent, task, task.url, task.values, task.max_steps))
            finally:
                session.close()
    finally:
        client.close()
    return measured
