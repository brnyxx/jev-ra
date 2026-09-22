"""WebVoyager through the same adapter, written out for WebVoyager's own GPT-4V auto-evaluator.

The benchmark is saturated - the field reports 99 % - so it is a regression gate here, not a score
to chase. Its task file is time-sensitive: the Booking and Google Flights tasks name dates from the
season they were written in, and its authors say those have to be re-dated by hand before a run.
Re-dating them would be writing our own tasks, so they are skipped, named, and counted.

Usage:
    uv run python -m bench.public.webvoyager --tasks 10 --out bench/public/runs/webvoyager
    uv run python -m bench.public.webvoyager --judge-only --out bench/public/runs/webvoyager
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from jev_ra import logs
from jev_ra.config import load
from jev_ra.errors import JevRaError

from .adapter import Adapter, evidence
from .vendor import ensure

logger = logging.getLogger("bench.public.webvoyager")

TASK_FILE = Path("data") / "WebVoyager_data.jsonl"
MAX_STEPS = 25
ANSWER_CHARS = 600
JUDGE_TIMEOUT_S = 3600
# WebVoyager's evaluator is written for `gpt-4-vision-preview`, which OpenAI has retired. Its
# successor is what the same prompt runs on now; the prompt, the images and the verdict rule are
# the repository's own, unchanged.
JUDGE_MODEL = "openai/gpt-4o"
JUDGE_IMAGES = 15
JUDGE_BASE_URL = "https://openrouter.ai/api/v1"
JUDGE_PACKAGES = ("openai==1.68.2",)
# The two site families whose tasks name a date. Everything else in the file is evergreen.
TIME_SENSITIVE = ("Booking", "Google Flights")
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
    "|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
DATED = re.compile(rf"\b(?:{MONTHS})\b|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b|\b20\d{{2}}\b", re.IGNORECASE)
YEAR = re.compile(r"\b(20\d{2})\b")
SYSTEM_MESSAGE = (
    "jev-ra drove this task: one observation of the page, one decision per step, and a screenshot "
    "after every action that landed. The messages below are that trajectory."
)


def tasks_file(root=None):
    """The WebVoyager task file inside the pinned checkout."""
    return Path(root or ensure("webvoyager")) / TASK_FILE


def load_tasks(path=None):
    """Every task in `WebVoyager_data.jsonl`, in file order."""
    text = Path(path or tasks_file()).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def past_dated(task, today=None):
    """Why a time-sensitive task cannot be run as written, or None when it can."""
    if task["web_name"] not in TIME_SENSITIVE:
        return None
    found = DATED.search(task["ques"])
    if not found:
        return None
    today = today or date.today()
    years = [int(year) for year in YEAR.findall(task["ques"])]
    if years and max(years) < today.year:
        return f"names {max(years)}, which is past"
    return f"names a date ({found.group(0)}) the benchmark expects to be re-dated by hand"


def select(tasks, count=None, ids=(), today=None):
    """The tasks to run and the time-sensitive ones held back, one site at a time."""
    if ids:
        found = {task["id"]: task for task in tasks}
        missing = [name for name in ids if name not in found]
        if missing:
            raise JevRaError(f"No such WebVoyager task: {', '.join(missing)}")
        return [found[name] for name in ids], []
    skipped = [{"id": task["id"], "why": why} for task in tasks if (why := past_dated(task, today))]
    held = {row["id"] for row in skipped}
    pool = [task for task in tasks if task["id"] not in held]
    if count is None or count >= len(pool):
        return pool, skipped
    # Ten tasks from the top of the file would all be Allrecipes. One site at a time gives a smoke
    # that touches ten different sites, and stays the same ten on the next run.
    sites, buckets = [], {}
    for task in pool:
        if task["web_name"] not in buckets:
            sites.append(task["web_name"])
            buckets[task["web_name"]] = []
        buckets[task["web_name"]].append(task)
    chosen, position = [], 0
    while len(chosen) < count and position < max(len(bucket) for bucket in buckets.values()):
        for site in sites:
            if position < len(buckets[site]) and len(chosen) < count:
                chosen.append(buckets[site][position])
        position += 1
    return chosen, skipped


def messages(task, result):
    """The trajectory as `interact_messages.json`, the shape WebVoyager's evaluator parses."""
    question = " ".join(task["ques"].split())
    spoken = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {
            "role": "user",
            "content": f"Now given a task: {question} Please interact with {task['web']} and get the answer.",
        },
    ]
    for entry in result["trajectory"]:
        landed = "landed" if entry["landed"] else "did not change the page"
        spoken.append(
            {
                "role": "assistant",
                "content": (
                    f"Thought: step {entry['step']} on {entry['url']}\n"
                    f"Action: {entry['operation']} [{entry['target']}] {entry['label']} - {landed}"
                ),
            }
        )
    spoken.append({"role": "assistant", "content": f"Thought: {result['status']}\nAction: ANSWER; [{answer(result)}]"})
    return spoken


def answer(result):
    """What the evaluator is shown: jev-ra's own sentence, else the page it finished on."""
    said = result.get("final_answer") or result.get("final_page_text") or ""
    text = " ".join(said.split())
    return text.replace("[", "(").replace("]", ")")[:ANSWER_CHARS] or "no answer; the run ended on the page above"


def rename_frames(directory):
    """The adapter's `0000.png` frames under the `screenshot0.png` names the evaluator globs for."""
    names = []
    for number, path in enumerate(sorted(directory.glob("[0-9][0-9][0-9][0-9].png"))):
        target = directory / f"screenshot{number}.png"
        path.rename(target)
        names.append(target.name)
    return names


def run_task(task, out, config, max_steps=MAX_STEPS, session=None, decide=None):
    """One live attempt at one task, written out for WebVoyager's evaluator."""
    directory = Path(out) / f"task{task['id']}"
    started = time.perf_counter()
    adapter = Adapter(directory, config=config, session=session, decide=decide, image="png")
    try:
        result = adapter.run(" ".join(task["ques"].split()), max_steps=max_steps, url=task["web"])
    except JevRaError as error:
        logger.error("%s: %s", task["id"], error)
        result = {
            "final_url": task["web"],
            "final_answer": None,
            "final_page_text": None,
            "trajectory": [],
            "status": "error",
            "reason": type(error).__name__,
            "steps": 0,
            "decisions": 0,
            "text_calls": 0,
            "cost": 0.0,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "detail": {"error": str(error)},
            "run_id": "",
        }
    finally:
        adapter.close()
    directory.mkdir(parents=True, exist_ok=True)
    frames = rename_frames(directory)
    (directory / "interact_messages.json").write_text(
        json.dumps(messages(task, result), ensure_ascii=False, indent=2) + "\n"
    )
    return {
        "id": task["id"],
        "web_name": task["web_name"],
        "web": task["web"],
        "ques": task["ques"],
        "run_id": result.get("run_id", ""),
        "status": result["status"],
        "reason": result["reason"],
        "why": evidence(result),
        "steps": result["steps"],
        "decisions": result["decisions"],
        "text_calls": result["text_calls"],
        "cost": result["cost"],
        "elapsed_ms": result["elapsed_ms"],
        "final_url": result["final_url"],
        "final_answer": result["final_answer"],
        "frames": len(frames),
    }


VERDICT = re.compile(r"^-{10,} (?P<dir>.+?) -{10,}$")
RESULT = re.compile(r"^Auto_eval_res: (?P<value>\d+|None)$")
NO_ANSWER = re.compile(r"^Not find answer for (?P<dir>.+?)(?: only system messages)?$")


def read_verdicts(output):
    """What the evaluator decided per task directory, read off its own printed lines."""
    verdicts, current = {}, None
    for line in output.splitlines():
        line = line.strip()
        header = VERDICT.match(line)
        if header:
            current = Path(header.group("dir")).name
            continue
        nothing = NO_ANSWER.match(line)
        if nothing:
            verdicts[Path(nothing.group("dir")).name] = 0
            continue
        scored = RESULT.match(line)
        if scored and current:
            verdicts[current] = 0 if scored.group("value") == "None" else int(scored.group("value"))
    return verdicts


def judge(out, model=JUDGE_MODEL, api_key=None, images=JUDGE_IMAGES):
    """WebVoyager's own auto-evaluator, over the trajectories already written."""
    out = Path(out).resolve()
    tasks = sorted(path for path in out.iterdir() if path.is_dir())
    if not tasks:
        raise JevRaError(f"No trajectories to judge under {out}")
    key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise JevRaError("The WebVoyager evaluator needs a key; export OPENROUTER_API_KEY.")
    repository = ensure("webvoyager")
    command = [
        "uv",
        "run",
        "--no-project",
        *[argument for package in JUDGE_PACKAGES for argument in ("--with", package)],
        "python",
        "auto_eval.py",
        "--api_key",
        key,
        "--process_dir",
        str(out),
        "--api_model",
        model,
        "--max_attached_imgs",
        str(images),
    ]
    environment = {**os.environ, "OPENAI_BASE_URL": JUDGE_BASE_URL, "OPENAI_API_KEY": key}
    logger.info("Judging %s trajectories with %s via %s", len(tasks), model, JUDGE_BASE_URL)
    done = subprocess.run(
        command,
        cwd=str(repository / "evaluation"),
        env=environment,
        timeout=JUDGE_TIMEOUT_S,
        check=False,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise JevRaError(f"The WebVoyager evaluator failed: {(done.stderr or done.stdout).strip()[-800:]}")
    (out.parent / (out.name + "-judge.log")).write_text(done.stdout)
    return read_verdicts(done.stdout)


def report(rows, verdicts=None, skipped=()):
    """One line per task and one summary line, with the evaluator's verdict when there is one."""
    lines = []
    for row in rows:
        verdict = "not judged"
        if verdicts is not None:
            verdict = "PASS" if verdicts.get(f"task{row['id']}") else "FAIL"
        lines.append(
            f"{row['id']:28s} {verdict:10s} {row['status']}:{row['reason'] or '-'} "
            f"{row['steps']} steps {row['elapsed_ms']} ms ${row['cost']:.4f}"
        )
    cost = sum(row["cost"] for row in rows)
    wall = sum(row["elapsed_ms"] for row in rows)
    if verdicts is None:
        lines.append(f"{len(rows)} tasks, not judged, ${cost:.4f} agent cost, {wall / 1000:.1f} s wall")
    else:
        passed = sum(1 for row in rows if verdicts.get(f"task{row['id']}"))
        rate = 100.0 * passed / len(rows) if rows else 0.0
        lines.append(
            f"{passed}/{len(rows)} = {rate:.1f}% by the WebVoyager evaluator, "
            f"${cost:.4f} agent cost, {wall / 1000:.1f} s wall"
        )
    if skipped:
        lines.append(f"{len(skipped)} time-sensitive tasks held back: {', '.join(row['id'] for row in skipped[:6])}")
    return "\n".join(lines)


def parse(argv=None):
    """The command line."""
    parser = argparse.ArgumentParser(description="Run WebVoyager tasks through jev-ra.")
    parser.add_argument("--tasks", type=int, default=10, help="how many tasks to run (default 10)")
    parser.add_argument("--out", required=True, help="directory the evaluator reads")
    parser.add_argument("--task-id", action="append", default=[], help="run one named task (repeatable)")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS, help=f"steps per task (default {MAX_STEPS})")
    parser.add_argument("--tasks-file", help="a local copy of WebVoyager_data.jsonl")
    parser.add_argument("--judge", action="store_true", help="run the WebVoyager evaluator afterwards")
    parser.add_argument("--judge-only", action="store_true", help="judge an existing --out directory and stop")
    parser.add_argument("--judge-model", default=JUDGE_MODEL, help=f"the evaluator's backbone (default {JUDGE_MODEL})")
    return parser.parse_args(argv)


def main(argv=None):
    """Run the selected tasks, write what the evaluator reads, and judge it when asked."""
    logs.configure({**os.environ, "JEV_RA_LOG_LEVEL": os.environ.get("JEV_RA_LOG_LEVEL") or "INFO"})
    args = parse(argv)
    out = Path(args.out)
    if args.judge_only:
        verdicts = judge(out, model=args.judge_model)
        rows = [json.loads(line) for line in (out / "summary.jsonl").read_text().splitlines() if line.strip()]
        print(report(rows, verdicts))
        return 0
    config = load()
    if not config.api_key:
        raise JevRaError("WebVoyager runs against the live web and needs a jev-ra key.")
    if config.text_model is None:
        logger.warning("No JEV_RA_TEXT_MODEL is set, so every task that needs typing will escalate needs_value")
    tasks = load_tasks(args.tasks_file)
    chosen, skipped = select(tasks, args.tasks, args.task_id)
    logger.info("Running %s of %s tasks, %s held back as time-sensitive", len(chosen), len(tasks), len(skipped))
    out.mkdir(parents=True, exist_ok=True)
    (out / "skipped.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=2) + "\n")
    rows = []
    with (out / "summary.jsonl").open("a", encoding="utf-8") as handle:
        for number, task in enumerate(chosen, start=1):
            logger.info("%s/%s %s %s", number, len(chosen), task["id"], " ".join(task["ques"].split())[:70])
            row = run_task(task, out, config, max_steps=args.max_steps)
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
    verdicts = judge(out, model=args.judge_model) if args.judge else None
    print(report(rows, verdicts, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
