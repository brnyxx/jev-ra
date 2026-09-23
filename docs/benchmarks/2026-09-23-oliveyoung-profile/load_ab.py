import json
import statistics
import sys
import time

from jev_ra.browser import snapshot_expression
from jev_ra.browser.session import PAINTED_JS, PARSED_JS, READY_JS, Session
from jev_ra.config import load

url = sys.argv[1]
pairs = int(sys.argv[2])
config = load()
times = {"plain": [], "glimpse": []}
snap = []
for attempt in range(pairs):
    for mode in (("plain", "glimpse") if attempt % 2 == 0 else ("glimpse", "plain")):
        session = Session(config)
        try:
            session.call("Page.navigate", timeout=45, url="about:blank")
            t0 = time.perf_counter()
            session.call("Page.navigate", timeout=45, url=url)
            if mode == "glimpse":
                state = session.evaluate(f"{PARSED_JS}({json.dumps({'budget_ms': 15000})})", await_promise=True)
                if state == "interactive" and session.evaluate(PAINTED_JS):
                    s0 = time.perf_counter()
                    session.evaluate(snapshot_expression(250))
                    snap.append(round((time.perf_counter() - s0) * 1000))
            while session.evaluate(f"{READY_JS}({json.dumps({'budget_ms': 15000})})", await_promise=True) != "complete":
                pass
            times[mode].append(round((time.perf_counter() - t0) * 1000))
        finally:
            session.close()
for mode, values in times.items():
    print(mode, values, "median", statistics.median(values))
print("glimpse snapshot ms", snap)
