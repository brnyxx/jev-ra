"""Run the capability matrix in tests/fixtures/capabilities.toml, scripted or live, and write one row per run.

    uv run python docs/benchmarks/2026-09-23-capabilities/capabilities.py scripted out.jsonl
    TYPESAFE_API_KEY=... uv run python docs/benchmarks/2026-09-23-capabilities/capabilities.py live out.jsonl --runs 3

Scripted rows answer whether the mechanism can carry out the plan at all; live rows whether Jev
picks it. A run counts only when the page check holds and the run ended the way the entry expects.
"""

import argparse
import functools
import json
import logging
import tempfile
import threading
import time
import tomllib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

from jev_ra.agent import Agent
from jev_ra.bench.scripted import scripted
from jev_ra.browser.session import Session
from jev_ra.config import load
from jev_ra.decide.client import DecisionClient

logger = logging.getLogger("capabilities")
ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
CATALOG = FIXTURES / "capabilities.toml"


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(FIXTURES)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def entries(only=()):
    catalog = tomllib.loads(CATALOG.read_text())["capability"]
    return [entry for entry in catalog if not only or entry["name"] in only]


def plan_of(entry):
    return [tuple([*step, None, None][:3]) for step in entry["plan"]]


def judged(entry, session, result):
    try:
        held = bool(session.evaluate(f"!!({entry['check']})"))
    except Exception as error:
        return False, f"check failed: {error}"
    expected = entry.get("expect", ["done"])
    ended = result.reason if result.status == "escalate" else result.status
    wanted = entry.get("downloaded")
    if wanted and wanted not in [item.get("file") for item in getattr(result, "downloads", []) or []]:
        return False, f"{wanted} was not downloaded"
    if not held:
        return False, "the page does not show the goal reached"
    if ended not in expected:
        return False, f"ended {ended}, expected {' or '.join(expected)}"
    return True, ""


def run_one(entry, base, config, decide, prefetch):
    session = Session(config)
    started = time.perf_counter()
    row = {"name": entry["name"], "pattern": entry["pattern"]}
    try:
        agent = Agent(session=session, config=config, decide=decide, prefetch=prefetch)
        result = agent.run(
            entry["goal"],
            values=entry.get("values"),
            max_steps=entry.get("max_steps", 10),
            url=base + entry["page"],
        )
        ok, why = judged(entry, session, result)
        row.update(
            ok=ok,
            why=why,
            status=result.status,
            reason=result.reason,
            steps=[f"{step['operation']} {step['target_label']}".strip() for step in result.steps],
            decisions=result.decisions,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            url=result.url,
            candidates=[candidate["label"] for candidate in result.candidates[:4]],
            detail={key: value for key, value in result.detail.items() if key != "page_text"},
            downloads=getattr(result, "downloads", []),
        )
    except Exception as error:
        row.update(
            ok=False,
            why=f"{type(error).__name__}: {error}",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
    finally:
        try:
            session.close()
        except Exception as error:
            logger.warning("could not close the session: %s", error)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("scripted", "live"))
    parser.add_argument("out")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--only", nargs="*", default=())
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = load()
    server, base = serve()
    client = DecisionClient(config) if args.mode == "live" else None
    # What a run downloads goes to a folder of its own, not to the Downloads folder of whoever runs it.
    ensure_daemon()
    cdp("Browser.setDownloadBehavior", behavior="allow", downloadPath=tempfile.mkdtemp(prefix="capabilities-"))
    rows = []
    try:
        for attempt in range(args.runs):
            for entry in entries(args.only):
                if args.mode == "scripted":
                    row = run_one(entry, base, config, scripted(plan_of(entry)), prefetch=False)
                else:
                    row = run_one(entry, base, config, client.decide, prefetch=True)
                row["run"] = attempt + 1
                rows.append(row)
                logger.info(
                    "%-28s run %s %-5s %-28s %s",
                    entry["name"],
                    attempt + 1,
                    row["ok"],
                    f"{row.get('status', '')}/{row.get('reason', '')}",
                    row["why"][:90],
                )
                with Path(args.out).open("a") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        if client is not None:
            client.close()
        cdp("Browser.setDownloadBehavior", behavior="default")
        server.shutdown()


if __name__ == "__main__":
    main()
