"""A file a click saves is part of what the click did, and the run says so."""

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.bench.scripted import scripted

pytestmark = pytest.mark.browser

PAGE = "/sites/download-report.html"


def link(page, label):
    return next(a for a in page["actions"] if a["label"] == label)


def saved(fixture_server, name):
    return {"file": name, "url": f"{fixture_server}/sites/report.csv", "state": "completed"}


def test_a_link_that_saves_a_file_is_read_back_with_the_name_it_saved_it_under(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    session.act(link(page, "Download CSV"), page)
    assert session.observe()["downloads"] == [saved(fixture_server, "revenue-2026-08.csv")]


def test_each_download_is_told_once_by_the_reading_after_the_input_that_started_it(session, fixture_server):
    page = session.open(fixture_server + PAGE)
    assert "downloads" not in page
    session.act(link(page, "Download CSV"), page)
    page = session.observe()
    session.act(link(page, "Download customers"), page)
    assert session.observe()["downloads"] == [saved(fixture_server, "customers.csv")]


def test_a_run_lists_every_file_it_downloaded(session, fixture_server, downloads_folder):
    plan = [("CLICK", "Download CSV", None)]
    agent = Agent(session=session, config=config.load({}), decide=scripted(plan), prefetch=False)
    result = agent.run("Download the August revenue report.", url=fixture_server + PAGE)
    assert result.status == "done"
    assert result.downloads == [saved(fixture_server, "revenue-2026-08.csv")]
    assert list(downloads_folder.glob("revenue-2026-08*.csv"))
