"""The first decision is asked while the page is still loading, from the reading it will settle on."""

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jev_ra import config
from jev_ra.agent import Agent
from jev_ra.decide import Reply

pytestmark = pytest.mark.browser

FIXTURES = Path(__file__).parent / "fixtures"
HOLD_S = 5.0
IMAGE = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"/>'


class HoldingHandler(SimpleHTTPRequestHandler):
    """Serves the fixtures, and holds the one image back until the test lets it go."""

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if not self.path.endswith("/held.svg"):
            super().do_GET()
            return
        self.server.released_early = self.server.release.wait(HOLD_S)
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(IMAGE)))
        self.end_headers()
        self.wfile.write(IMAGE)


@pytest.fixture
def holding_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(HoldingHandler, directory=str(FIXTURES)))
    server.release, server.released_early = threading.Event(), None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield server, f"http://{host}:{port}/sites/held-image.html"
    server.release.set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def done_and_release(server):
    calls = []

    def decide(state, questions):
        calls.append(state)
        server.release.set()
        criteria = questions["operation"]["criteria"]
        answers = {
            "operation": {
                "choice": "DONE",
                "confidence": 0.95,
                "probabilities": {key: float(key == "DONE") for key in criteria},
            },
            "goal_achieved": {"noul": 0.95},
        }
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    decide.calls = calls
    return decide


def test_the_first_decision_is_asked_before_the_page_finishes_loading(session, holding_server):
    server, url = holding_server
    decide = done_and_release(server)
    agent = Agent(session=session, config=config.load({}), decide=decide)
    result = agent.run("Open the order status page.", url=url)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert server.released_early is True
    assert (result.speculations, result.prefetched) == (1, 1)
    assert len(decide.calls) == 1
    assert result.elapsed_ms < HOLD_S * 1000


def test_the_answer_is_only_used_once_the_page_has_loaded(session, holding_server):
    server, url = holding_server
    decide = done_and_release(server)
    agent = Agent(session=session, config=config.load({}), decide=decide)
    result = agent.run("Open the order status page.", url=url)
    assert result.final_page["text"].startswith("Order status")
    assert session.evaluate("document.readyState") == "complete"
    assert session.evaluate("document.images[0].complete") is True


def test_a_decider_that_answers_by_position_waits_for_the_load(session, holding_server):
    server, url = holding_server
    server.release.set()
    decide = done_and_release(server)
    agent = Agent(session=session, config=config.load({}), decide=decide, prefetch=False)
    result = agent.run("Open the order status page.", url=url)
    assert (result.status, result.speculations, result.prefetched) == ("done", 0, 0)
    assert len(decide.calls) == 1
