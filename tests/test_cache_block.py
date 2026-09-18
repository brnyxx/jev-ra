"""Blocked resources never leave the browser, and a repeated extract does not re-read the DOM."""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jev_ra import config, search
from jev_ra.browser.session import BLOCKED_URLS, Session
from jev_ra.extract import extract
from tests.conftest import FIXTURES

pytestmark = pytest.mark.browser


@pytest.fixture
def recording_server():
    requested = []

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            requested.append(self.path)
            super().do_GET()

    handler = functools.partial(Handler, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}", requested
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_blocking_is_on_by_default_and_can_be_turned_off():
    assert config.load({}).block_resources is True
    assert config.load({"JEV_RA_BLOCK_RESOURCES": "0"}).block_resources is False
    assert config.load({"JEV_RA_BLOCK_RESOURCES": "off"}).block_resources is False
    assert config.load({"JEV_RA_BLOCK_RESOURCES": "1"}).block_resources is True


def test_the_default_list_blocks_fonts_and_media_but_never_images():
    assert "*.woff2" in BLOCKED_URLS
    assert "*.mp4" in BLOCKED_URLS
    # Images size real layouts; blocking them costs half the observable page.
    assert not any(pattern.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")) for pattern in BLOCKED_URLS)
    assert "*.png" in search.BLOCKED_URLS


def test_the_driving_session_still_loads_images(chrome, recording_server):
    base, requested = recording_server
    session = Session(config.load({}))
    try:
        assert session.blocked == list(BLOCKED_URLS)
        session.open(f"{base}/heavy.html")
        session.observe()
    finally:
        session.close()
    assert any("pixel.png" in path for path in requested)


def test_the_heavier_reading_list_keeps_images_off_the_wire(chrome, recording_server):
    base, requested = recording_server
    session = Session(config.load({}))
    try:
        session.block_resources(search.BLOCKED_URLS)
        session.open(f"{base}/heavy.html")
        session.observe()
    finally:
        session.close()
    assert any(path.startswith("/heavy.html") for path in requested)
    assert not any("pixel.png" in path for path in requested)


def test_blocking_can_be_turned_off_entirely(chrome, recording_server):
    base, _requested = recording_server
    session = Session(config.load({"JEV_RA_BLOCK_RESOURCES": "0"}))
    try:
        assert session.blocked == []
        session.open(f"{base}/heavy.html")
    finally:
        session.close()


def test_a_second_extract_of_the_same_url_is_served_from_cache(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    first = extract(session, "links")
    assert first["cached"] is False
    evaluations = []
    original = session.evaluate

    def counting(expression, await_promise=False):
        evaluations.append(expression)
        return original(expression, await_promise)

    session.evaluate = counting
    second = extract(session, "links")
    assert second["cached"] is True
    assert second["links"] == first["links"]
    assert not any("mode" in expression for expression in evaluations)


def test_a_different_mode_is_a_different_cache_entry(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    extract(session, "links")
    assert extract(session, "tables")["cached"] is False
    assert extract(session, "tables")["cached"] is True


def test_acting_on_the_page_invalidates_the_cache(session, fixture_server):
    page = session.open(f"{fixture_server}/form.html")
    assert extract(session, "text")["cached"] is False
    assert extract(session, "text")["cached"] is True
    action = next(a for a in page["actions"] if a["label"] == "City" and a["kind"] == "fill")
    session.act(action, page, text="Lisbon")
    fresh = extract(session, "text")
    assert fresh["cached"] is False


def test_opening_a_new_url_invalidates_the_cache(session, fixture_server):
    session.open(f"{fixture_server}/list.html")
    extract(session, "text")
    session.open(f"{fixture_server}/form.html")
    assert extract(session, "text")["cached"] is False
    assert session.cache_get(("extract", f"{fixture_server}/list.html", "text", 20000)) is None
