import json
import sys
import time

from jev_ra.browser import actions, snapshot_expression
from jev_ra.browser.session import PAINTED_JS, Session
from jev_ra.config import load
from jev_ra.decide.policy import build_questions, build_state

url = sys.argv[1]
goal = sys.argv[2]
runs = int(sys.argv[3]) if len(sys.argv) > 3 else 2
config = load()


def reading(session):
    page = session.evaluate(snapshot_expression(session.max_elements))
    if not page:
        return None, None
    space = actions.build(page, session.max_elements, goal)
    return page, json.dumps([build_state(page, space, goal), build_questions(space, goal)], ensure_ascii=False)


for attempt in range(runs):
    session = Session(config)
    try:
        t0 = time.perf_counter()
        session.call("Page.navigate", timeout=45, url=url)
        committed = time.perf_counter() - t0
        seen = []
        last_state = None
        while True:
            try:
                ready = session.evaluate("document.readyState")
                painted = session.evaluate(PAINTED_JS)
                page, state = reading(session)
            except Exception as error:
                seen.append((round((time.perf_counter() - t0) * 1000), "err", str(error)[:60]))
                continue
            at = round((time.perf_counter() - t0) * 1000)
            changed = state != last_state
            seen.append((at, ready, painted, "CHANGED" if changed else "same", len(page["elements"]) if page else 0, len(page["text"]) if page else 0))
            last_state = state
            if ready == "complete":
                complete_at = at
                break
        # after complete, keep reading for a second
        end = time.perf_counter() + 1.0
        while time.perf_counter() < end:
            page, state = reading(session)
            at = round((time.perf_counter() - t0) * 1000)
            seen.append((at, "after", "", "CHANGED" if state != last_state else "same", len(page["elements"]), len(page["text"])))
            last_state = state
        print(f"run {attempt+1}: commit {committed*1000:.0f} ms")
        for row in seen:
            print("   ", row)
    finally:
        session.close()
