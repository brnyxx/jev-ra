"""Find, launch and reuse one dedicated automation Chrome. BU_CDP_URL always wins."""

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


def profile_dir(env=None):
    """The automation profile directory under `$XDG_STATE_HOME`."""
    env = os.environ if env is None else env
    home = env.get("XDG_STATE_HOME") or Path(env.get("HOME", "~")).expanduser() / ".local" / "state"
    return Path(home) / "jev-ra" / "chrome-profile"


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


def complaint(profile):
    """The last thing Chrome said before it gave up, if it said anything."""
    try:
        text = (Path(profile) / STDERR_LOG).read_text(errors="replace")
    except OSError:
        return ""
    spoken = [line.strip() for line in text.splitlines() if line.strip()]
    return spoken[-1] if spoken else ""


def launch(binary, profile, viewport=(1280, 900), env=None):
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
        *platform_flags(env=env, version=browser_version(binary)),
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


def ensure(env=None, viewport=(1280, 900), allow_launch=True):
    """Return (cdp_url, source) where source is 'BU_CDP_URL', 'reused' or 'launched'."""
    global LAUNCHED_URL
    env = os.environ if env is None else env
    profile = profile_dir(env)
    configured = env.get("BU_CDP_URL")
    if configured:
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
        LAUNCHED_URL = url_for(port)
        env["BU_CDP_URL"] = LAUNCHED_URL
        return LAUNCHED_URL, "reused"
    if not allow_launch:
        raise ChromeError("No automation Chrome is running and launching is disabled")
    binary = find_browser(env=env)
    if binary is None:
        raise ChromeError(
            "No Chrome, Chromium or Edge found. Install one, set JEV_RA_CHROME to its path, "
            "or start your own and export BU_CDP_URL."
        )
    process = launch(binary, profile, viewport)
    port = wait_for_port(profile, process)
    LAUNCHED_URL = url_for(port)
    env["BU_CDP_URL"] = LAUNCHED_URL
    return LAUNCHED_URL, "launched"
