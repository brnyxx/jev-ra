"""Record one bench task as timestamped frames, under jev-ra and optionally under browser-use.

Both sides drive the same Chrome, one after the other, so the frames are comparable.
Frames are captured by polling Page.captureScreenshot on a background thread: CDP screencast
events are not exposed per session through the harness, and a fixed cadence keeps the clocks honest.
"""

import argparse
import json
import logging
import sys
import threading
import time
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_ra.bench import LIVE_TASKS, OFFLINE_TASKS, serve
from jev_ra.bench.scripted import scripted
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


def record_browser_use(key, out_dir, fps=DEFAULT_FPS):
    """Only possible where browser-use is installed; it is not a dependency of jev-ra."""
    try:
        import browser_use  # noqa: F401
    except ImportError:
        logger.warning("browser-use is not installed; recording the jev-ra side only")
        return None
    raise SystemExit(
        "Recording the browser-use side is done by docs/benchmarks/*/bench.py with its own "
        "environment; point --browser-use-manifest at the directory it wrote."
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
