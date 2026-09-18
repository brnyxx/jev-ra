"""Find, launch and reuse one dedicated automation Chrome. BU_CDP_URL always wins."""

import logging
import os
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


def launch(binary, profile, viewport=(1280, 900)):
    """Start Chrome on its own profile with an ephemeral debugging port."""
    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    # A stale port file from a dead Chrome would otherwise be read as a live one.
    (profile / PORT_FILE).unlink(missing_ok=True)
    argv = [
        str(binary),
        "--remote-debugging-port=0",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        f"--window-size={viewport[0]},{viewport[1]}",
        *FLAGS,
        "about:blank",
    ]
    logger.info("Launching %s on %s", binary, profile)
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def wait_for_port(profile, process=None, timeout=STARTUP_TIMEOUT_S):
    """Block until the launched Chrome publishes a reachable port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port = read_port(profile)
        if port and alive(url_for(port)):
            return port
        if process is not None and process.poll() is not None:
            raise ChromeError(f"Chrome exited with code {process.returncode} before it opened a debugging port")
        time.sleep(0.1)
    raise ChromeError(f"Chrome did not open a debugging port on {profile} within {timeout:g}s")


def ensure(env=None, viewport=(1280, 900), allow_launch=True):
    """Return (cdp_url, source) where source is 'BU_CDP_URL', 'reused' or 'launched'."""
    env = os.environ if env is None else env
    configured = env.get("BU_CDP_URL")
    if configured:
        return configured, "BU_CDP_URL"
    profile = profile_dir(env)
    port = read_port(profile)
    if port and alive(url_for(port)):
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
    process = launch(binary, profile, viewport)
    port = wait_for_port(profile, process)
    env["BU_CDP_URL"] = url_for(port)
    return url_for(port), "launched"
