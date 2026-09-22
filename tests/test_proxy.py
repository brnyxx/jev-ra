"""The egress a launched Chrome is put behind, and what is refused as a proxy."""

from jev_ra import config
from jev_ra.browser import chrome


def launched_argv(monkeypatch, tmp_path, proxy):
    """The command line Chrome would have been started with."""
    argv = []

    class Started:
        pid = 4242

    monkeypatch.setattr(chrome, "browser_version", lambda *_a, **_k: None)
    monkeypatch.setattr(chrome.subprocess, "Popen", lambda command, **_k: argv.extend(command) or Started())
    profile = tmp_path / "profile"
    profile.mkdir()
    chrome.launch("/opt/chrome", profile, proxy=proxy)
    return argv


def test_a_configured_proxy_reaches_the_command_line(monkeypatch, tmp_path):
    argv = launched_argv(monkeypatch, tmp_path, "http://egress.example:8080")
    assert "--proxy-server=http://egress.example:8080" in argv


def test_without_one_no_proxy_flag_is_passed(monkeypatch, tmp_path):
    assert not [flag for flag in launched_argv(monkeypatch, tmp_path, None) if flag.startswith("--proxy-server")]


def test_the_flag_sits_before_whatever_the_caller_added(monkeypatch, tmp_path):
    argv = []

    class Started:
        pid = 1

    monkeypatch.setattr(chrome, "browser_version", lambda *_a, **_k: None)
    monkeypatch.setattr(chrome.subprocess, "Popen", lambda command, **_k: argv.extend(command) or Started())
    profile = tmp_path / "profile"
    profile.mkdir()
    chrome.launch("/opt/chrome", profile, flags=("--caller-added",), proxy="socks5://127.0.0.1:1080")
    assert argv.index("--proxy-server=socks5://127.0.0.1:1080") < argv.index("--caller-added")


def test_the_env_names_the_proxy():
    assert config.load({"JEV_RA_PROXY": "http://egress.example:8080"}).proxy == "http://egress.example:8080"


def test_a_stored_proxy_is_read_too(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"proxy": "socks5://127.0.0.1:1080"}')
    assert config.load({}, path=path).proxy == "socks5://127.0.0.1:1080"


def test_the_environment_outranks_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"proxy": "socks5://127.0.0.1:1080"}')
    assert config.load({"JEV_RA_PROXY": "direct://"}, path=path).proxy == "direct://"


def test_no_proxy_is_the_default():
    assert config.load({}).proxy is None
    assert config.load({"JEV_RA_PROXY": "   "}).proxy is None


def test_a_value_that_would_become_another_flag_is_refused(caplog):
    for refused in ("--headless=new", "http://egress.example:8080 --no-sandbox", "\thttp://a b"):
        assert config.load({"JEV_RA_PROXY": refused}).proxy is None


def test_a_refusal_never_repeats_the_value(caplog):
    with caplog.at_level("WARNING"):
        config.load({"JEV_RA_PROXY": "http://user:secret@egress.example:8080 --no-sandbox"})
    assert "secret" not in caplog.text
    assert "--proxy-server" in caplog.text


def test_a_chrome_that_was_already_running_is_reported_as_unproxied(monkeypatch, caplog):
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: True)
    env = {"BU_CDP_URL": "http://127.0.0.1:9222"}
    with caplog.at_level("WARNING"):
        assert chrome.ensure(env=env, proxy="http://egress.example:8080") == ("http://127.0.0.1:9222", "BU_CDP_URL")
    assert "not used" in caplog.text
