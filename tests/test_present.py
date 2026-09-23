"""A human check is put in front of the person at this machine, or said to be out of their sight."""

import subprocess

import pytest

from jev_ra import config
from jev_ra.browser import chrome
from jev_ra.browser.present import TITLE, Presenter, notify, notify_command


def found(*names):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_macos_says_it_with_osascript_and_passes_the_words_as_arguments():
    argv = notify_command("shop.example", "reCAPTCHA", platform="darwin", which=found("osascript"))
    assert argv[:2] == ["/usr/bin/osascript", "-e"]
    assert "display notification (item 1 of argv) with title (item 2 of argv)" in argv
    assert argv[-1] == TITLE
    assert "shop.example" in argv[-2] and "reCAPTCHA" in argv[-2]


def test_words_that_look_like_applescript_stay_words():
    argv = notify_command(
        'shop.example" & (do shell script "id") & "', "check", platform="darwin", which=found("osascript")
    )
    assert all("do shell script" not in part for part in argv[:-2])


def test_linux_says_it_with_notify_send_when_it_is_there():
    argv = notify_command("shop.example", "Turnstile", platform="linux", which=found("notify-send"))
    assert argv[:2] == ["/usr/bin/notify-send", TITLE]
    assert "shop.example" in argv[2] and "Turnstile" in argv[2]


@pytest.mark.parametrize(
    ("platform", "which"),
    [("linux", found()), ("darwin", found()), ("win32", found("osascript", "notify-send")), ("freebsd", found())],
)
def test_elsewhere_there_is_nothing_to_say_it_with(platform, which):
    assert notify_command("shop.example", "captcha", platform=platform, which=which) is None


class Recorder:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def __call__(self, argv, **options):
        self.calls.append((argv, options))
        if self.error:
            raise self.error
        return subprocess.CompletedProcess(argv, 0)


def test_the_notification_runs_the_command_with_a_timeout():
    run = Recorder()
    assert notify("shop.example", "captcha", run=run, platform="linux", which=found("notify-send")) is True
    ((argv, options),) = run.calls
    assert argv[0] == "/usr/bin/notify-send"
    assert options["timeout"] > 0 and options["check"] is False


def test_nothing_is_run_where_there_is_nothing_to_run():
    run = Recorder()
    assert notify("shop.example", "captcha", run=run, platform="win32", which=found()) is False
    assert run.calls == []


@pytest.mark.parametrize("error", [OSError("gone"), subprocess.TimeoutExpired("notify-send", 5)])
def test_a_notification_that_fails_never_ends_the_run(error):
    run = Recorder(error)
    assert notify("shop.example", "captcha", run=run, platform="linux", which=found("notify-send")) is False


class Window:
    """A session that records being brought forward."""

    def __init__(self, cdp_url="http://127.0.0.1:9222", source="launched"):
        self.cdp_url = cdp_url
        self.chrome_source = source
        self.fronted = 0

    def front(self):
        self.fronted += 1


def test_presenting_brings_the_window_forward_and_names_the_site():
    said = []
    window = Window()
    Presenter(window, notify=True, alert=lambda site, check: said.append((site, check))).present(
        "shop.example", "hCaptcha"
    )
    assert window.fronted == 1
    assert said == [("shop.example", "hCaptcha")]


def test_notifications_can_be_turned_off():
    said = []
    window = Window()
    Presenter(window, notify=False, alert=lambda site, check: said.append(site)).present("shop.example", "hCaptcha")
    assert window.fronted == 1
    assert said == []


def about(browser="Chrome/153.0.8010.53", agent="Mozilla/5.0 (Macintosh) Chrome/153.0.0.0 Safari/537.36"):
    return lambda _url: {"Browser": browser, "User-Agent": agent}


def test_a_windowed_chrome_on_this_machine_can_be_seen():
    assert Presenter(Window(source="BU_CDP_URL"), about=about()).hidden() == ""


def test_a_headless_chrome_says_so_in_its_user_agent():
    headless = about(agent="Mozilla/5.0 (Macintosh) HeadlessChrome/153.0.0.0 Safari/537.36")
    assert "headless" in Presenter(Window(source="BU_CDP_URL"), about=headless).hidden()


def test_a_chrome_on_another_machine_cannot_be_seen_from_this_one():
    reason = Presenter(Window(cdp_url="http://10.0.0.5:9222", source="BU_CDP_URL"), about=about()).hidden()
    assert "10.0.0.5" in reason


def test_the_answer_is_asked_for_once():
    asked = []

    def counting(url):
        asked.append(url)
        return {"Browser": "Chrome/153", "User-Agent": "Chrome/153"}

    presenter = Presenter(Window(source="BU_CDP_URL"), about=counting)
    assert presenter.hidden() == presenter.hidden() == ""
    assert len(asked) == 1


def test_a_chrome_jev_ra_launched_headless_is_headless_whatever_it_claims():
    bare = {"PATH": "/usr/bin"}
    assert chrome.headless("http://127.0.0.1:9222", "launched", env=bare, platform="linux", read=about()) is True
    assert chrome.headless("http://127.0.0.1:9222", "reused", env=bare, platform="linux", read=about()) is True
    shown = {"DISPLAY": ":0"}
    assert chrome.headless("http://127.0.0.1:9222", "launched", env=shown, platform="linux", read=about()) is False
    assert chrome.headless("http://127.0.0.1:9222", "BU_CDP_URL", env=bare, platform="linux", read=about()) is False
    assert chrome.headless("http://127.0.0.1:9222", "launched", env=bare, platform="darwin", read=about()) is False


def test_a_chrome_that_will_not_say_is_taken_at_its_launch():
    assert chrome.headless("http://127.0.0.1:1", "BU_CDP_URL", env={}, platform="darwin", read=lambda _url: {}) is False


def test_notifications_are_on_by_default_and_can_be_turned_off():
    assert config.load({}).notify is True
    assert config.load({"JEV_RA_NOTIFY": "0"}).notify is False
    assert config.load({"JEV_RA_NOTIFY": "off"}).notify is False


@pytest.mark.browser
def test_the_tab_comes_to_the_front_and_a_minimized_window_comes_back(session):
    from browser_harness.helpers import cdp

    window = cdp("Browser.getWindowForTarget", targetId=session.target_id)
    cdp("Browser.setWindowBounds", windowId=window["windowId"], bounds={"windowState": "minimized"})
    assert cdp("Browser.getWindowForTarget", targetId=session.target_id)["bounds"]["windowState"] == "minimized"
    session.front()
    assert cdp("Browser.getWindowForTarget", targetId=session.target_id)["bounds"]["windowState"] == "normal"
    assert session.evaluate("document.visibilityState") == "visible"


@pytest.mark.browser
def test_a_session_knows_whether_its_own_browser_can_be_seen(session):
    said = chrome.about(session.cdp_url)
    headless = "headless" in f"{said.get('Browser', '')} {said.get('User-Agent', '')}".lower()
    assert ("headless" in session.presenter.hidden()) is headless


def test_a_chrome_jev_ra_launched_where_there_is_a_screen_can_be_seen():
    assert chrome.headless("http://127.0.0.1:9222", "launched", env={}, platform="darwin", read=about()) is False
    shown = {"DISPLAY": ":0"}
    assert chrome.headless("http://127.0.0.1:9222", "launched", env=shown, platform="linux", read=about()) is False
