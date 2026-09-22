"""The browser speaks the locale the operator asked for, whether jev-ra launched it or attached."""

import pytest

from jev_ra import config
from jev_ra.browser import chrome
from jev_ra.browser import session as session_module
from jev_ra.errors import ChromeError


@pytest.fixture
def no_chrome_needed(monkeypatch):
    monkeypatch.setattr(session_module, "ensure_chrome", lambda **_k: ("http://127.0.0.1:9222", "BU_CDP_URL"))
    monkeypatch.setattr(session_module, "ensure_daemon", lambda *_a, **_k: None)
    monkeypatch.setattr(session_module, "verify_attached", lambda *_a, **_k: None)


def recording_cdp(refuse=()):
    calls = []

    def cdp(method, session_id=None, _response_timeout=None, **params):
        calls.append((method, params))
        if method in refuse:
            raise RuntimeError({"code": -32000, "message": "Another locale override is already in effect."})
        if method == "Target.createTarget":
            return {"targetId": "t1"}
        if method == "Target.attachToTarget":
            return {"sessionId": "s1"}
        return {}

    cdp.calls = calls
    return cdp


def argv_of(monkeypatch, tmp_path, locale=None):
    seen = {}

    class Started:
        pid = 4242

    def popen(argv, **_kwargs):
        seen["argv"] = argv
        return Started()

    monkeypatch.setattr(chrome, "browser_version", lambda *_a, **_k: None)
    monkeypatch.setattr(chrome.subprocess, "Popen", popen)
    if locale is None:
        chrome.launch("/opt/chrome", tmp_path / "profile")
    else:
        chrome.launch("/opt/chrome", tmp_path / "profile", locale=locale)
    return seen["argv"]


def test_the_default_locale_is_en_us():
    assert config.load({}).locale == "en-US"
    assert config.DEFAULT_LOCALE == "en-US"


def test_the_environment_sets_the_locale():
    assert config.load({"JEV_RA_LOCALE": "ko-KR"}).locale == "ko-KR"


def test_a_blank_locale_leaves_the_browser_to_the_machine():
    assert config.load({"JEV_RA_LOCALE": ""}).locale == ""
    assert config.load({"JEV_RA_LOCALE": "  "}).locale == ""


def test_the_config_file_sets_the_locale_and_the_environment_wins(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"locale": "ja-JP"}')
    assert config.load({}, path=path).locale == "ja-JP"
    assert config.load({"JEV_RA_LOCALE": "en-GB"}, path=path).locale == "en-GB"


def test_a_launched_chrome_is_told_the_locale_twice(monkeypatch, tmp_path):
    argv = argv_of(monkeypatch, tmp_path)
    assert "--lang=en-US" in argv
    assert "--accept-lang=en-US" in argv


def test_the_launch_flags_carry_the_configured_locale(monkeypatch, tmp_path):
    argv = argv_of(monkeypatch, tmp_path, locale="de-DE")
    assert "--lang=de-DE" in argv
    assert "--accept-lang=de-DE" in argv


def test_a_blank_locale_adds_no_flag_at_all(monkeypatch, tmp_path):
    argv = argv_of(monkeypatch, tmp_path, locale="")
    assert not [flag for flag in argv if flag.startswith(("--lang=", "--accept-lang="))]


def test_ensure_hands_the_locale_to_the_chrome_it_launches(monkeypatch, tmp_path):
    flags = []
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=chrome.PROBE_TIMEOUT_S: False)
    monkeypatch.setattr(chrome, "find_browser", lambda **_k: "/usr/bin/chromium")
    monkeypatch.setattr(chrome, "launch", lambda *_a, **kwargs: flags.append(kwargs.get("locale")))
    monkeypatch.setattr(chrome, "wait_for_port", lambda *_a, **_k: 45000)
    chrome.ensure(env={"XDG_STATE_HOME": str(tmp_path)}, locale="ko-KR")
    assert flags == ["ko-KR"]


def test_an_attached_chrome_is_told_the_locale_over_cdp(monkeypatch, no_chrome_needed):
    cdp = recording_cdp()
    monkeypatch.setattr(session_module, "cdp", cdp)
    session_module.Session(config=config.load({"JEV_RA_LOCALE": "en-US"}))
    assert ("Emulation.setLocaleOverride", {"locale": "en-US"}) in cdp.calls


def test_an_attached_chrome_asks_sites_for_that_language_too(monkeypatch, no_chrome_needed):
    cdp = recording_cdp()
    monkeypatch.setattr(session_module, "cdp", cdp)
    session_module.Session(config=config.load({"JEV_RA_LOCALE": "en-US"}))
    headers = {"headers": {"Accept-Language": "en-US"}}
    assert ("Network.setExtraHTTPHeaders", headers) in cdp.calls


def test_a_blank_locale_sends_no_override(monkeypatch, no_chrome_needed):
    cdp = recording_cdp()
    monkeypatch.setattr(session_module, "cdp", cdp)
    session_module.Session(config=config.load({"JEV_RA_LOCALE": ""}))
    spoken = {"Emulation.setLocaleOverride", "Network.setExtraHTTPHeaders"}
    assert not [method for method, _params in cdp.calls if method in spoken]


def test_a_browser_that_refuses_the_override_is_not_a_session_that_failed(monkeypatch, no_chrome_needed):
    cdp = recording_cdp(refuse=("Emulation.setLocaleOverride",))
    monkeypatch.setattr(session_module, "cdp", cdp)
    opened = session_module.Session(config=config.load({}))
    assert opened.session_id == "s1"
    assert not [method for method, _params in cdp.calls if method == "Target.closeTarget"]
    assert opened.speak("en-US") is False


def test_the_session_refuses_nothing_else_the_browser_refuses(monkeypatch, no_chrome_needed):
    cdp = recording_cdp(refuse=("Emulation.setFocusEmulationEnabled",))
    monkeypatch.setattr(session_module, "cdp", cdp)
    with pytest.raises(ChromeError):
        session_module.Session(config=config.load({}))
