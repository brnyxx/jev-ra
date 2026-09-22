"""A named profile is its own Chrome user-data-dir, so a login done once on it stays."""

import json

import pytest

from jev_ra import cli, config
from jev_ra.browser import chrome
from jev_ra.browser import session as session_module
from jev_ra.errors import ChromeError
from jev_ra.mcp_server import Browser, build_server
from tests.test_agent import FakeSession
from tests.test_mcp_server import call, payload, server_with


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("JEV_RA_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    return {"XDG_STATE_HOME": str(tmp_path)}


def test_the_default_profile_is_where_it_has_always_been(tmp_path):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    assert chrome.profile_dir(env) == tmp_path / "jev-ra" / "chrome-profile"
    assert chrome.profile_dir(env, chrome.DEFAULT_PROFILE) == chrome.profile_dir(env)


def test_a_named_profile_gets_a_directory_of_its_own(tmp_path):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    work = chrome.profile_dir(env, "work")
    assert work == tmp_path / "jev-ra" / "chrome-profiles" / "work"
    assert work != chrome.profile_dir(env, "home")
    assert work != chrome.profile_dir(env)


def test_a_profile_name_cannot_escape_the_state_directory(tmp_path):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    for name in ("..", "../../etc", "a/b", "a\\b", "", "  ", "a b"):
        with pytest.raises(ChromeError, match="profile name"):
            chrome.profile_dir(env, name)


def test_a_named_profile_is_launched_on_its_own_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    monkeypatch.setattr(chrome, "find_browser", lambda **_k: "/opt/chrome")
    launched = []
    monkeypatch.setattr(chrome, "launch", lambda binary, path, viewport: launched.append(path))
    monkeypatch.setattr(chrome, "wait_for_port", lambda *_a, **_k: 45001)
    env = {"XDG_STATE_HOME": str(tmp_path)}
    assert chrome.ensure(env=env, profile="work") == ("http://127.0.0.1:45001", "launched")
    assert launched == [tmp_path / "jev-ra" / "chrome-profiles" / "work"]
    assert env["BU_CDP_URL"] == "http://127.0.0.1:45001"


def test_a_named_profile_reuses_the_chrome_already_on_it(monkeypatch, tmp_path):
    profile = tmp_path / "jev-ra" / "chrome-profiles" / "work"
    profile.mkdir(parents=True)
    (profile / chrome.PORT_FILE).write_text("41999\n")
    monkeypatch.setattr(chrome, "alive", lambda url, timeout=2.0: url == "http://127.0.0.1:41999")
    monkeypatch.setattr(chrome, "launch", lambda *_a, **_k: pytest.fail("must not launch"))
    env = {"XDG_STATE_HOME": str(tmp_path)}
    assert chrome.ensure(env=env, profile="work") == ("http://127.0.0.1:41999", "reused")


def test_a_named_profile_is_not_overruled_by_bu_cdp_url(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    monkeypatch.setattr(chrome, "find_browser", lambda **_k: "/opt/chrome")
    monkeypatch.setattr(chrome, "launch", lambda *_a, **_k: None)
    monkeypatch.setattr(chrome, "wait_for_port", lambda *_a, **_k: 45002)
    env = {"XDG_STATE_HOME": str(tmp_path), "BU_CDP_URL": "http://127.0.0.1:9222"}
    # The whole point of asking for a profile is which cookie jar the run gets, so a named
    # profile outranks the ambient Chrome the default profile would have reused.
    assert chrome.ensure(env=env, profile="work") == ("http://127.0.0.1:45002", "launched")
    assert chrome.ensure(env=env) == ("http://127.0.0.1:45002", "BU_CDP_URL")


def test_a_daemon_holding_another_chrome_is_refused_rather_than_driven():
    with pytest.raises(ChromeError, match="another Chrome"):
        chrome.verify_attached(
            "http://127.0.0.1:41999",
            targets=lambda: {"targetInfos": [{"targetId": "aaa"}]},
            listed=lambda _url: {"bbb"},
        )


def one_target():
    return {"targetInfos": [{"targetId": "a"}]}


def test_every_session_is_checked_against_the_browser_the_daemon_holds(monkeypatch):
    # The default profile is as easy to misdrive as a named one: the daemon attached to whichever
    # Chrome came first, and nothing else in the process would notice.
    checked = []
    monkeypatch.setattr(session_module, "ensure_chrome", lambda **_k: ("http://127.0.0.1:1", "launched"))
    monkeypatch.setattr(session_module, "ensure_daemon", lambda: None)
    monkeypatch.setattr(session_module, "verify_attached", checked.append)
    monkeypatch.setattr(session_module, "chrome_ready", lambda: None)
    monkeypatch.setattr(session_module, "cdp", lambda *_a, **_k: {"targetId": "t", "sessionId": "s"})
    session_module.Session(config.load({}))
    assert checked == ["http://127.0.0.1:1"]


def test_an_unanswerable_probe_never_blocks_a_run():
    url = "http://127.0.0.1:41999"
    chrome.verify_attached(url, targets=lambda: {"targetInfos": []}, listed=lambda _url: {"bbb"})
    chrome.verify_attached(url, targets=one_target, listed=lambda _url: None)
    chrome.verify_attached(url, targets=one_target, listed=lambda _url: {"a", "b"})


ASKED = []


class Recorded(session_module.Session):
    """A Session that records which profile it asked Chrome for, without opening one."""

    def __init__(self, config=None, target_id=None, profile=None, **_kwargs):
        ASKED.append(profile)
        self.profile = profile
        self.max_elements = 250
        self.target_id = target_id or "t1"
        self.cache = {}

    def open(self, url):
        return {"url": url, "title": "", "text": "", "elements": [], "actions": [], "omitted": 0}

    def close(self):
        return None


@pytest.fixture
def recorded(monkeypatch):
    ASKED.clear()
    monkeypatch.setattr(cli, "Session", Recorded)
    return ASKED


def test_the_cli_passes_the_named_profile_to_the_session(state, recorded, capsys):
    assert cli.main(["open", "http://127.0.0.1/page", "--profile", "work"]) == 0
    assert recorded == ["work"]
    capsys.readouterr()


def test_the_open_session_remembers_its_profile_so_later_commands_land_on_it(state, recorded, capsys):
    cli.main(["open", "http://127.0.0.1/page", "--profile", "work"])
    stored = json.loads(config.state_path(state).read_text())
    assert stored["profile"] == "work"
    cli.attach()
    assert recorded == ["work", "work"]
    capsys.readouterr()


def test_a_session_opened_without_a_profile_stores_none(state, recorded, capsys):
    cli.main(["open", "http://127.0.0.1/page"])
    assert json.loads(config.state_path(state).read_text())["profile"] is None
    assert recorded == [None]
    capsys.readouterr()


def test_the_run_command_takes_a_profile_too():
    args = cli.build_parser().parse_args(["run", "http://127.0.0.1/p", "book it", "--profile", "work"])
    assert args.profile == "work"
    assert cli.build_parser().parse_args(["search", "q", "--profile", "work"]).profile == "work"
    assert cli.build_parser().parse_args(["open", "http://127.0.0.1/p"]).profile is None


def test_browser_open_takes_a_profile_and_opens_the_session_on_it():
    asked = []

    def factory(profile=None):
        asked.append(profile)
        return FakeSession()

    browser = Browser(config=config.load({}), session_factory=factory)
    server = build_server(browser)
    assert payload(call(server, "browser_open", url="http://127.0.0.1/form.html", profile="work"))["elements"]
    assert asked == ["work"]
    assert browser.profile == "work"


def test_a_second_profile_on_one_server_is_refused_with_the_one_it_is_on():
    server, browser, _session = server_with()
    call(server, "browser_open", url="http://127.0.0.1/form.html", profile="work")
    refused = call(server, "browser_open", url="http://127.0.0.1/form.html", profile="home")
    assert refused.is_error
    assert "work" in refused.content[0].text
    assert not call(server, "browser_open", url="http://127.0.0.1/form.html").is_error
    assert browser.profile == "work"
