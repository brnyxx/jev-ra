"""Drive a checkout form from Python, with the decisions asked or scripted.

`uv run python examples/python_api.py --fixtures` runs against the bundled page with no key and no
network. Without the flag it runs against `--url` and needs OPENROUTER_API_KEY.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_ra import Agent
from jev_ra.bench import serve
from jev_ra.bench.scripted import scripted
from jev_ra.config import load

logger = logging.getLogger("python_api")

GOAL = "Place an order for Ada Lovelace at ada@example.com with express shipping."
VALUES = {"name": "Ada Lovelace", "email": "ada@example.com"}
# What the scripted decider would choose, so the example runs without a key.
PLAN = (
    ("TYPE_TEXT", "Full name", "name"),
    ("TYPE_TEXT", "Email", "email"),
    ("SELECT", "Shipping → Express", None),
    ("CLICK", "Place order", None),
)


def place_order(url, decide=None, config=None):
    """Run the checkout goal at `url` and return the Result."""
    with Agent(config=config or load(), decide=decide) as agent:
        return agent.run(GOAL, values=VALUES, url=url)


def on_fixtures(config=None):
    """The same run against the bundled fixture page, with no network at all."""
    with serve() as base:
        return place_order(f"{base}/checkout.html", decide=scripted(PLAN), config=config)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python_api", description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", action="store_true", help="use the bundled page and scripted decisions")
    parser.add_argument("--url", default="https://example.com/checkout")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = on_fixtures() if args.fixtures else place_order(args.url)
    logger.info("%s: %s in %s ms", result.status, result.reason, result.elapsed_ms)
    for step in result.steps:
        logger.info("  %s. %s %s %s", step["n"], step["operation"], step["target_label"], step["text"] or "")
    if result.status != "done":
        logger.info("%s", json.dumps(result.detail, ensure_ascii=False)[:400])
    return 0 if result.status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
