"""How often a run asks one host for a page: a polite client's pace, and a backoff when told to slow down."""

import logging
import threading
import time
from urllib.parse import urlsplit

from .browser.chrome import loopback
from .config import PACE_S

logger = logging.getLogger(__name__)

# A site's hiccup is the site's, not the task's: the same address a moment later is often the
# working page, and a site that answered 429 or put up a check has said to slow down. The first
# backoff is the two seconds the site-error retry always waited; one that follows it on the same
# host waits twice as long, up to the cap.
BACKOFF_S = 2.0
BACKOFF_CAP_S = 30.0


def host_of(url):
    """The server a url names, port and all, or an empty string for an address with none."""
    parts = urlsplit(url or "")
    if not parts.hostname:
        return ""
    return f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname


class Pacer:
    """When the next navigation to each host may start, shared by every run in the process."""

    def __init__(self, backoff=BACKOFF_S, cap=BACKOFF_CAP_S, clock=time.monotonic, sleep=time.sleep):
        self.backoff_s = backoff
        self.cap = cap
        self.clock = clock
        self.sleep = sleep
        self.lock = threading.Lock()
        self.hosts = {}

    def wait(self, url, interval=PACE_S):
        """Hold a navigation to this url's host until its pace allows it, and say how long it was held.

        The navigation that follows is held until `interval` after this one starts. The machine
        this runs on is the operator's own and is never paced, but a backoff it asked for is kept.
        """
        host = host_of(url)
        if not host:
            return 0.0
        with self.lock:
            now = self.clock()
            self.forget(now)
            due, strikes = self.hosts.get(host, (now, 0))
            start = max(now, due)
            gap = 0.0 if loopback(urlsplit(url).hostname) else max(0.0, interval)
            self.hosts[host] = (start + gap, strikes)
        held = start - now
        if held > 0:
            logger.info("Holding the next navigation to %s for %.2f s", host, held)
            self.sleep(held)
        return held

    def backoff(self, url):
        """Slow down for a host that answered 429 or put up a check, and say for how long.

        The next navigation to it waits that long; one more in a row waits twice as long, up to
        the cap. A host quiet for longer than the cap starts over.
        """
        host = host_of(url)
        if not host:
            return 0.0
        with self.lock:
            now = self.clock()
            self.forget(now)
            due, strikes = self.hosts.get(host, (now, 0))
            delay = min(self.cap, self.backoff_s * 2**strikes)
            self.hosts[host] = (max(due, now + delay), strikes + 1)
        return delay

    def forget(self, now):
        """Drop every host whose pace ran out longer ago than the cap, so the table stays small."""
        for host, (due, _strikes) in list(self.hosts.items()):
            if now - due > self.cap:
                del self.hosts[host]


SHARED = Pacer()
