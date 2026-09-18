"""Command line entry point. Stateful subcommands share one target through browser-harness."""

import argparse
import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .agent import Agent
from .browser import actions
from .browser.chrome import find_browser, profile_dir
from .browser.session import Session
from .config import load, state_path
from .decide.client import DecisionClient
from .errors import JevError, JevRaError, render
from .extract import MODES, extract

logger = logging.getLogger(__name__)

SCREENSHOT_DEFAULT = Path("screenshot.jpg")
SUMMARY_TEXT_CHARS = 1500
SCOPES = ("user", "project", "local")
AGENTS = ("claude", "codex")
MANUAL_CHROME_HINT = """No Chrome answered over CDP and none is installed where jev-ra looks.
Install Chrome, Chromium or Edge, point JEV_RA_CHROME at the binary, or start your own:
  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
    --remote-debugging-port=9222 --user-data-dir="$HOME/.jev-ra-chrome" &
  export BU_CDP_URL=http://127.0.0.1:9222"""
# browser_harness talks to its daemon over a unix socket named under $HOME, and the kernel caps
# that path at ~104 characters. A long temporary HOME fails with "AF_UNIX path too long" before
# any of this matters, and the message says nothing about HOME, so say it here.
SOCKET_PATH_LIMIT = 80
LONG_HOME_HINT = (
    "HOME is {length} characters long ({home}). browser-harness names its daemon "
    "socket under it, and a path over about {limit} characters fails with "
    "'AF_UNIX path too long'. Use a shorter HOME, such as /tmp/jev-ra."
)
DOCTOR_QUESTIONS = {
    "operation": {
        "type": "choice",
        "criteria": {"DONE": "The connectivity check is complete.", "BLOCKED": "Nothing can be decided."},
        "instructions": "Answer DONE. This request only checks that the decision endpoint replies.",
    }
}
DOCTOR_STATE = {
    "goal": "Confirm the decision endpoint answers.",
    "page": {"url": "about:blank", "title": "", "text": "connectivity check"},
    "elements": [],
    "recent_actions": [],
    "values_available": [],
}


class SessionMissing(JevRaError):
    """No stateful session is open."""

    next_step = "Run `jev-ra open URL` first."


class GuideMissing(JevRaError):
    """The packaged agent guide could not be found."""

    next_step = "Reinstall jev-ra, or read AGENTS.md in the repository."


def read_state():
    """The stored session, or None when there is none to reattach to."""
    path = state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        logger.warning("Ignoring unreadable session state at %s", path)
        return None


def write_state(session, url):
    """Remember the target id so later commands reattach to it."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"target_id": session.target_id, "url": url}, indent=2))


def clear_state():
    """Forget the stored session."""
    path = state_path()
    if path.exists():
        path.unlink()


def attach():
    """Reattach to the session `open` left behind."""
    state = read_state()
    if not state:
        raise SessionMissing("No open session.")
    try:
        return Session(load(), target_id=state["target_id"])
    except RuntimeError as error:
        clear_state()
        raise SessionMissing(f"The stored session is gone ({error}).") from None


def parse_values(pairs):
    """Turn repeated `--value NAME=TEXT` into a mapping."""
    values = {}
    for pair in pairs or []:
        name, separator, text = pair.partition("=")
        if not separator or not name:
            raise ValueError(f"--value expects NAME=TEXT, got {pair!r}")
        values[name] = text
    return values


def element_line(element):
    """Render one observed element as `[ref] role label · value`."""
    line = " ".join(part for part in (f"[{element['ref']}]", element.get("role"), element.get("label")) if part)
    value = element.get("value")
    return f"{line} · {value}" if value else line


def page_summary(page, session):
    """The short page summary the navigating commands print."""
    space = actions.build(page, session.max_elements)
    return {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text": page.get("text", "")[:SUMMARY_TEXT_CHARS],
        "elements": len(space.elements),
        "omitted": space.omitted,
    }


def emit(args, data, lines=None):
    """Print the payload as JSON, or the prepared lines."""
    stream = sys.stdout
    if getattr(args, "json", False) or lines is None:
        print(json.dumps(data, indent=2, ensure_ascii=False), file=stream)
        return 0
    for line in lines:
        print(line, file=stream)
    return 0


def summary_lines(data):
    """The human rendering of a page summary."""
    return [
        f"{data['title']} — {data['url']}",
        f"{data['elements']} elements" + (f", {data['omitted']} omitted" if data.get("omitted") else ""),
    ]


def result_lines(result):
    """The human rendering of a run result."""
    lines = [f"{result['status']}: {result['reason']}", f"{result['url']}"]
    for step in result["steps"]:
        text = f" {step['text']!r}" if step.get("text") else ""
        lines.append(
            f"  {step['n']}. {step['operation']} {step['target_label']}{text}"
            f" (p={step['probability']:.2f}, {step['latency_ms']} ms,"
            f" {'changed' if step['page_changed'] else 'no change'})"
        )
    lines.append(
        f"{len(result['steps'])} steps, {result['decisions']} decisions,"
        f" {len(result['text_calls'])} text calls, {result['elapsed_ms']} ms, ${result['cost']:.6f}"
    )
    return lines


def agent_for(session):
    """An agent and the decision client it owns, for one command."""
    client = DecisionClient(load())
    return Agent(session=session, config=load(), client=client), client


def cmd_run(args):
    """Pursue a goal from a URL in a session of its own."""
    session = Session(load())
    agent, client = agent_for(session)
    try:
        result = agent.run(args.goal, values=parse_values(args.value), max_steps=args.max_steps, url=args.url)
    finally:
        client.close()
        session.close()
    return emit(args, result.as_dict(), result_lines(result.as_dict()))


def cmd_open(args):
    """Open a URL and remember the session for later commands."""
    session = Session(load())
    page = session.open(args.url)
    write_state(session, page["url"])
    data = page_summary(page, session)
    return emit(args, data, summary_lines(data))


def cmd_observe(args):
    """List the controls and text of the open page."""
    session = attach()
    page = session.observe()
    space = actions.build(page, args.max_elements or session.max_elements)
    data = {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text": page.get("text", ""),
        "elements": [element_line(element) for element in space.elements],
        "omitted": space.omitted,
    }
    return emit(args, data, [f"{data['title']} — {data['url']}", *data["elements"]])


def cmd_extract(args):
    """Pull structured data out of the open page."""
    data = extract(attach(), args.mode)
    return emit(args, data, [json.dumps(data, indent=2, ensure_ascii=False)])


def cmd_act(args):
    """Take one decided step on the open page."""
    session = attach()
    agent, client = agent_for(session)
    try:
        result = agent.act(args.instruction, values=parse_values(args.value))
    finally:
        client.close()
    return emit(args, result.as_dict(), result_lines(result.as_dict()))


def step_command(call):
    """Wrap a direct browser call as a CLI handler."""

    def handler(args):
        """Run the wrapped browser call and print the page it left behind."""
        session = attach()
        agent = Agent(session=session, config=load(), decide=no_decision)
        page = call(agent, args)
        data = page_summary(page, session)
        return emit(args, data, summary_lines(data))

    return handler


def no_decision(_state, _questions):
    """Guard for commands that must never reach the decision model."""
    raise RuntimeError("This command never calls the decision model")


def cmd_screenshot(args):
    """Save a JPEG of the open page's viewport."""
    session = attach()
    path = Path(args.path) if args.path else SCREENSHOT_DEFAULT
    path.write_bytes(session.screenshot())
    return emit(args, {"path": str(path)}, [str(path)])


def cmd_close(args):
    """Close the session `open` left behind."""
    session = attach()
    session.close()
    clear_state()
    return emit(args, {"ok": True}, ["closed"])


def server_command(which=None):
    """How the agent should start the server: the installed entry point, else uv, else npm."""
    which = which or shutil.which
    if which("jev-ra"):
        return ["jev-ra", "mcp"]
    if which("uvx"):
        return ["uvx", "jev-ra", "mcp"]
    if which("npx"):
        return ["npx", "-y", "jev-ra", "mcp"]
    return ["uvx", "jev-ra", "mcp"]


def install_argv(agent, scope, config, which=None):
    """The exact argv to exec. The key travels as a value here and is never printed."""
    command = server_command(which)
    if agent == "claude":
        argv = ["claude", "mcp", "add", "jev-ra", "-s", scope]
        flag = "-e"
    else:
        argv = ["codex", "mcp", "add", "jev-ra"]
        flag = "--env"
    if config.api_key and config.key_variable and config.key_variable != "config.json":
        argv += [flag, f"{config.key_variable}={config.api_key}"]
    return [*argv, "--", *command]


def install_display(argv, key_variable):
    """The same command with the key replaced by a shell reference to the variable it came from."""
    shown = [
        f"{key_variable}=${key_variable}" if key_variable and part.startswith(f"{key_variable}=") else part
        for part in argv
    ]
    return shlex.join(shown).replace(f"'{key_variable}=${key_variable}'", f'{key_variable}="${key_variable}"')


def redact(text, secret):
    """Remove a secret from text a subprocess may have echoed back."""
    if not secret:
        return text
    return text.replace(secret, "[redacted]")


def cmd_install(args):
    """Register jev-ra as an MCP server with a coding agent."""
    config = load()
    argv = install_argv(args.agent, args.scope, config)
    display = install_display(argv, config.key_variable)
    source = (
        f"forwarding {config.key_variable}"
        if config.api_key and config.key_variable != "config.json"
        else "no key variable to forward; set OPENROUTER_API_KEY before starting the server"
    )
    if shutil.which(argv[0]) is None:
        lines = [f"{argv[0]} is not on PATH. Run this once it is installed:", f"  {display}", source]
        return emit(args, {"installed": False, "command": display, "key_source": source}, lines) or 1
    finished = subprocess.run(argv, capture_output=True, text=True)
    output = redact((finished.stdout + finished.stderr).strip(), config.api_key)
    lines = [f"  {display}", source, output] if output else [f"  {display}", source]
    report = {
        "installed": finished.returncode == 0,
        "command": display,
        "key_source": source,
        "output": output,
    }
    emit(args, report, lines)
    return finished.returncode


SOURCE_NOTES = {
    "BU_CDP_URL": "the Chrome you pointed BU_CDP_URL at",
    "reused": "the automation Chrome already running on the jev-ra profile",
    "launched": "a Chrome jev-ra launched on its own profile",
}


def chrome_hint(binary=None, home=None):
    """What to tell someone whose Chrome could not be reached."""
    home = os.environ.get("HOME", "") if home is None else home
    lines = []
    if len(home) > SOCKET_PATH_LIMIT:
        lines.append(LONG_HOME_HINT.format(length=len(home), home=home, limit=SOCKET_PATH_LIMIT))
    if binary:
        lines.append(
            f"No Chrome is running yet. jev-ra will launch its own on first use, using {binary} "
            f"on the profile at {profile_dir()}. Nothing to set up; run a command and it starts."
        )
    else:
        lines.append(MANUAL_CHROME_HINT)
    return "\n".join(lines)


def chrome_check(config):
    """Whether a Chrome can be reached, and which one it was."""
    try:
        session = Session(config)
    except Exception as error:
        return False, str(error), None
    try:
        session.open("about:blank")
        note = SOURCE_NOTES.get(session.chrome_source, session.chrome_source)
        viewport = f"{config.viewport.width}x{config.viewport.height}"
        return True, f"{session.cdp_url} ({note}), viewport {viewport}", session.chrome_source
    except Exception as error:
        return False, str(error), None
    finally:
        session.close()


def cmd_doctor(args):
    """Check the key, the route, Chrome and one live decision."""
    config = load()
    report = {
        "key": bool(config.api_key),
        "key_variable": config.key_variable,
        "endpoint": config.endpoint,
        "model": config.model,
        "provider": config.provider,
        "text_model": config.text_model.model if config.text_model else None,
    }
    lines = [
        f"key: {'found in ' + str(config.key_variable) if config.api_key else 'missing'}",
        f"endpoint: {config.endpoint} ({config.provider})",
        f"model: {config.model}",
        f"text model: {report['text_model'] or 'none (host supplies values)'}",
    ]
    if not config.api_key:
        lines.append("Set JEV_RA_API_KEY, TYPESAFE_API_KEY or OPENROUTER_API_KEY, then run `jev-ra doctor` again.")
        emit(args, report, lines)
        return 1
    ok, detail, source = chrome_check(config)
    report["chrome"] = {"ok": ok, "detail": detail, "source": source}
    lines.append(f"chrome: {'ok, ' + detail if ok else 'unreachable'}")
    if not ok:
        lines.append(chrome_hint(find_browser()))
    client = DecisionClient(config)
    started = time.perf_counter()
    try:
        reply = client.decide(DOCTOR_STATE, DOCTOR_QUESTIONS)
    except JevError as error:
        report["decision"] = {"ok": False, "error": str(error)}
        lines.append(f"decision: failed ({error})")
        emit(args, report, lines)
        return 1
    finally:
        client.close()
    latency_ms = round((time.perf_counter() - started) * 1000)
    report["decision"] = {
        "ok": True,
        "latency_ms": latency_ms,
        "model": reply.model,
        "choice": reply.answers["operation"]["choice"],
        "cost": reply.cost,
    }
    lines.append(f"decision: {reply.answers['operation']['choice']} in {latency_ms} ms via {reply.model}")
    emit(args, report, lines)
    return 0 if ok else 1


SUMMARY_COLUMNS = (
    "task",
    "runs",
    "successes",
    "success_rate",
    "median_ms",
    "p90_ms",
    "median_steps",
    "median_decisions",
    "median_cost",
    "text_calls",
)
RATIO_COLUMNS = ("task", "jev_ra_ms", "flash_mode_ms", "ratio", "success_rate", "passed")


def summary_line(row):
    """The human rendering of one benchmark summary row."""
    verified = f"{row['successes']}/{row['runs']} verified"
    if not row["median_ms"]:
        return f"  {row['task']}: {verified}; {', '.join(row['failures']) or 'no successful run'}"
    return (
        f"  {row['task']}: {verified}, median {row['median_ms']} ms, p90 {row['p90_ms']} ms,"
        f" {row['median_decisions']} decisions, {row['text_calls']} text calls"
    )


def ratio_line(row):
    """The human rendering of one ratio row."""
    reference = f"{row['flash_mode_ms']} ms" if row["flash_mode_ms"] else "no baseline row"
    ratio = f"{row['ratio']}x" if row["ratio"] else "n/a"
    ours = f"{row['jev_ra_ms']} ms" if row["jev_ra_ms"] else "never verified"
    rate = f"{row['success_rate']:.0%} of {row['runs']} runs"
    return f"  {row['task']}: {ours} / {reference} = {ratio}, {rate}  {'PASS' if row['passed'] else 'FAIL'}"


def cmd_search(args):
    """Search the web and read the best results."""
    from .search import search

    config = load()
    session = Session(config)
    client = DecisionClient(config)
    try:
        payload = search(
            args.query,
            args.goal_flag or args.goal,
            args.max_pages,
            config=config,
            decide=client.decide,
            session=session,
            session_factory=lambda: Session(config),
        )
    finally:
        client.close()
    lines = [f"{payload['query']} — {len(payload['results'])} pages in {payload['elapsed_ms']} ms"]
    for item in payload["results"]:
        title = item.get("title") or item["label"]
        lines.append(f"  {item['rank']}. {title} (answers_goal={item.get('answers_goal', 0):.2f})")
        lines.append(f"     {item.get('url', '')}")
    return emit(args, payload, lines)


def cmd_bench(args):
    """Time the offline fixtures, and the live tasks with --live."""
    from .bench import (
        ACCEPTANCE_RATIO,
        flash_baseline,
        markdown_table,
        profile_rows,
        profile_table,
        ratio_rows,
        run_baseline,
        run_live,
        run_offline,
        summarise,
    )

    config = load()
    runs = args.runs
    offline_runs = run_offline(config, runs=runs)
    offline = summarise(offline_runs)
    payload = {"runs": runs, "offline": offline, "baseline_flash_ms": flash_baseline()}
    lines = [f"offline (scripted decisions, local fixtures, no network), {runs} run(s) each:"]
    lines += [summary_line(row) for row in offline]
    if args.profile and not args.live:
        payload["profile"] = profile_rows(offline_runs)
        lines += ["", "where the time goes (offline):", profile_table(offline_runs)]
    if args.baseline:
        payload["baseline_runs"] = run_baseline(runs)
        lines.append(f"browser-use baseline re-run {runs} time(s); rows appended under docs/benchmarks/")
    if not args.live:
        lines.append("Run `jev-ra bench --live` to measure the live tasks against the recorded baseline.")
        emit(args, payload, lines)
        return 0
    live_runs = run_live(config, runs=runs)
    live = summarise(live_runs)
    rows = ratio_rows(live)
    payload["live"] = live
    payload["ratios"] = rows
    payload["passed"] = all(row["passed"] for row in rows)
    payload["markdown"] = markdown_table(rows, RATIO_COLUMNS)
    lines.append(f"live, {runs} run(s) each, verified on the page:")
    lines += [summary_line(row) for row in live]
    lines.append(f"ratio (jev-ra median / browser-use flash_mode, >= {ACCEPTANCE_RATIO}x to pass):")
    lines += [ratio_line(row) for row in rows]
    lines += ["", markdown_table(live, SUMMARY_COLUMNS), ""]
    if args.profile:
        payload["profile"] = profile_rows(live_runs)
        lines += ["where the time goes:", profile_table(live_runs), ""]
    lines.append("PASS: every task clears the bar" if payload["passed"] else "FAIL: at least one task is short")
    emit(args, payload, lines)
    return 0 if payload["passed"] else 1


CORPUS_COLUMNS = ("task", "family", "runs", "passed", "pass_rate", "median_ms", "decisions", "cost", "why")


def corpus_line(row):
    """The human rendering of one corpus summary row."""
    verdict = f"{row['passed']}/{row['runs']}"
    if row["median_ms"] is None:
        return f"  {row['task']}: {verdict} - {'; '.join(row['why'])}"
    tail = f" - {'; '.join(row['why'])}" if row["why"] else ""
    return f"  {row['task']}: {verdict} in {row['median_ms']} ms, {row['decisions']} decisions{tail}"


def cmd_corpus(args):
    """Run the real-site corpus and report what passed, what escalated and why."""
    from .corpus import PASS_RATE, load_tasks, markdown_table, pass_rate, reasons, run, summarise, write_results

    if args.list:
        tasks = load_tasks()
        rows = [{"name": task.name, "family": task.family, "expect": task.expect} for task in tasks]
        return emit(args, {"tasks": rows}, [f"  {r['family']:<12} {r['name']:<28} {r['expect']}" for r in rows])
    config = load()
    rows = run(config=config, runs=args.runs, family=args.family, name=args.task)
    table = summarise(rows)
    rate = pass_rate(rows)
    histogram = reasons(rows)
    path = write_results(rows)
    payload = {
        "runs": args.runs,
        "attempts": len(rows),
        "pass_rate": rate,
        "passed": rate >= PASS_RATE,
        "tasks": table,
        "escalations": histogram,
        "results": str(path),
        "markdown": markdown_table(table, CORPUS_COLUMNS),
    }
    lines = [f"corpus, {args.runs} run(s) each, {len(rows)} attempts:"]
    lines += [corpus_line(row) for row in table]
    lines += ["", f"pass rate {rate:.0%} (bar is {PASS_RATE:.0%})"]
    if histogram:
        lines.append("failures by reason: " + ", ".join(f"{k} x{v}" for k, v in histogram.items()))
    lines += ["", markdown_table(table, CORPUS_COLUMNS), "", f"rows appended to {path}"]
    lines.append("PASS: the corpus clears the bar" if payload["passed"] else "FAIL: the corpus is under the bar")
    emit(args, payload, lines)
    return 0 if payload["passed"] else 1


def skill_text():
    """The agent guide, from the wheel when installed and from the checkout otherwise."""
    for candidate in (Path(__file__).with_name("AGENTS.md"), Path(__file__).resolve().parents[1] / "AGENTS.md"):
        if candidate.exists():
            return candidate.read_text()
    raise GuideMissing("AGENTS.md is missing from this installation.")


def cmd_skill(args):
    """Print the agent guide, so an agent can save it as its own skill file."""
    text = skill_text()
    if getattr(args, "json", False):
        return emit(args, {"name": "jev-ra", "text": text})
    sys.stdout.write(text)
    return 0


def cmd_mcp(_args):
    """Run the MCP stdio server."""
    from .mcp_server import main as serve

    serve()
    return 0


def add_json(parser):
    """Give a subcommand a --json flag."""
    parser.add_argument("--json", action="store_true", help="print the raw JSON payload")
    return parser


def build_parser():
    """The full command line parser."""
    parser = argparse.ArgumentParser(prog="jev-ra", description="A fast browser-use layer for CLI coding agents.")
    parser.add_argument("--version", action="version", version=f"jev-ra {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = add_json(sub.add_parser("run", help="pursue a goal from a URL until it is done or escalates"))
    run.add_argument("url")
    run.add_argument("goal")
    run.add_argument("--value", action="append", metavar="NAME=TEXT", help="a value the agent may type")
    run.add_argument("--max-steps", type=int, help="override the configured step budget")
    run.set_defaults(handler=cmd_run)

    opened = add_json(sub.add_parser("open", help="open a URL and keep the session for later commands"))
    opened.add_argument("url")
    opened.set_defaults(handler=cmd_open)

    observe = add_json(sub.add_parser("observe", help="list the controls and text of the open page"))
    observe.add_argument("--max-elements", type=int)
    observe.set_defaults(handler=cmd_observe)

    extract_parser = add_json(sub.add_parser("extract", help="pull structured data out of the open page"))
    extract_parser.add_argument("--mode", choices=MODES, default="text")
    extract_parser.set_defaults(handler=cmd_extract)

    act = add_json(sub.add_parser("act", help="take one decided step on the open page"))
    act.add_argument("instruction")
    act.add_argument("--value", action="append", metavar="NAME=TEXT")
    act.set_defaults(handler=cmd_act)

    click = add_json(sub.add_parser("click", help="click one observed element"))
    click.add_argument("ref")
    click.set_defaults(handler=step_command(lambda agent, args: agent.click(args.ref)))

    typed = add_json(sub.add_parser("type", help="type into one observed field"))
    typed.add_argument("ref")
    typed.add_argument("text")
    typed.set_defaults(handler=step_command(lambda agent, args: agent.type(args.ref, args.text)))

    select = add_json(sub.add_parser("select", help="select an observed dropdown option"))
    select.add_argument("ref")
    select.add_argument("option")
    select.set_defaults(handler=step_command(lambda agent, args: agent.select(args.ref, args.option)))

    scroll = add_json(sub.add_parser("scroll", help="scroll the open page"))
    scroll.add_argument("direction", choices=("down", "up"))
    scroll.set_defaults(handler=step_command(lambda agent, args: agent.scroll(args.direction)))

    press = add_json(sub.add_parser("press", help="press Enter, Escape or Tab"))
    press.add_argument("key", choices=("Enter", "Escape", "Tab"))
    press.set_defaults(handler=step_command(lambda agent, args: agent.press(args.key)))

    wait = add_json(sub.add_parser("wait", help="wait a moment and observe again"))
    wait.set_defaults(handler=step_command(lambda agent, _args: agent.wait()))

    screenshot = add_json(sub.add_parser("screenshot", help="save a JPEG of the viewport"))
    screenshot.add_argument("path", nargs="?")
    screenshot.set_defaults(handler=cmd_screenshot)

    close = add_json(sub.add_parser("close", help="close the session kept by `open`"))
    close.set_defaults(handler=cmd_close)

    sub.add_parser("mcp", help="run the MCP stdio server").set_defaults(handler=cmd_mcp)

    skill = add_json(sub.add_parser("skill", help="print the agent guide, for saving as a skill file"))
    skill.set_defaults(handler=cmd_skill)

    install = add_json(sub.add_parser("install", help="register jev-ra as an MCP server with a coding agent"))
    install.add_argument("agent", choices=AGENTS)
    install.add_argument("--scope", choices=SCOPES, default="user", help="claude only")
    install.set_defaults(handler=cmd_install)

    doctor = add_json(sub.add_parser("doctor", help="check the key, the endpoint, Chrome and one live decision"))
    doctor.set_defaults(handler=cmd_doctor)

    search = add_json(sub.add_parser("search", help="search the web and read the best results"))
    search.add_argument("query")
    search.add_argument("goal", nargs="?", help="what the pages have to answer; defaults to the query")
    search.add_argument("--goal", dest="goal_flag", metavar="TEXT", help="what the pages have to answer")
    search.add_argument("--max-pages", type=int, default=3)
    search.set_defaults(handler=cmd_search)

    bench = add_json(sub.add_parser("bench", help="time the offline fixtures, and the live tasks with --live"))
    bench.add_argument("--live", action="store_true", help="also run the live tasks (needs a key)")
    bench.add_argument("--runs", type=int, default=5, help="repeat each task N times (default 5)")
    bench.add_argument("--baseline", action="store_true", help="re-run the recorded browser-use script too")
    bench.add_argument("--profile", action="store_true", help="print where each step's time went")
    bench.set_defaults(handler=cmd_bench)

    corpus = sub.add_parser("corpus", help="run the real-site corpus")
    corpus_sub = corpus.add_subparsers(dest="corpus_command")
    corpus_run = add_json(corpus_sub.add_parser("run", help="run the corpus against the live web"))
    corpus_run.add_argument("--family", help="only this family")
    corpus_run.add_argument("--task", help="only this task")
    corpus_run.add_argument("--runs", type=int, default=3, help="repeat each task N times (default 3)")
    corpus_run.add_argument("--list", action="store_true", help="list the tasks instead of running them")
    corpus_run.set_defaults(handler=cmd_corpus)
    corpus.set_defaults(handler=lambda _args: corpus.print_help() or 0)
    return parser


def main(argv=None):
    """Run one command and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except (JevRaError, LookupError, RuntimeError, ValueError) as error:
        print(render(error), file=sys.stderr)
        return 1
