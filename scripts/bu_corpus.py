"""Run the real-site corpus through browser-use, judged by the same verify specs as jev-ra.

Usage: uv run --no-project --with browser-use==0.13.10 --with-editable . python scripts/bu_corpus.py \
           <model> <flash|default> <out.jsonl> [runs] [task ...]

Needs OPENAI_API_KEY (OpenRouter key) for browser-use, and BU_CDP_URL for a Chrome both sides
share. The final page is read through jev-ra's own snapshot on the same Chrome, so `corpus.check`
judges both agents on identical evidence.
"""

import asyncio
import contextlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "warning")

from browser_use import Agent, Browser, ChatOpenAI

from jev_ra.browser.session import Session
from jev_ra.config import load
from jev_ra.corpus import TEXT_CHARS, check, load_tasks

TIMEOUT_S = 240


def goal_text(task):
    values = "".join(f" Use {key}: {value}." for key, value in (task.values or {}).items())
    return f"Start at {task.url}. {task.goal}{values} Stop as soon as it is done."


def last_page_target(cdp_url):
    """The target id of the page browser-use last worked in: the newest page target."""
    import urllib.request

    with urllib.request.urlopen(f"{cdp_url}/json/list", timeout=5) as response:
        targets = json.load(response)
    pages = [
        t for t in targets if t.get("type") == "page" and not t.get("url", "").startswith(("chrome", "about:blank"))
    ]
    if not pages:
        return None
    return pages[0]["id"]


def final_page(cdp_url):
    """The page browser-use left behind, read the way jev-ra reads its own final page."""
    target = last_page_target(cdp_url)
    if target is None:
        return None
    os.environ["BU_CDP_URL"] = cdp_url
    session = Session(load(), target_id=target)
    try:
        page = session.observe()
        text = page.get("doc_text") or page.get("text") or ""
        return {"url": page.get("url"), "text": text[:TEXT_CHARS], "elements": page.get("elements") or []}
    finally:
        # Detach only; the tab is browser-use's, and it stops its own browser.
        session.target_id = None


async def run_one(task, model, flash, cdp_url):
    llm = ChatOpenAI(model=model, base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENAI_API_KEY"])
    browser = Browser(cdp_url=cdp_url)
    agent = Agent(task=goal_text(task), llm=llm, browser=browser, flash_mode=flash, use_vision=False)
    started = time.perf_counter()
    error = None
    history = None
    try:
        history = await asyncio.wait_for(agent.run(max_steps=task.max_steps or 25), timeout=TIMEOUT_S)
    except Exception as exc:  # browser-use raises many kinds; the row records them all
        error = f"{type(exc).__name__}: {exc}"[:300]
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    row = {
        "task": task.name,
        "family": task.family,
        "agent": "browser-use",
        "model": model,
        "flash_mode": flash,
        "elapsed_ms": elapsed_ms,
        "error": error,
        "expect": task.expect,
    }
    if history is not None:
        row.update(
            steps=history.number_of_steps(),
            is_done=history.is_done(),
            successful=history.is_successful(),
            final_url=(history.urls() or [None])[-1],
            final_result=(history.final_result() or "")[:200],
            actions=history.action_names()[:40],
        )
    # Judge on the page as it stands, with jev-ra's verify spec, before the agent's browser is stopped.
    page = None
    try:
        page = final_page(cdp_url)
    except Exception as exc:
        row["judge_error"] = f"{type(exc).__name__}: {exc}"[:200]
    if page is None and history is not None and (history.urls() or [None])[-1]:
        # browser-use closes its tab inside agent.run(), so the page is judged from what the agent
        # itself read: every extracted_content chunk and its final result. This favours browser-use
        # (it is judged on text it chose to keep), so a FAIL here is a FAIL by its own account.
        text = "\n".join(c for c in history.extracted_content() if c) + "\n" + (history.final_result() or "")
        page = {"url": (history.urls() or [None])[-1], "text": text[:TEXT_CHARS], "elements": []}
        row["judged_from"] = "history"
    with contextlib.suppress(Exception):
        await browser.stop()
    if page is not None:
        row["url"] = page["url"]
        if task.expect == "done":
            ok, why = check(task.verify, page)
            row["passed"] = bool(ok and error is None)
            row["why"] = None if row["passed"] else (why if error is None else error)
        else:
            # An escalation task passes for browser-use only if it stopped without pretending it did the job.
            done = bool(history and history.is_successful())
            row["passed"] = not done
            row["why"] = None if row["passed"] else "claimed success on a task that needs a value or is blocked"
    else:
        row["passed"] = False
        row["why"] = row.get("judge_error") or error or "no final page"
    return row


async def main():
    model, mode, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    runs = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    names = set(sys.argv[5:])
    cdp_url = os.environ.get("BU_CDP_URL", "http://127.0.0.1:9333")
    tasks = [t for t in load_tasks() if not names or t.name in names]
    passed = total = 0
    with out.open("a") as handle:
        for attempt in range(runs):
            for task in tasks:
                row = await run_one(task, model, mode == "flash", cdp_url)
                row["run"] = attempt + 1
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                total += 1
                passed += bool(row["passed"])
                print(
                    f"{task.name}: {'PASS' if row['passed'] else 'FAIL'} {row['elapsed_ms']} ms {row.get('why') or ''}",
                    flush=True,
                )
    print(f"browser-use {model} {mode}: {passed}/{total}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
