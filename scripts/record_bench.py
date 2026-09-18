"""Record one bench task as timestamped frames, under jev-ra and optionally under browser-use.

Both sides drive the same Chrome, one after the other, so the frames are comparable.
Frames are captured by polling Page.captureScreenshot on a background thread: CDP screencast
events are not exposed per session through the harness, and a fixed cadence keeps the clocks honest.
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_ra.bench import FLASH_MODEL, LIVE_TASKS, OFFLINE_TASKS, baseline_dir, serve
from jev_ra.bench.scripted import scripted
from jev_ra.browser.chrome import ensure as ensure_chrome
from jev_ra.browser.session import Session
from jev_ra.config import load
from jev_ra.decide.client import DecisionClient

logger = logging.getLogger("record_bench")

DEFAULT_FPS = 10


class Recorder:
    """Captures JPEG frames at a fixed cadence and remembers when each one was taken."""

    def __init__(self, session, directory, fps=DEFAULT_FPS):
        self.session = session
        self.directory = Path(directory)
        self.interval = 1.0 / fps
        self.frames = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        """Capture a frame every interval until the recording is stopped."""
        started = time.perf_counter()
        index = 0
        while not self.stop.is_set():
            at = round((time.perf_counter() - started) * 1000)
            try:
                image = self.session.screenshot()
            except Exception as error:
                logger.debug("Dropped a frame: %s", error)
                self.stop.wait(self.interval)
                continue
            path = self.directory / f"{index:06d}.jpg"
            path.write_bytes(image)
            self.frames.append({"ms": at, "file": path.name})
            index += 1
            self.stop.wait(self.interval)

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join(timeout=5)


def write_manifest(directory, label, task, frames, elapsed_ms, status, extra=None):
    manifest = {
        "label": label,
        "task": task,
        "elapsed_ms": elapsed_ms,
        "status": status,
        "frames": sorted(frames, key=lambda frame: frame["ms"]),
        **(extra or {}),
    }
    path = Path(directory) / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    return path


def task_named(key):
    for task in (*LIVE_TASKS, *OFFLINE_TASKS):
        if task.key == key:
            return task
    raise SystemExit(f"unknown task {key!r}; try one of " + ", ".join(t.key for t in (*LIVE_TASKS, *OFFLINE_TASKS)))


def record_jev_ra(key, out_dir, fps=DEFAULT_FPS):
    from jev_ra.agent import Agent

    task = task_named(key)
    config = load()
    offline = hasattr(task, "plan")
    client = None if offline else DecisionClient(config)
    session = Session(config)
    directory = Path(out_dir) / "jev-ra"
    try:
        decide = scripted(task.plan) if offline else client.decide
        agent = Agent(session=session, config=config, decide=decide)
        with serve() if offline else nullcontext() as base:
            url = f"{base}/{task.page}" if offline else task.url
            started = time.perf_counter()
            with Recorder(session, directory, fps) as recorder:
                result = agent.run(task.goal, values=task.values, max_steps=task.max_steps, url=url)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
        return write_manifest(
            directory,
            "jev-ra",
            key,
            recorder.frames,
            elapsed_ms,
            result.status,
            {"steps": len(result.steps), "decisions": result.decisions, "cost": result.cost},
        )
    finally:
        session.close()
        if client:
            client.close()


class nullcontext:
    """A context manager that yields nothing, for the live tasks that need no fixture server."""

    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


def page_targets(cdp_url):
    with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/list", timeout=5) as response:
        listing = json.loads(response.read())
    return [item for item in listing if item.get("type") == "page"]


def target_that_moved(cdp_url, before, needle):
    """The page target browser-use is driving.

    It takes over an existing tab rather than opening one, so the signal is a target whose url
    changed since the subprocess started, or a new one. `needle` only breaks ties.
    """
    moved = []
    for item in page_targets(cdp_url):
        url = item.get("url") or ""
        if item["id"] not in before or before[item["id"]] != url:
            moved.append((needle in url, item["id"]))
    moved.sort(reverse=True)
    return moved[0][1] if moved else None


def record_browser_use(key, out_dir, fps=DEFAULT_FPS, model=FLASH_MODEL):
    """Run the recorded browser-use script in its own environment and film the tab it opens.

    browser-use is not a dependency of jev-ra, so it runs through `uv run --with`. We watch the same
    Chrome for the page target it creates and attach a read-only session to it.
    """
    directory = baseline_dir()
    if directory is None:
        raise SystemExit("No recorded browser-use script to run")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    copy = out_dir / "bench.py"
    copy.write_text((directory / "bench.py").read_text())
    config = load()
    cdp_url, _source = ensure_chrome(viewport=(config.viewport.width, config.viewport.height))
    task = next(item for item in LIVE_TASKS if item.key == key)
    needle = task.url.split("://", 1)[-1].split("?", 1)[0].rstrip("/")
    before = {item["id"]: (item.get("url") or "") for item in page_targets(cdp_url)}
    started = time.perf_counter()
    process = subprocess.Popen(
        [shutil.which("uv"), "run", "--no-project", "--with", "browser-use==0.13.10", "python", str(copy),
         model, "flash", key],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    target = None
    deadline = time.monotonic() + 180
    while target is None and time.monotonic() < deadline and process.poll() is None:
        target = target_that_moved(cdp_url, before, needle)
        if target is None:
            time.sleep(0.2)
    if target is None:
        process.wait(timeout=600)
        raise SystemExit("browser-use never opened a page target to film")
    logger.info("filming browser-use on target %s", target)
    session = Session(config, target_id=target)
    directory_out = out_dir / "browser-use"
    with Recorder(session, directory_out, fps) as recorder:
        process.wait(timeout=900)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    row = {}
    for line in (process.stdout.read() if process.stdout else "").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
    return write_manifest(
        directory_out,
        "browser-use flash_mode",
        key,
        recorder.frames,
        row.get("wall_ms") or elapsed_ms,
        "done" if row.get("is_done") else "unfinished",
        {"steps": row.get("steps"), "model": model},
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="record_bench", description=__doc__.splitlines()[0])
    parser.add_argument("task", help="a bench task key, e.g. wikipedia or form_fill")
    parser.add_argument("--out", default="docs/recordings", help="directory to write frames into")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--with-browser-use", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out_dir = Path(args.out) / args.task
    manifest = record_jev_ra(args.task, out_dir, args.fps)
    logger.info("wrote %s", manifest)
    if args.with_browser_use:
        other = record_browser_use(args.task, out_dir, args.fps)
        if other:
            logger.info("wrote %s", other)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
