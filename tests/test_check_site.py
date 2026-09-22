"""A site check says what the site answered, with the Agent's own verdict on it."""

from pathlib import Path

import pytest

from jev_ra.errors import ChromeError
from tests.test_examples import load

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def check_site():
    return load(ROOT / "scripts" / "check_site.py", "check_site")


def row(**overrides):
    base = {
        "requested": "https://a/",
        "url": "https://b/",
        "status": 200,
        "wall": "the page answered with 'access denied'",
        "chars": 42,
        "controls": 1,
    }
    return {**base, **overrides}


def test_a_task_name_is_its_address_and_a_url_is_itself(check_site):
    assert check_site.address("gov_kr_search") == ("gov_kr_search", "https://plus.gov.kr/")
    assert check_site.address("https://example.com/x") == ("https://example.com/x", "https://example.com/x")


def test_an_unknown_task_is_named_back(check_site):
    with pytest.raises(SystemExit, match="unknown corpus task"):
        check_site.address("wikipedia_lookup")


def test_the_report_prints_status_landing_wall_and_controls(check_site):
    text = "\n".join(check_site.report("a", row()))
    assert "a: https://a/" in text
    assert "status: 200" in text
    assert "landed on: https://b/" in text
    assert "wall: the page answered with 'access denied'" in text
    assert "page: 42 chars, 1 controls" in text


def test_an_unknown_status_reads_as_unknown_and_no_wall_as_none(check_site):
    text = "\n".join(check_site.report("a", row(status=None, wall="")))
    assert "status: unknown" in text and "wall: none" in text


def test_a_failed_open_is_an_exit_one(monkeypatch, capsys, check_site):
    def boom(_url, **_kwargs):
        raise ChromeError("No Chrome answered at BU_CDP_URL.")

    monkeypatch.setattr(check_site, "open_once", boom)
    assert check_site.main(["https://example.com/"]) == 1
    assert "BU_CDP_URL" in capsys.readouterr().err


def test_a_served_address_is_an_exit_zero(monkeypatch, capsys, check_site):
    monkeypatch.setattr(check_site, "open_once", lambda _url, **_kwargs: row())
    assert check_site.main(["gov_kr_search"]) == 0
    assert "gov_kr_search" in capsys.readouterr().out


@pytest.mark.browser
def test_a_walled_fixture_is_reported_as_a_wall(check_site, session, fixture_server):
    checked = check_site.open_once(f"{fixture_server}/sites/bot-wall.html", session=session)
    assert checked["status"] == 200
    assert "access denied" in checked["wall"]
    assert checked["controls"] >= 1


@pytest.mark.browser
def test_an_ordinary_fixture_is_not_a_wall_and_offers_its_control(check_site, session, fixture_server):
    checked = check_site.open_once(f"{fixture_server}/sites/static.html", session=session)
    assert checked["status"] == 200
    assert checked["wall"] == ""
    assert checked["controls"] == 1
