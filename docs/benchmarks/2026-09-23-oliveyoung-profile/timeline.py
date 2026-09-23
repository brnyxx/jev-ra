import functools
import json
import logging
import sys
import time
from pathlib import Path

from jev_ra.agent import Agent
from jev_ra.bench import LIVE_TASKS, measure, serve
from jev_ra.browser import session as session_module
from jev_ra.browser.session import Session
from jev_ra.config import load
from jev_ra.decide.client import DecisionClient

logging.basicConfig(level=logging.WARNING)
task_key = sys.argv[1]
runs = int(sys.argv[2])
out = Path(sys.argv[3])
events = []
t0 = [0.0]
depth = [0]


def stamp():
    return round((time.perf_counter() - t0[0]) * 1000)


def wrap(cls, name, label=None, describe=None):
    original = getattr(cls, name)

    @functools.wraps(original)
    def inner(self, *args, **kwargs):
        start = stamp()
        depth[0] += 1
        try:
            result = original(self, *args, **kwargs)
            return result
        finally:
            depth[0] -= 1
            info = describe(args, kwargs) if describe else ""
            events.append({"at": start, "ms": stamp() - start, "what": label or name, "depth": depth[0], "info": info})

    setattr(cls, name, inner)


def expr_kind(args, kwargs):
    text = args[0] if args else kwargs.get("expression", "")
    if "__jevRaQuiet" in text and "budget_ms" in text and "quiet_ms" in text:
        return "quiet"
    if "location.href !== options.url" in text:
        return "route"
    if "readyState" in text and "load" in text and "budget_ms" in text and "quiet_ms" not in text and "elementFromPoint" not in text:
        return "ready"
    if "elementFromPoint" in text and "shown" in text and "below" in text and "snapshot" not in text and len(text) < 3000:
        return "painted"
    if "autocomplete" in text:
        return "settle+snapshot"
    if "page?.marker" in text:
        return "marker"
    if "pageKey()" in text and "guard(" in text and len(text) < 400:
        return "guard"
    if "max_elements" in text:
        return "snapshot"
    return text[:40]


wrap(Session, "open")
wrap(Session, "load")
wrap(Session, "paint")
wrap(Session, "observe")
wrap(Session, "settle")
wrap(Session, "wait_out")
wrap(Session, "execute")
wrap(Session, "evaluate", describe=expr_kind)
replies = []
original_decide = DecisionClient.decide


def decide_logged(self, state, questions):
    start = stamp()
    reply = original_decide(self, state, questions)
    ops = reply.answers["operation"]["probabilities"]
    top = sorted(ops.items(), key=lambda kv: -kv[1])[:3]
    events.append({"at": start, "ms": stamp() - start, "what": "decide", "depth": depth[0], "info": {"top": [(k, round(v, 2)) for k, v in top], "goal": reply.answers.get("goal_achieved", {}).get("noul"), "prev_ok": reply.answers.get("prev_ok", {}).get("noul"), "url": state["page"]["url"][-40:], "n_el": len(state["elements"])}})
    return reply


DecisionClient.decide = decide_logged

config = load()
client = DecisionClient(config)
task = next(t for t in LIVE_TASKS if t.key == task_key)
rows = []
with serve() as base:
    for attempt in range(runs):
        events.clear()
        session = Session(config)
        try:
            agent = Agent(session=session, config=config, decide=client.decide)
            url = f"{base}/{task.page}" if task.page else task.url
            t0[0] = time.perf_counter()
            row = measure(agent, task, url, task.values, task.max_steps)
        finally:
            session.close()
        row = {k: v for k, v in row.items() if k not in ("text", "elements")}
        row["timeline"] = list(events)
        rows.append(row)
        sys.stdout.write(f"run {attempt + 1}: ok={row['ok']} {row['status']}/{row['reason']} {row['elapsed_ms']} ms decisions={row['decisions']} steps={row['steps']}\n")
        for e in events:
            if e["what"] in ("evaluate",) and e["ms"] < 15:
                continue
            sys.stdout.write(f"   {e['at']:>6} +{e['ms']:>5} {'  ' * e['depth']}{e['what']} {e['info']}\n")
client.close()
out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
