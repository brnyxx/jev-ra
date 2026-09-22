import subprocess
import sys

import pytest

from jev_ra.browser import chrome


def fake_exists(present):
    return lambda path: str(path) in present


def test_macos_paths_are_tried_in_order():
    present = {
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    }
    found = chrome.find_browser("darwin", env={}, exists=fake_exists(present), which=lambda _c: None)
    assert found == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def test_linux_and_windows_paths_are_recognised():
    linux = chrome.find_browser("linux", env={}, exists=fake_exists({"/usr/bin/chromium"}), which=lambda _c: None)
    assert linux == "/usr/bin/chromium"
    windows = chrome.find_browser(
        "win32",
        env={},
        exists=fake_exists({r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"}),
        which=lambda _c: None,
    )
    assert windows.endswith("msedge.exe")


def test_path_lookup_is_the_fallback():
    def which(command):
        return f"/opt/{command}" if command == "chromium" else None

    found = chrome.find_browser("linux", env={}, exists=fake_exists(set()), which=which)
    assert found == "/opt/chromium"


def test_nothing_found_returns_none():
    assert chrome.find_browser("linux", env={}, exists=fake_exists(set()), which=lambda _c: None) is None


def test_an_explicit_binary_wins_and_must_exist():
    env = {"JEV_RA_CHROME": "/opt/my-chrome"}
    assert chrome.find_browser("linux", env=env, exists=fake_exists({"/opt/my-chrome"}), which=lambda _c: None) == (
        "/opt/my-chrome"
    )
    with pytest.raises(chrome.ChromeError, match="does not exist"):
        chrome.find_browser("linux", env=env, exists=fake_exists(set()), which=lambda _c: None)


def test_the_profile_follows_xdg_state_home(tmp_path):
    env = {"XDG_STATE_HOME": str(tmp_path)}
    assert chrome.profile_dir(env) == tmp_path / "jev-ra" / "chrome-profile"


def test_the_port_file_is_parsed_and_bad_ones_are_ignored(tmp_path):
    (tmp_path / chrome.PORT_FILE).write_text("54321\n/devtools/browser/abc\n")
    assert chrome.read_port(tmp_path) == 54321
    (tmp_path / chrome.PORT_FILE).write_text("not a port\n")
    assert chrome.read_port(tmp_path) is None
    (tmp_path / chrome.PORT_FILE).write_text("")
    assert chrome.read_port(tmp_path) is None
    assert chrome.read_port(tmp_path / "missing") is None


def test_a_live_bu_cdp_url_wins_over_everything(monkeypatch):
    monkeypatch.setattr(chrome, "alive", lambda url, timeout=2.0: url == "http://127.0.0.1:9222")
    monkeypatch.setattr(chrome, "launch", lambda *_a, **_k: pytest.fail("must not launch"))
    url, source = chrome.ensure(env={"BU_CDP_URL": "http://127.0.0.1:9222"})
    assert (url, source) == ("http://127.0.0.1:9222", "BU_CDP_URL")


def test_a_live_profile_port_is_reused(monkeypatch, tmp_path):
    profile = tmp_path / "jev-ra" / "chrome-profile"
    profile.mkdir(parents=True)
    (profile / chrome.PORT_FILE).write_text("41234\n")
    monkeypatch.setattr(chrome, "alive", lambda url, timeout=2.0: url == "http://127.0.0.1:41234")
    monkeypatch.setattr(chrome, "launch", lambda *_a, **_k: pytest.fail("must not launch"))
    env = {"XDG_STATE_HOME": str(tmp_path)}
    url, source = chrome.ensure(env=env)
    assert (url, source) == ("http://127.0.0.1:41234", "reused")
    assert env["BU_CDP_URL"] == url


def test_a_dead_profile_port_leads_to_a_launch(monkeypatch, tmp_path):
    profile = tmp_path / "jev-ra" / "chrome-profile"
    profile.mkdir(parents=True)
    (profile / chrome.PORT_FILE).write_text("41234\n")
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    monkeypatch.setattr(chrome, "find_browser", lambda **_k: "/opt/chrome")
    launched = []
    monkeypatch.setattr(chrome, "launch", lambda binary, path, viewport: launched.append(binary))
    monkeypatch.setattr(chrome, "wait_for_port", lambda *_a, **_k: 45000)
    env = {"XDG_STATE_HOME": str(tmp_path)}
    assert chrome.ensure(env=env) == ("http://127.0.0.1:45000", "launched")
    assert launched == ["/opt/chrome"]


def test_no_browser_anywhere_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    monkeypatch.setattr(chrome, "find_browser", lambda **_k: None)
    with pytest.raises(chrome.ChromeError, match="No Chrome, Chromium or Edge found"):
        chrome.ensure(env={"XDG_STATE_HOME": str(tmp_path)})


def test_launching_can_be_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    with pytest.raises(chrome.ChromeError, match="launching is disabled"):
        chrome.ensure(env={"XDG_STATE_HOME": str(tmp_path)}, allow_launch=False)


def test_a_chrome_that_dies_before_opening_a_port_is_reported(tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    dead.wait()
    with pytest.raises(chrome.ChromeError, match="exited with code 3"):
        chrome.wait_for_port(tmp_path, dead, timeout=2.0)


@pytest.mark.browser
def test_a_launched_chrome_answers_and_leaves_no_zombie(tmp_path):
    binary = chrome.find_browser()
    if binary is None:
        pytest.skip("no Chrome binary on this machine")
    profile = tmp_path / "profile"
    process = chrome.launch(binary, profile)
    try:
        port = chrome.wait_for_port(profile, process)
        assert chrome.alive(chrome.url_for(port))
        assert chrome.read_port(profile) == port
    finally:
        process.terminate()
        process.wait(timeout=20)
    assert process.poll() is not None
    assert not chrome.alive(chrome.url_for(port), timeout=1.0)


ALLOWED = {
    "/proc/sys/kernel/apparmor_restrict_unprivileged_userns": "0\n",
    "/proc/sys/user/max_user_namespaces": "63988\n",
}


def test_a_desktop_needs_none_of_the_runner_flags():
    assert chrome.platform_flags("darwin", env={}) == ()
    assert chrome.platform_flags("win32", env={}) == ()


def test_a_linux_box_with_no_display_runs_headless():
    flags = chrome.platform_flags("linux", env={}, uid=1000, read=ALLOWED.__getitem__)
    assert "--headless=new" in flags
    assert "--disable-gpu" in flags
    assert "--disable-dev-shm-usage" in flags


def test_a_linux_desktop_keeps_its_window():
    flags = chrome.platform_flags("linux", env={"DISPLAY": ":0"}, uid=1000, read=ALLOWED.__getitem__)
    assert "--headless=new" not in flags
    assert "--disable-dev-shm-usage" in flags


def test_a_headless_launch_claims_the_agent_a_windowed_one_would():
    flags = chrome.platform_flags("linux", env={}, uid=1000, read=ALLOWED.__getitem__, version="153")
    agents = [flag for flag in flags if flag.startswith("--user-agent=")]
    assert agents == [
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ]
    assert "HeadlessChrome" not in agents[0]


def test_a_windowed_linux_box_keeps_its_own_agent():
    flags = chrome.platform_flags("linux", env={"DISPLAY": ":0"}, uid=1000, read=ALLOWED.__getitem__, version="153")
    assert not any(flag.startswith("--user-agent=") for flag in flags)


def test_a_missing_version_means_no_invented_agent():
    assert chrome.desktop_user_agent("linux", None) is None
    assert chrome.desktop_user_agent("plan9", "153") is None
    flags = chrome.platform_flags("linux", env={}, uid=1000, read=ALLOWED.__getitem__)
    assert not any(flag.startswith("--user-agent=") for flag in flags)


def test_the_version_comes_from_what_the_binary_reports():
    def reports(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="Chromium 153.0.8010.47 built on Debian\n", stderr="")

    assert chrome.browser_version("/usr/bin/chromium", run=reports) == "153"

    def refuses(argv, **_kwargs):
        raise OSError("cannot run")

    assert chrome.browser_version("/nope", run=refuses) is None

    def silent(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, stdout="not a version", stderr="")

    assert chrome.browser_version("/usr/bin/chromium", run=silent) is None


def test_the_sandbox_is_kept_wherever_the_kernel_still_allows_it():
    assert chrome.sandbox_usable("darwin", uid=0) is True
    assert chrome.sandbox_usable("linux", uid=1000, read=ALLOWED.__getitem__) is True
    flags = chrome.platform_flags("linux", env={}, uid=1000, read=ALLOWED.__getitem__)
    assert "--no-sandbox" not in flags


def test_the_sandbox_is_dropped_only_where_it_cannot_start():
    assert chrome.sandbox_usable("linux", uid=0) is False
    restricted = {"/proc/sys/kernel/apparmor_restrict_unprivileged_userns": "1\n"}
    assert chrome.sandbox_usable("linux", uid=1000, read=lambda p: restricted.get(p, "")) is False
    starved = {"/proc/sys/user/max_user_namespaces": "0\n"}
    assert chrome.sandbox_usable("linux", uid=1000, read=lambda p: starved.get(p, "")) is False
    assert "--no-sandbox" in chrome.platform_flags("linux", env={}, uid=0)


def test_an_unreadable_sandbox_setting_is_not_a_blocker():
    def missing(_path):
        raise OSError("no such file")

    assert chrome.sandbox_usable("linux", uid=1000, read=missing) is True


def test_a_refusal_explains_itself_with_what_chrome_said(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / chrome.STDERR_LOG).write_text(
        "[4445:4445:0918/074220.613337:ERROR:zygote_host_impl_linux.cc:102] "
        "Running as root without --no-sandbox is not supported.\n"
    )
    assert "Running as root without --no-sandbox" in chrome.complaint(profile)

    class Dead:
        returncode = 1

        def poll(self):
            return 1

    with pytest.raises(chrome.ChromeError) as caught:
        chrome.wait_for_port(profile, Dead(), timeout=0.5)
    assert "exited with code 1" in str(caught.value)
    assert "Running as root without --no-sandbox" in str(caught.value)


def test_a_silent_refusal_still_reads_cleanly(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    assert chrome.complaint(profile) == ""


def test_a_remembered_url_that_is_dead_is_dropped_and_a_new_chrome_starts(monkeypatch, tmp_path):
    profile = tmp_path / "jev-ra" / "chrome-profile"
    profile.mkdir(parents=True)
    (profile / chrome.PORT_FILE).write_text("41234\n")
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    monkeypatch.setattr(chrome, "find_browser", lambda **_k: "/opt/chrome")
    launched = []
    monkeypatch.setattr(chrome, "launch", lambda binary, path, viewport: launched.append(binary))
    monkeypatch.setattr(chrome, "wait_for_port", lambda *_a, **_k: 45000)
    env = {"XDG_STATE_HOME": str(tmp_path), "BU_CDP_URL": "http://127.0.0.1:41234"}
    assert chrome.ensure(env=env) == ("http://127.0.0.1:45000", "launched")
    assert launched == ["/opt/chrome"]
    assert env["BU_CDP_URL"] == "http://127.0.0.1:45000"
    assert chrome.read_port(profile) is None


def test_a_url_we_launched_is_dropped_even_without_a_port_file(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "LAUNCHED_URL", "http://127.0.0.1:41234")
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    monkeypatch.setattr(chrome, "find_browser", lambda **_k: "/opt/chrome")
    monkeypatch.setattr(chrome, "launch", lambda *_a, **_k: None)
    monkeypatch.setattr(chrome, "wait_for_port", lambda *_a, **_k: 45000)
    env = {"XDG_STATE_HOME": str(tmp_path), "BU_CDP_URL": "http://127.0.0.1:41234"}
    assert chrome.ensure(env=env) == ("http://127.0.0.1:45000", "launched")


def test_a_dead_url_the_user_set_is_reported_not_replaced(monkeypatch, tmp_path):
    monkeypatch.setattr(chrome, "LAUNCHED_URL", None)
    monkeypatch.setattr(chrome, "alive", lambda _url, timeout=2.0: False)
    monkeypatch.setattr(chrome, "launch", lambda *_a, **_k: pytest.fail("must not launch"))
    env = {"XDG_STATE_HOME": str(tmp_path), "BU_CDP_URL": "http://127.0.0.1:9222"}
    with pytest.raises(chrome.ChromeError) as caught:
        chrome.ensure(env=env)
    rendered = caught.value.render()
    assert "http://127.0.0.1:9222" in rendered
    assert "unset BU_CDP_URL" in rendered
    assert env["BU_CDP_URL"] == "http://127.0.0.1:9222"


def test_the_launched_pid_is_recorded_next_to_the_port(monkeypatch, tmp_path):
    class Started:
        pid = 4242

    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / chrome.PID_FILE).write_text("99999\n")
    monkeypatch.setattr(chrome, "browser_version", lambda *_a, **_k: None)
    monkeypatch.setattr(chrome.subprocess, "Popen", lambda *_a, **_k: Started())
    assert chrome.launch("/opt/chrome", profile).pid == 4242
    assert chrome.read_pid(profile) == 4242
    chrome.forget_pid(profile)
    assert chrome.read_pid(profile) is None
    assert chrome.read_pid(tmp_path / "missing") is None
