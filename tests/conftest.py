"""Shared fixtures: a local fixture web server and a raw CDP target when Chrome is reachable."""

import functools
import os
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.fixture(scope="session")
def fixture_server():
    handler = functools.partial(QuietHandler, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def chrome_url():
    url = os.environ.get("BU_CDP_URL")
    if not url:
        return None
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/json/version", timeout=2):
            return url
    except (urllib.error.URLError, OSError):
        return None


@pytest.fixture(scope="session")
def chrome():
    url = chrome_url()
    if not url:
        pytest.skip("No Chrome over CDP; export BU_CDP_URL to run browser tests")
    from browser_harness.admin import ensure_daemon

    ensure_daemon()
    return url


@pytest.fixture
def cdp_target(chrome):
    """A blank background target plus a `call(method, **params)` bound to its session."""
    from browser_harness.helpers import cdp

    target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    session = cdp("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    call("Emulation.setDeviceMetricsOverride", width=1280, height=900, deviceScaleFactor=1, mobile=False)
    call("Emulation.setFocusEmulationEnabled", enabled=True)
    try:
        yield call
    finally:
        cdp("Target.closeTarget", targetId=target)
