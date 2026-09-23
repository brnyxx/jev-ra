"""Put a human check in front of the person at this machine: the window, and a notification naming the site."""

import logging
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

from .chrome import about as describe
from .chrome import headless, loopback

logger = logging.getLogger(__name__)

TITLE = "jev-ra"
NOTIFY_TIMEOUT_S = 5.0
# The words go to osascript as arguments of the script rather than inside it, so a site's name is
# only ever a string to display and never AppleScript to run.
DISPLAY_SCRIPT = ("on run argv", "display notification (item 1 of argv) with title (item 2 of argv)", "end run")


def message(site, check):
    """What the notification says: which site is asking, and what for."""
    return f"{site} is asking a person to clear a {check}. Clear it in the Chrome window and the run carries on."


def notify_command(site, check, platform=None, which=None):
    """The command that raises a desktop notification on this platform, or None where there is none."""
    platform = platform or sys.platform
    which = which or shutil.which
    text = message(site, check)
    if platform == "darwin":
        osascript = which("osascript")
        if not osascript:
            return None
        script = [part for line in DISPLAY_SCRIPT for part in ("-e", line)]
        return [osascript, *script, text, TITLE]
    if platform.startswith("linux"):
        sender = which("notify-send")
        return [sender, TITLE, text] if sender else None
    return None


def notify(site, check, run=None, platform=None, which=None):
    """Raise the notification, and say whether it was raised. A failure is logged, never raised."""
    argv = notify_command(site, check, platform, which)
    if argv is None:
        logger.info("No desktop notification is available here; the check on %s waits unannounced", site)
        return False
    try:
        (run or subprocess.run)(argv, capture_output=True, timeout=NOTIFY_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        logger.info("The desktop notification could not be raised: %s", error)
        return False
    return True


class Presenter:
    """How a human check reaches the person at this machine, when someone there can see the browser."""

    def __init__(self, session, notify=True, alert=notify, about=describe):
        self.session = session
        self.notify = notify
        self.alert = alert
        self.about = about
        self.reason = None

    def hidden(self):
        """Why nobody at this machine can see the browser, or an empty string when someone can.

        A browser on another machine is out of sight however it runs, and a headless one draws
        nothing to look at. Asked once per session: neither changes while it is open.
        """
        if self.reason is not None:
            return self.reason
        url = self.session.cdp_url
        host = urlsplit(url).hostname or ""
        if not loopback(host):
            self.reason = f"the browser is at {host}, not on this machine"
        elif headless(url, self.session.chrome_source, read=self.about):
            self.reason = "the browser is headless"
        else:
            self.reason = ""
        return self.reason

    def present(self, site, check):
        """Bring the check's tab and window to the front, and say which site is asking."""
        self.session.front()
        if self.notify:
            self.alert(site, check)
