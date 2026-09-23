"""Every kind of interaction in the capability matrix, carried out with scripted decisions."""

import tomllib
from pathlib import Path

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.bench.scripted import scripted

pytestmark = pytest.mark.browser

CATALOG = tomllib.loads((Path(__file__).parent / "fixtures" / "capabilities.toml").read_text())["capability"]


def planned(entry):
    marks = [pytest.mark.xfail(strict=True, reason=entry["gap"])] if "gap" in entry else []
    return pytest.param(entry, id=entry["name"], marks=marks)


def steps(entry):
    return [tuple([*step, None, None][:3]) for step in entry["plan"]]


def ended(result):
    return result.reason if result.status == "escalate" else result.status


def test_every_entry_says_what_it_is_and_how_it_is_proven():
    names = [entry["name"] for entry in CATALOG]
    assert len(names) == len(set(names))
    for entry in CATALOG:
        assert {"name", "pattern", "page", "goal", "check"} <= set(entry)
        assert (Path(__file__).parent / "fixtures" / entry["page"].lstrip("/")).is_file()
        assert "plan" in entry or entry.get("expect", "done") != "done"


@pytest.mark.parametrize("entry", [planned(entry) for entry in CATALOG if "plan" in entry])
def test_the_mechanism_carries_out_the_plan(session, fixture_server, entry):
    agent = Agent(session=session, config=config.load({}), decide=scripted(steps(entry)), prefetch=False)
    result = agent.run(
        entry["goal"],
        values=entry.get("values"),
        max_steps=entry.get("max_steps", 10),
        url=fixture_server + entry["page"],
    )
    assert ended(result) == entry.get("expect", "done")
    assert session.evaluate(f"!!({entry['check']})") is True
    if "downloaded" in entry:
        assert entry["downloaded"] in [item.get("file") for item in result.downloads]
