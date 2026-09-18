import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_LOGGING_LEVEL", "warning")

from browser_use import Agent, Browser, ChatOpenAI

TASKS = {
    "wikipedia": (
        "https://en.wikipedia.org/wiki/Main_Page",
        "Find and open the Wikipedia article about Godel incompleteness theorems. Stop once the article page is open.",
    ),
    "flights": (
        "https://www.google.com/travel/flights",
        "Search one-way flights from Zurich to London departing September 20, 2026. "
        "Stop as soon as a list of flight results is visible.",
    ),
    "oliveyoung_sort": (
        "https://www.oliveyoung.co.kr/store/display/getMCategoryList.do?dispCatNo=100000100010014",
        "Change the product list sort order to 신상품순 (newest first). Stop once the sort is applied.",
    ),
}


async def run_one(name, model, flash, max_steps=25):
    url, goal = TASKS[name]
    llm = ChatOpenAI(model=model, base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENAI_API_KEY"])
    browser = Browser(cdp_url=os.environ.get("BU_CDP_URL", "http://127.0.0.1:9222"))
    agent = Agent(task=f"Start at {url}. {goal}", llm=llm, browser=browser, flash_mode=flash, use_vision=False)
    started = time.perf_counter()
    error = None
    history = None
    try:
        history = await asyncio.wait_for(agent.run(max_steps=max_steps), timeout=240)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
    wall_ms = round((time.perf_counter() - started) * 1000)
    row = {"task": name, "model": model, "flash_mode": flash, "wall_ms": wall_ms, "error": error}
    if history is not None:
        row.update(
            steps=history.number_of_steps(),
            is_done=history.is_done(),
            successful=history.is_successful(),
            duration_s=round(history.total_duration_seconds(), 2),
            final_url=(history.urls() or [None])[-1],
            final_result=(history.final_result() or "")[:200],
            actions=history.action_names()[:30],
        )
    try:
        await browser.stop()
    except Exception:
        pass
    return row


async def main():
    model = sys.argv[1]
    flash = sys.argv[2] == "flash"
    tasks = sys.argv[3:] or list(TASKS)
    out = Path(__file__).with_name(f"results_{model.replace('/', '_')}_{'flash' if flash else 'default'}.jsonl")
    for name in tasks:
        row = await run_one(name, model, flash)
        with out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(json.dumps({k: row.get(k) for k in ("task", "wall_ms", "steps", "is_done", "final_url", "error")}, ensure_ascii=False), flush=True)


asyncio.run(main())
