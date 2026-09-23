"""A run asks one host for pages at a polite pace, and slows down when the host says so."""

import pytest

from jev_ra import config
from jev_ra.agent import HUMAN, Agent
from jev_ra.browser.chrome import loopback
from jev_ra.decide import Reply
from jev_ra.pacing import BACKOFF_CAP_S, BACKOFF_S, Pacer


class Clock:
    """A clock that only moves when something sleeps on it."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def pacer(**options):
    clock = Clock()
    return Pacer(clock=clock, sleep=clock.sleep, **options), clock


def test_the_first_navigation_to_a_host_is_not_held():
    paced, clock = pacer()
    assert paced.wait("https://shop.test/a", interval=1.0) == 0
    assert clock.slept == []


def test_a_second_navigation_to_the_same_host_waits_out_the_interval():
    paced, clock = pacer()
    paced.wait("https://shop.test/a", interval=1.0)
    clock.now += 0.25
    assert paced.wait("https://shop.test/b", interval=1.0) == pytest.approx(0.75)
    assert clock.slept == [0.75]


def test_another_host_is_not_held_by_the_first():
    paced, clock = pacer()
    paced.wait("https://shop.test/a", interval=1.0)
    assert paced.wait("https://news.test/", interval=1.0) == 0
    assert clock.slept == []


def test_a_navigation_after_the_interval_is_not_held():
    paced, clock = pacer()
    paced.wait("https://shop.test/a", interval=1.0)
    clock.now += 5
    assert paced.wait("https://shop.test/b", interval=1.0) == 0


def test_an_interval_of_zero_turns_the_pace_off():
    paced, _clock = pacer()
    paced.wait("https://shop.test/a", interval=0)
    assert paced.wait("https://shop.test/b", interval=0) == 0


def test_this_machine_is_never_paced():
    paced, clock = pacer()
    for _ in range(3):
        paced.wait("http://127.0.0.1:8000/", interval=1.0)
    assert clock.slept == []


def test_a_backoff_holds_the_next_navigation_to_that_host():
    paced, clock = pacer()
    paced.wait("https://shop.test/a", interval=1.0)
    assert paced.backoff("https://shop.test/a") == BACKOFF_S
    assert paced.wait("https://shop.test/a", interval=1.0) == BACKOFF_S
    assert clock.slept == [BACKOFF_S]


def test_a_backoff_holds_this_machine_too():
    paced, _clock = pacer()
    paced.backoff("http://127.0.0.1:8000/")
    assert paced.wait("http://127.0.0.1:8000/", interval=1.0) == BACKOFF_S


def test_backoffs_in_a_row_double_up_to_the_cap():
    paced, _clock = pacer()
    delays = [paced.backoff("https://shop.test/") for _ in range(8)]
    assert delays[:4] == [BACKOFF_S, BACKOFF_S * 2, BACKOFF_S * 4, BACKOFF_S * 8]
    assert max(delays) == BACKOFF_CAP_S


def test_a_host_that_has_been_quiet_long_enough_starts_over():
    paced, clock = pacer()
    paced.backoff("https://shop.test/")
    paced.backoff("https://shop.test/")
    clock.now += BACKOFF_CAP_S * 3
    assert paced.backoff("https://shop.test/") == BACKOFF_S


def test_a_url_without_a_host_is_never_held():
    paced, _clock = pacer()
    assert paced.backoff("about:blank") == 0
    assert paced.wait("about:blank", interval=1.0) == 0


def test_loopback_is_this_machine_by_name_and_by_address():
    assert all(loopback(host) for host in ("localhost", "127.0.0.1", "127.8.0.1", "::1", "[::1]", "app.localhost"))
    assert not any(loopback(host) for host in ("", "example.com", "10.0.0.5", "192.0.2.1", "localhost.example"))


def test_the_pace_is_configurable_and_zero_is_off():
    assert config.load({}).pace_s == 1.0
    assert config.load({"JEV_RA_PACE_S": "2.5"}).pace_s == 2.5
    assert config.load({"JEV_RA_PACE_S": "0"}).pace_s == 0.0
    assert config.load({"JEV_RA_PACE_S": "soon"}).pace_s == 1.0


def done(_state, questions):
    criteria = questions["operation"]["criteria"]
    spread = {key: float(key == "DONE") for key in criteria}
    answers = {
        "operation": {"choice": "DONE", "confidence": 0.95, "probabilities": spread},
        "goal_achieved": {"noul": 0.95},
    }
    return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})


class Sessionless:
    """Just enough session for a run that opens one page and finishes on it."""

    max_elements = 250
    target_id = "fake"

    def __init__(self):
        self.opened = []

    def open(self, url):
        self.opened.append(url)
        return {"url": url, "title": "Shop", "text": "A shop with things in it. " * 20, "elements": [], "actions": []}

    def observe(self, timer=None):
        return self.open(self.opened[-1])


def test_a_run_waits_out_the_pace_before_it_opens_the_same_host_again():
    paced, clock = pacer()
    for _ in range(2):
        agent = Agent(session=Sessionless(), config=config.load({}), decide=done, prefetch=False, pacer=paced)
        assert agent.run("Look at the shop.", url="https://shop.test/").status == "done"
    assert clock.slept == [1.0]


def test_a_run_without_an_address_to_open_is_never_paced():
    paced, clock = pacer()
    paced.wait("https://shop.test/", interval=1.0)
    session = Sessionless()
    session.opened.append("https://shop.test/")
    Agent(session=session, config=config.load({}), decide=done, prefetch=False, pacer=paced).run("Look.")
    assert clock.slept == []


TOO_MANY = (
    "<!doctype html><html><head><title>429 Too Many Requests</title></head>"
    "<body><h1>Too Many Requests</h1></body></html>"
)
CHECK = (
    "<!doctype html><html><head><title>Just a moment...</title></head>"
    "<body><h1>shop.example</h1><p>Verify you are human by completing the action below.</p></body></html>"
)


def run_on(session, url, paced):
    agent = Agent(session=session, config=config.load({}), decide=done, prefetch=False, pacer=paced)
    return agent.run("Order a large pizza for Ada Lovelace.", url=url)


@pytest.mark.browser
def test_a_429_backs_off_before_the_one_reload(session, flaky_server):
    paced, clock = pacer()
    result = run_on(session, flaky_server(status=429, failures=1, body=TOO_MANY), paced)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert result.site_error is True
    assert clock.slept == [BACKOFF_S]


@pytest.mark.browser
def test_a_check_on_an_opened_page_backs_off_and_asks_once_more(session, flaky_server):
    paced, clock = pacer()
    result = run_on(session, flaky_server(status=200, failures=1, body=CHECK), paced)
    assert (result.status, result.reason) == ("done", "goal_achieved")
    assert clock.slept == [BACKOFF_S]


@pytest.mark.browser
def test_a_check_that_is_still_there_after_the_reload_is_a_wall(session, flaky_server):
    paced, clock = pacer()
    result = run_on(session, flaky_server(status=200, failures=2, body=CHECK), paced)
    assert (result.status, result.reason) == ("escalate", "blocked_by_site")
    assert result.detail["kind"] == HUMAN
    assert clock.slept == [BACKOFF_S]
