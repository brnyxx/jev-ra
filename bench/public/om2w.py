"""Online-Mind2Web through the adapter, written out in the submission layout the benchmark reads.

The task file itself is not in this repository and is not in the benchmark's git repository either:
it lives in a gated Hugging Face dataset. So it is downloaded at run time into a gitignored
directory - from Hugging Face when a token is in the environment, otherwise from a public mirror
pinned to one commit, which is one task revision behind the gated file and says so.

Usage:
    uv run python -m bench.public.om2w --tasks 10 --out bench/public/runs/om2w
    uv run python -m bench.public.om2w --judge-only --out bench/public/runs/om2w
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from jev_ra import logs
from jev_ra.config import load
from jev_ra.errors import JevRaError

from .adapter import Adapter, evidence
from .vendor import ensure

logger = logging.getLogger("bench.public.om2w")

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SCHEMA_VERSION = "online-mind2web-v2"
HUGGINGFACE = "https://huggingface.co/datasets/osunlp/Online-Mind2Web/resolve/main/Online_Mind2Web.json"
# The task file as the ABP submission published it - the same 300 tasks, at a commit that cannot
# move. It carries the 2026-01-02 task revision; the gated file has had one revision since
# (6 tasks, 2026-05-15), so a number measured from the mirror is not the leaderboard's task set.
MIRROR = (
    "https://raw.githubusercontent.com/theredsix/abp-online-mind2web-results/"
    "c30614d7e1ddf345b7ed5cc8591da8f72b7ca065/Online_Mind2Web.json"
)
MIRROR_REVISION = "2026-01-02"
LEVELS = ("easy", "medium", "hard")
MAX_STEPS = 25
DOWNLOAD_TIMEOUT_S = 60
JUDGE_TIMEOUT_S = 3600
JUDGE_MODE = "WebJudge_Online_Mind2Web_eval"
JUDGE_MODEL = "openai/o4-mini"
JUDGE_THRESHOLD = 3
JUDGE_BASE_URL = "https://openrouter.ai/api/v1"
JUDGE_PACKAGES = ("openai==1.68.2", "backoff==2.2.1", "Pillow==11.1.0")
PAGE_VERBS = {"NAVIGATE", "GO_BACK", "GO_FORWARD", "REFRESH"}
VERBS = {
    "NAVIGATE": ("NAVIGATE", "page"),
    "CLICK": ("CLICK", "element"),
    "TYPE_TEXT": ("TYPE", "element"),
    "SELECT": ("SELECT", "element"),
    "SCROLL_DOWN": ("SCROLL", "page"),
    "SCROLL_UP": ("SCROLL", "page"),
    "WAIT": ("WAIT", "page"),
    "PRESS_ENTER": ("PRESS_KEY", "page"),
}
DESCRIPTIONS = {
    "NAVIGATE": "open the website the task starts from",
    "SCROLL_DOWN": "scroll down one viewport to read further",
    "SCROLL_UP": "scroll up one viewport",
    "WAIT": "wait for the page to finish updating",
    "PRESS_ENTER": "press Enter to submit the focused field",
}


def tasks_path(directory=None):
    """Where the downloaded task file lives."""
    return Path(directory or DATA) / "Online_Mind2Web.json"


def download(url, token=None):
    """One file over HTTPS, with a token when the source is gated."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
        return response.read()


def fetch_tasks(path=None, directory=None, token=None):
    """The 300 tasks, from a local file, from Hugging Face with a token, else from the mirror."""
    if path is not None:
        return json.loads(Path(path).read_text()), str(path)
    stored = tasks_path(directory)
    if stored.exists():
        return json.loads(stored.read_text()), str(stored)
    token = token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    source = HUGGINGFACE if token else MIRROR
    try:
        payload = download(source, token)
    except urllib.error.HTTPError as error:
        if source is HUGGINGFACE and error.code in {401, 403}:
            logger.warning("Hugging Face refused the token (HTTP %s); falling back to the pinned mirror", error.code)
            payload, source = download(MIRROR), MIRROR
        else:
            raise JevRaError(f"Could not download the Online-Mind2Web task file: HTTP {error.code}") from None
    if source is MIRROR:
        logger.warning("Task file from the pinned mirror, task revision %s, not the gated file", MIRROR_REVISION)
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(payload)
    return json.loads(stored.read_text()), source


def select(tasks, count=None, level=None, ids=()):
    """The tasks to run: the named ones, or a level-balanced slice taken in file order."""
    if ids:
        wanted = list(ids)
        found = {task["task_id"]: task for task in tasks}
        missing = [name for name in wanted if name not in found]
        if missing:
            raise JevRaError(f"No such Online-Mind2Web task: {', '.join(missing)}")
        return [found[name] for name in wanted]
    pool = [task for task in tasks if level is None or task.get("level") == level]
    if count is None or count >= len(pool):
        return pool
    # A ten-task smoke drawn in file order would be whatever the file happens to start with.
    # Taking one level at a time keeps easy, medium and hard in it, and stays deterministic.
    buckets = [[task for task in pool if task.get("level") == name] for name in LEVELS]
    buckets = [bucket for bucket in buckets if bucket] or [pool]
    chosen, index = [], 0
    while len(chosen) < count:
        bucket = buckets[index % len(buckets)]
        position = index // len(buckets)
        if position < len(bucket):
            chosen.append(bucket[position])
        elif all(index // len(buckets) >= len(one) for one in buckets):
            break
        index += 1
    return chosen[:count]


def describe(entry):
    """The factual description of one step, with no reasoning in it."""
    fixed = DESCRIPTIONS.get(entry["operation"])
    if fixed:
        return fixed
    label = entry["label"] or entry["target"]
    if entry["operation"] == "TYPE_TEXT":
        return f"type into {label}"
    if entry["operation"] == "SELECT":
        return f"select {label}"
    return f"click {label}"


def render(entry):
    """One trajectory entry as a Grammar A action string, and the status that mirrors it."""
    verb, shape = VERBS.get(entry["operation"], ("CLICK", "element"))
    status = None if verb == "WAIT" else ("SUCCESS" if entry["landed"] else "FAILED")
    target = "page" if shape == "page" else f"[data-jev-ref='{entry['target']}']"
    body = f"page -> {verb} -> {describe(entry)}" if verb in PAGE_VERBS else f"{verb} {target} -> {describe(entry)}"
    return (f"{body} | {status}" if status else body), status


def submission(task, result, frames):
    """One task's `result.json`, in the v2 schema the benchmark validates against."""
    history = []
    for entry in result["trajectory"]:
        action, status = render(entry)
        history.append(
            {
                "step": entry["step"],
                "screenshot": Path(entry["screenshot_path"]).name,
                "url": entry["url"] or None,
                "action": action,
                "action_status": status,
                "thought": None,
            }
        )
    history.append(
        {
            "step": len(history),
            "screenshot": frames[-1],
            "url": result["final_url"] or None,
            "action": "TASK_COMPLETE",
            "action_status": None,
            "thought": None,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "task": task["confirmed_task"],
        "task_id": task["task_id"],
        # jev-ra has no model that writes prose, and the benchmark asks for factual actions only.
        # An answer here would have to be page text relabelled as the agent's words, so there is none.
        "agent_final_answer": None,
        "reference_length": task["reference_length"],
        "action_history": history,
    }


def finish(adapter, shots):
    """A frame for the terminal step, or the last one already taken when the page is gone."""
    taken = [frame["path"].name for frame in adapter.recorder.frames]
    try:
        return [*taken, adapter.recorder.capture(adapter.agent.observe())["path"].name]
    except Exception as error:
        logger.warning("Could not photograph the final page (%s); reusing the last frame", error)
        return taken or [name.name for name in sorted(Path(shots).iterdir())]


def run_task(task, out, config, max_steps=MAX_STEPS, session=None, decide=None):
    """One live attempt at one task, written out in the submission layout."""
    directory = Path(out) / task["task_id"]
    shots = directory / "trajectory"
    started = time.perf_counter()
    adapter = Adapter(shots, config=config, session=session, decide=decide)
    try:
        result = adapter.run(task["confirmed_task"], max_steps=max_steps, url=task["website"])
        frames = finish(adapter, shots)
    except JevRaError as error:
        logger.error("%s: %s", task["task_id"], error)
        result = {
            "final_url": task["website"],
            "final_answer": None,
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
        frames = [frame["path"].name for frame in adapter.recorder.frames]
    finally:
        adapter.close()
    if result["trajectory"] or frames:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "result.json").write_text(
            json.dumps(submission(task, result, frames), ensure_ascii=False, indent=2) + "\n"
        )
    return {
        "task_id": task["task_id"],
        "level": task.get("level"),
        "website": task["website"],
        "task": task["confirmed_task"],
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
        "final_page_text": result["final_answer"],
        "frames": len(frames),
    }


def judge(out, model=JUDGE_MODEL, api_key=None, threshold=JUDGE_THRESHOLD):
    """WebJudge from the benchmark's own repository, over the trajectories already written."""
    out = Path(out).resolve()
    tasks = sorted(path for path in out.iterdir() if path.is_dir())
    if not tasks:
        raise JevRaError(f"No trajectories to judge under {out}")
    repository = ensure("online-mind2web")
    results = out.parent / (out.name + "-judge")
    # The harness names its output file after the model, and an OpenRouter model name has a slash
    # in it, so the directory that slash implies has to exist before the harness opens the file.
    stem = f"{JUDGE_MODE}_{model}_score_threshold_{threshold}_auto_eval_results.json"
    (results / stem).parent.mkdir(parents=True, exist_ok=True)
    key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise JevRaError("WebJudge needs a key; export OPENROUTER_API_KEY.")
    command = [
        "uv",
        "run",
        "--no-project",
        *[argument for package in JUDGE_PACKAGES for argument in ("--with", package)],
        "python",
        str(HERE / "webjudge_runner.py"),
        "--repository",
        str(repository),
        "--mode",
        JUDGE_MODE,
        "--model",
        model,
        "--trajectories_dir",
        str(out),
        "--api_key",
        key,
        "--output_path",
        str(results),
        "--score_threshold",
        str(threshold),
    ]
    environment = {**os.environ, "OPENAI_BASE_URL": JUDGE_BASE_URL, "OPENAI_API_KEY": key}
    logger.info("Judging %s trajectories with %s via %s", len(tasks), model, JUDGE_BASE_URL)
    done = subprocess.run(
        command,
        cwd=str(repository),
        env=environment,
        timeout=JUDGE_TIMEOUT_S,
        check=False,
        capture_output=True,
        text=True,
    )
    (out.parent / (out.name + "-judge.log")).write_text(done.stdout)
    if done.returncode != 0:
        raise JevRaError(f"WebJudge failed: {(done.stderr or done.stdout).strip()[-800:]}")
    return read_labels(results / stem, [path.name for path in tasks])


def read_labels(path, task_ids):
    """What WebJudge decided per task, and which tasks it never reached."""
    labels = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                labels[row["task_id"]] = int(row.get("predicted_label") or 0)
    return {"labels": labels, "missing": [name for name in task_ids if name not in labels], "results": str(path)}


def report(rows, labels=None):
    """One line per task and one summary line, with the judge's verdict when there is one."""
    lines = []
    for row in rows:
        verdict = "not judged"
        if labels is not None:
            verdict = "PASS" if labels.get(row["task_id"]) else "FAIL"
        lines.append(
            f"{row['task_id']} {row['level'] or '-':6s} {verdict:10s} "
            f"{row['status']}:{row['reason'] or '-'} {row['steps']} steps "
            f"{row['elapsed_ms']} ms ${row['cost']:.4f}"
        )
    cost = sum(row["cost"] for row in rows)
    wall = sum(row["elapsed_ms"] for row in rows)
    if labels is None:
        lines.append(f"{len(rows)} tasks, not judged, ${cost:.4f} agent cost, {wall / 1000:.1f} s wall")
    else:
        passed = sum(1 for row in rows if labels.get(row["task_id"]))
        rate = 100.0 * passed / len(rows) if rows else 0.0
        lines.append(
            f"{passed}/{len(rows)} = {rate:.1f}% by WebJudge, ${cost:.4f} agent cost, {wall / 1000:.1f} s wall"
        )
    return "\n".join(lines)


def parse(argv=None):
    """The command line."""
    parser = argparse.ArgumentParser(description="Run Online-Mind2Web tasks through jev-ra.")
    parser.add_argument("--tasks", type=int, default=10, help="how many tasks to run (default 10)")
    parser.add_argument("--out", required=True, help="directory the submission layout is written to")
    parser.add_argument("--task-id", action="append", default=[], help="run one named task (repeatable)")
    parser.add_argument("--level", choices=LEVELS, help="only tasks of this difficulty")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS, help=f"steps per task (default {MAX_STEPS})")
    parser.add_argument("--tasks-file", help="a local copy of Online_Mind2Web.json")
    parser.add_argument("--judge", action="store_true", help="run WebJudge over the trajectories afterwards")
    parser.add_argument("--judge-only", action="store_true", help="judge an existing --out directory and stop")
    parser.add_argument("--judge-model", default=JUDGE_MODEL, help=f"the WebJudge backbone (default {JUDGE_MODEL})")
    return parser.parse_args(argv)


def main(argv=None):
    """Run the selected tasks, write the submission layout, and judge it when asked."""
    logs.configure({**os.environ, "JEV_RA_LOG_LEVEL": os.environ.get("JEV_RA_LOG_LEVEL") or "INFO"})
    args = parse(argv)
    out = Path(args.out)
    if args.judge_only:
        verdict = judge(out, model=args.judge_model)
        rows = [json.loads(line) for line in (out / "summary.jsonl").read_text().splitlines() if line.strip()]
        print(report(rows, verdict["labels"]))
        return 0
    config = load()
    if not config.api_key:
        raise JevRaError("Online-Mind2Web runs against the live web and needs a jev-ra key.")
    if config.text_model is None:
        logger.warning("No JEV_RA_TEXT_MODEL is set, so every task that needs typing will escalate needs_value")
    tasks, source = fetch_tasks(args.tasks_file)
    chosen = select(tasks, args.tasks, args.level, args.task_id)
    logger.info("Running %s of %s tasks from %s", len(chosen), len(tasks), source)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (out / "summary.jsonl").open("a", encoding="utf-8") as handle:
        for number, task in enumerate(chosen, start=1):
            logger.info("%s/%s %s %s", number, len(chosen), task["task_id"], task["confirmed_task"][:70])
            row = run_task(task, out, config, max_steps=args.max_steps)
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
    labels = judge(out, model=args.judge_model)["labels"] if args.judge else None
    print(report(rows, labels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
