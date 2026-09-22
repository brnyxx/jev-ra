"""Find, launch and reuse one dedicated automation Chrome. BU_CDP_URL always wins."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import DEFAULT_LOCALE
from ..errors import ChromeError

logger = logging.getLogger(__name__)

PORT_FILE = "DevToolsActivePort"
PID_FILE = "jev-ra-chrome.pid"
STDERR_LOG = "chrome-stderr.log"
STARTUP_TIMEOUT_S = 30.0
PROBE_TIMEOUT_S = 2.0
BINARIES = {
    "darwin": (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ),
    "linux": (
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
    ),
    "win32": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ),
}
COMMANDS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")
DEFAULT_PROFILE = "default"
# Dots are allowed inside a name and never on their own: `.` and `..` are directories already.
PROFILE_NAME = re.compile(r"(?!\.+$)[A-Za-z0-9._-]{1,64}")
NAME_RULE = "A profile name is 1-64 characters of letters, digits, dot, dash or underscore."
FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
)
# Chrome's own sandbox needs unprivileged user namespaces. Root never has them, and a Linux box
# can take them away from everyone else: Ubuntu's AppArmor does it by default, and a container
# can set the namespace budget to zero. Where the kernel has already said no, Chrome exits rather
# than start, so the choice is running without the sandbox or not running at all.
SANDBOX_BLOCKERS = (
    ("/proc/sys/kernel/apparmor_restrict_unprivileged_userns", "1"),
    ("/proc/sys/user/max_user_namespaces", "0"),
)
# A headless Chrome announces "HeadlessChrome" in its user agent, and real sites answer that with
# a bot challenge instead of a page - DuckDuckGo's html endpoint did exactly that on the first
# headless container run. When we launch headless, claim what the same binary claims with a window.
UA_PLATFORMS = {
    "darwin": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{version} Safari/537.36"
    ),
    "linux": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"),
    "win32": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{version} Safari/537.36"
    ),
}


def profile_dir(env=None, name=None):
    """The user-data-dir this profile owns: the default one, or a directory of its own per name."""
    env = os.environ if env is None else env
    home = env.get("XDG_STATE_HOME") or Path(env.get("HOME", "~")).expanduser() / ".local" / "state"
    base = Path(home) / "jev-ra"
    if name is None or name == DEFAULT_PROFILE:
        return base / "chrome-profile"
    if not PROFILE_NAME.fullmatch(name):
        raise ChromeError(f"{name!r} is not a usable profile name.", NAME_RULE)
    return base / "chrome-profiles" / name


def listed_targets(url, timeout=PROBE_TIMEOUT_S):
    """The target ids the Chrome at this url publishes, or None when it will not say."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/list", timeout=timeout) as answer:
            listed = json.loads(answer.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return {item.get("id") for item in listed if isinstance(item, dict)}


def verify_attached(url, targets=None, listed=None):
    """Refuse a daemon that is already holding a Chrome other than the profile's own.

    browser-harness keeps one daemon per name and pins it to the browser it first attached to, so
    a second profile asked for while that daemon is up would be driven against the wrong cookies.
    Every way of not knowing - a Chrome that will not list, a daemon that will not answer - lets
    the run through; only a browser that demonstrably holds other targets is refused.
    """
    published = (listed or listed_targets)(url)
    if not published:
        return
    if targets is None:
        from browser_harness.helpers import cdp

        def targets():
            """The targets the daemon this process talks to can see."""
            return cdp("Target.getTargets")

    try:
        held = {info.get("targetId") for info in targets().get("targetInfos", [])}
    except Exception as error:  # the daemon reports every refusal its own way
        logger.info("Could not ask the daemon which Chrome it holds: %s", error)
        return
    if held and not held & published:
        raise ChromeError(
            f"The browser-harness daemon is already driving another Chrome, not the one at {url}.",
            "One daemon holds one browser: close the other jev-ra session first, "
            "or give this one a daemon of its own with BH_RUNTIME_DIR.",
        )


def find_browser(platform=None, env=None, exists=None, which=None):
    """The first Chrome, Chromium or Edge binary this platform offers."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    exists = exists or (lambda path: Path(path).exists())
    which = which or shutil.which
    override = env.get("JEV_RA_CHROME")
    if override:
        if not exists(override):
            raise ChromeError(f"JEV_RA_CHROME points at {override}, which does not exist")
        return override
    for path in BINARIES.get(platform, ()):
        if exists(path):
            return path
    for command in COMMANDS:
        found = which(command)
        if found:
            return found
    return None


def read_port(profile):
    """Chrome writes the chosen port on the first line of DevToolsActivePort."""
    path = Path(profile) / PORT_FILE
    try:
        first = path.read_text().splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return int(first) if first.isdigit() else None


def read_pid(profile):
    """The pid of the Chrome jev-ra launched on this profile, or None when it did not launch one."""
    try:
        first = (Path(profile) / PID_FILE).read_text().strip()
    except OSError:
        return None
    return int(first) if first.isdigit() else None


def url_for(port):
    """The CDP base url for a port on loopback."""
    return f"http://127.0.0.1:{port}"


def alive(url, timeout=PROBE_TIMEOUT_S):
    """Whether a Chrome answers `/json/version` at this url."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def sandbox_usable(platform=None, uid=None, read=None):
    """Whether Chrome's own sandbox can start here, or this box has already taken it away."""
    platform = platform or sys.platform
    if platform != "linux":
        return True
    uid = os.geteuid() if uid is None else uid
    if uid == 0:
        return False
    read = read or (lambda path: Path(path).read_text())
    for path, blocked in SANDBOX_BLOCKERS:
        try:
            if read(path).strip() == blocked:
                return False
        except OSError:
            continue
    return True


def browser_version(binary, run=None):
    """The Chrome major version the binary reports, or None when it will not say."""
    run = run or subprocess.run
    try:
        done = run([str(binary), "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"\b(\d+)\.", (done.stdout or "") + (done.stderr or ""))
    return match.group(1) if match else None


def desktop_user_agent(platform=None, version=None):
    """The user agent a windowed Chrome on this platform sends, or None without a version."""
    template = UA_PLATFORMS.get(platform or sys.platform)
    if not template or not version:
        return None
    return template.format(version=f"{version}.0.0.0")


def platform_flags(platform=None, env=None, uid=None, read=None, version=None):
    """What this machine needs and a desktop does not: no display, no shared memory, no sandbox."""
    env = os.environ if env is None else env
    platform = platform or sys.platform
    if platform != "linux":
        return ()
    # /dev/shm is 64 MB in a container and Chrome will fill it and crash.
    flags = ["--disable-dev-shm-usage"]
    if not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
        flags += ["--headless=new", "--disable-gpu"]
        agent = desktop_user_agent(platform, version)
        if agent:
            flags.append(f"--user-agent={agent}")
    if not sandbox_usable(platform, uid, read):
        flags.append("--no-sandbox")
    return tuple(flags)


def locale_flags(locale=DEFAULT_LOCALE):
    """What a browser is told so it asks sites for one language rather than the machine's."""
    if not locale:
        return ()
    return (f"--lang={locale}", f"--accept-lang={locale}")


def complaint(profile):
    """The last thing Chrome said before it gave up, if it said anything."""
    try:
        text = (Path(profile) / STDERR_LOG).read_text(errors="replace")
    except OSError:
        return ""
    spoken = [line.strip() for line in text.splitlines() if line.strip()]
    return spoken[-1] if spoken else ""


def launch(binary, profile, viewport=(1280, 900), env=None, flags=(), locale=DEFAULT_LOCALE):
    """Start Chrome on its own profile with an ephemeral debugging port."""
    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    # A stale port file from a dead Chrome would otherwise be read as a live one, and a stale pid
    # would be signalled by `jev-ra clean` long after the kernel gave the number to someone else.
    (profile / PORT_FILE).unlink(missing_ok=True)
    (profile / PID_FILE).unlink(missing_ok=True)
    log = profile / STDERR_LOG
    log.unlink(missing_ok=True)
    argv = [
        str(binary),
        "--remote-debugging-port=0",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        f"--window-size={viewport[0]},{viewport[1]}",
        *FLAGS,
        *locale_flags(locale),
        *platform_flags(env=env, version=browser_version(binary)),
        *flags,
        "about:blank",
    ]
    logger.info("Launching %s on %s", binary, profile)
    # Chrome explains itself on stderr and then exits. Thrown away, every refusal looks the same.
    handle = log.open("wb")
    try:
        process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=handle, start_new_session=True)
    finally:
        handle.close()
    # Its own session means nothing reaps it when we exit, so record who to stop later.
    (profile / PID_FILE).write_text(f"{process.pid}\n")
    return process


# The three ways Chrome says its sandbox could not start, measured in a python:3.12-slim
# container: without chromium-sandbox it names the sandbox, and with it the SUID helper dies on
# the namespace the seccomp profile refuses, taking the zygote with it.
SANDBOX_COMPLAINTS = (
    "no usable sandbox",
    "failed to move to new namespace",
    "zygote process exited prematurely",
)


def sandbox_refused(profile):
    """Whether the Chrome that just died blamed its own sandbox.

    A container is the case this exists for: the kernel would allow an unprivileged user
    namespace and the seccomp profile refuses the syscall, so nothing under /proc says in advance
    that the sandbox cannot start. Chrome says it, once, on the way out.
    """
    try:
        text = (Path(profile) / STDERR_LOG).read_text(errors="replace").lower()
    except OSError:
        return False
    return any(phrase in text for phrase in SANDBOX_COMPLAINTS)


def said(message, profile):
    """A failure with whatever Chrome itself said about it appended."""
    spoken = complaint(profile)
    return f"{message}: {spoken}" if spoken else message


def wait_for_port(profile, process=None, timeout=STARTUP_TIMEOUT_S):
    """Block until the launched Chrome publishes a reachable port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port = read_port(profile)
        if port and alive(url_for(port)):
            return port
        if process is not None and process.poll() is not None:
            gone = f"Chrome exited with code {process.returncode} before it opened a debugging port"
            raise ChromeError(said(gone, profile))
        time.sleep(0.1)
    raise ChromeError(said(f"Chrome did not open a debugging port on {profile} within {timeout:g}s", profile))


READY_TIMEOUT_S = 20.0
READY_INTERVAL_S = 0.1


def ready(cdp=None, timeout=READY_TIMEOUT_S):
    """Wait until a target in this Chrome evaluates something, which a published port does not prove."""
    send = cdp
    if send is None:
        from browser_harness.helpers import cdp as send
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            target = send("Target.createTarget", url="about:blank", background=True)["targetId"]
            session = send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
            send("Runtime.evaluate", session_id=session, expression="1", returnByValue=True)
            send("Target.closeTarget", targetId=target)
            return True
        except Exception as error:  # the daemon reports every refusal its own way
            last = error
            time.sleep(READY_INTERVAL_S)
    raise ChromeError(f"Chrome did not answer a first command within {timeout:g}s: {last}")


# The url of the Chrome on the jev-ra profile this process last settled on. `ensure()` writes its
# answer into the environment, so a Chrome that dies leaves a url behind that looks configured;
# remembering what we wrote is what tells our own leftover from the one the user exported.
LAUNCHED_URL = None


def forget_port(profile):
    """Drop the port file, so a dead Chrome is not read as a live one later."""
    (Path(profile) / PORT_FILE).unlink(missing_ok=True)


def forget_pid(profile):
    """Drop the pid file, so a Chrome that has been stopped is not signalled again."""
    (Path(profile) / PID_FILE).unlink(missing_ok=True)


def remembered(url, profile):
    """Whether this cdp url is one jev-ra wrote itself, rather than one the user exported."""
    if url == LAUNCHED_URL:
        return True
    port = read_port(profile)
    return port is not None and url == url_for(port)


def ensure(env=None, viewport=(1280, 900), allow_launch=True, profile=None, locale=DEFAULT_LOCALE):
    """Return (cdp_url, source) where source is 'BU_CDP_URL', 'reused' or 'launched'.

    A named profile is asked for because of the cookies in it, so it outranks an ambient
    BU_CDP_URL; the default profile keeps deferring to whatever Chrome the caller pointed at.
    """
    global LAUNCHED_URL
    env = os.environ if env is None else env
    named = profile is not None and profile != DEFAULT_PROFILE
    profile = profile_dir(env, profile)
    configured = env.get("BU_CDP_URL")
    if configured and not named:
        if alive(configured):
            return configured, "BU_CDP_URL"
        if not remembered(configured, profile):
            raise ChromeError(
                f"No Chrome answered at BU_CDP_URL ({configured})",
                next_step="Start it or unset BU_CDP_URL.",
            )
        logger.info("The Chrome jev-ra launched at %s is gone; starting another", configured)
        env.pop("BU_CDP_URL")
        forget_port(profile)
        LAUNCHED_URL = None
    port = read_port(profile)
    if port and alive(url_for(port)):
        if not named:
            LAUNCHED_URL = url_for(port)
        env["BU_CDP_URL"] = url_for(port)
        return url_for(port), "reused"
    if not allow_launch:
        raise ChromeError("No automation Chrome is running and launching is disabled")
    binary = find_browser(env=env)
    if binary is None:
        raise ChromeError(
            "No Chrome, Chromium or Edge found. Install one, set JEV_RA_CHROME to its path, "
            "or start your own and export BU_CDP_URL."
        )
    port = start(binary, profile, viewport, locale)
    if not named:
        LAUNCHED_URL = url_for(port)
    env["BU_CDP_URL"] = url_for(port)
    return url_for(port), "launched"


def start(binary, profile, viewport, locale=DEFAULT_LOCALE):
    """Launch Chrome and return its port, giving up the sandbox only when Chrome asks us to."""
    process = launch(binary, profile, viewport, locale=locale)
    try:
        return wait_for_port(profile, process)
    except ChromeError:
        if not sandbox_refused(profile):
            raise
    logger.warning("Chrome could not start its own sandbox on this machine; launching it without one")
    relaunched = launch(binary, profile, viewport, flags=("--no-sandbox",), locale=locale)
    return wait_for_port(profile, relaunched)
