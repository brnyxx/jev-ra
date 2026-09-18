"""Command line entry point. Stateful subcommands share one target through browser-harness."""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .agent import Agent
from .browser import actions
from .browser.session import Session, StalePage
from .config import load, state_path
from .decide.client import DecisionClient, JevError
from .extract import MODES, extract

logger = logging.getLogger(__name__)

SCREENSHOT_DEFAULT = Path("screenshot.jpg")
SUMMARY_TEXT_CHARS = 1500


class SessionMissing(Exception):
    """No stateful session is open."""


def read_state():
    path = state_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        logger.warning("Ignoring unreadable session state at %s", path)
        return None


def write_state(session, url):
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"target_id": session.target_id, "url": url}, indent=2))


def clear_state():
    path = state_path()
    if path.exists():
        path.unlink()


def attach():
    state = read_state()
    if not state:
        raise SessionMissing("No open session. Run `jev-ra open URL` first.")
    try:
        return Session(load(), target_id=state["target_id"])
    except RuntimeError as error:
        clear_state()
        raise SessionMissing(f"The stored session is gone ({error}). Run `jev-ra open URL` again.") from None


def parse_values(pairs):
    values = {}
    for pair in pairs or []:
        name, separator, text = pair.partition("=")
        if not separator or not name:
            raise ValueError(f"--value expects NAME=TEXT, got {pair!r}")
        values[name] = text
    return values


def element_line(element):
    line = " ".join(part for part in (f"[{element['ref']}]", element.get("role"), element.get("label")) if part)
    value = element.get("value")
    return f"{line} · {value}" if value else line


def page_summary(page, session):
    space = actions.build(page, session.max_elements)
    return {
        "url": page.get("url", ""),
        "title": page.get("title", ""),
        "text": page.get("text", "")[:SUMMARY_TEXT_CHARS],
        "elements": len(space.elements),
        "omitted": space.omitted,
    }


def emit(args, data, lines=None):
    stream = sys.stdout
    if getattr(args, "json", False) or lines is None:
        print(json.dumps(data, indent=2, ensure_ascii=False), file=stream)
        return 0
    for line in lines:
        print(line, file=stream)
    return 0


def summary_lines(data):
    return [
        f"{data['title']} — {data['url']}",
        f"{data['elements']} elements" + (f", {data['omitted']} omitted" if data.get("omitted") else ""),
    ]


def result_lines(result):
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
    client = DecisionClient(load())
    return Agent(session=session, config=load(), client=client), client


def cmd_run(args):
    session = Session(load())
    agent, client = agent_for(session)
    try:
        result = agent.run(args.goal, values=parse_values(args.value), max_steps=args.max_steps, url=args.url)
    finally:
        client.close()
        session.close()
    return emit(args, result.as_dict(), result_lines(result.as_dict()))


def cmd_open(args):
    session = Session(load())
    page = session.open(args.url)
    write_state(session, page["url"])
    data = page_summary(page, session)
    return emit(args, data, summary_lines(data))


def cmd_observe(args):
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
    data = extract(attach(), args.mode)
    return emit(args, data, [json.dumps(data, indent=2, ensure_ascii=False)])


def cmd_act(args):
    session = attach()
    agent, client = agent_for(session)
    try:
        result = agent.act(args.instruction, values=parse_values(args.value))
    finally:
        client.close()
    return emit(args, result.as_dict(), result_lines(result.as_dict()))


def step_command(call):
    def handler(args):
        session = attach()
        agent = Agent(session=session, config=load(), decide=no_decision)
        page = call(agent, args)
        data = page_summary(page, session)
        return emit(args, data, summary_lines(data))

    return handler


def no_decision(_state, _questions):
    raise RuntimeError("This command never calls the decision model")


def cmd_screenshot(args):
    session = attach()
    path = Path(args.path) if args.path else SCREENSHOT_DEFAULT
    path.write_bytes(session.screenshot())
    return emit(args, {"path": str(path)}, [str(path)])


def cmd_close(args):
    session = attach()
    session.close()
    clear_state()
    return emit(args, {"ok": True}, ["closed"])


def cmd_mcp(_args):
    from .mcp_server import main as serve

    serve()
    return 0


def add_json(parser):
    parser.add_argument("--json", action="store_true", help="print the raw JSON payload")
    return parser


def build_parser():
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
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except (SessionMissing, JevError, StalePage, LookupError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
