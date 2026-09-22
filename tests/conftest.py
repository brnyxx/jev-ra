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


ERROR_PAGE = (
    "<!doctype html><html><head><title>502 Bad Gateway</title></head>"
    "<body><h1>502 Bad Gateway</h1><p>The site hiccupped.</p></body></html>"
)
FORM_PAGE = (
    "<!doctype html><html><head><title>Pizza order</title></head><body>"
    '<form action="/post" method="post">'
    '<label>Customer name: <input name="custname"></label>'
    '<label>Size: <select name="size"><option>small</option><option>large</option></select></label>'
    '<button type="submit">Submit order</button>'
    "</form></body></html>"
)


class FlakyHandler(QuietHandler):
    """Answers `/` with a status for the server's first `failures` requests, then with the form."""

    def answer(self, status, body):
        body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/":
            super().do_GET()
            return
        if self.server.failures > 0:
            self.server.failures -= 1
            self.answer(self.server.status, self.server.body)
            return
        self.answer(200, FORM_PAGE)


@pytest.fixture
def flaky_server():
    """A factory for a site that answers its first `failures` requests with `status`."""
    servers = []

    def start(status=502, failures=1, body=ERROR_PAGE):
        handler = functools.partial(FlakyHandler, directory=str(FIXTURES))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.status, server.failures, server.body = status, failures, body
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        host, port = server.server_address
        return f"http://{host}:{port}/"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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


def require_browser():
    """The CDP url, or skip. CI sets JEV_RA_REQUIRE_BROWSER so a missing Chrome fails instead."""
    url = chrome_url()
    if url:
        return url
    if os.environ.get("JEV_RA_REQUIRE_BROWSER"):
        raise RuntimeError("JEV_RA_REQUIRE_BROWSER is set but no Chrome answered on BU_CDP_URL")
    pytest.skip("No Chrome over CDP; export BU_CDP_URL to run browser tests")


@pytest.fixture(scope="session")
def chrome():
    url = require_browser()
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


@pytest.fixture
def session(chrome):
    """A jev-ra Session on its own target, closed after the test."""
    from jev_ra.browser.session import Session

    opened = Session()
    try:
        yield opened
    finally:
        opened.close()
