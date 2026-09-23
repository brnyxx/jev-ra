"""A wall says which it is: a check a person at the window can clear, or a site refusing outright."""

import pytest

from jev_ra import config
from jev_ra.agent import HUMAN, REFUSAL, Agent, _Run, wall
from jev_ra.decide import Reply

CHECKS = (
    ("recaptcha-wall.html", "reCAPTCHA"),
    ("hcaptcha-wall.html", "hCaptcha"),
    ("turnstile-wall.html", "Turnstile"),
    ("cloudflare-challenge.html", "Cloudflare challenge"),
    ("perimeterx-wall.html", "press and hold"),
    ("akamai-challenge.html", "Akamai challenge"),
)
REFUSALS = ("cloudflare-wall.html", "bot-wall.html", "akamai-wall.html", "geo-block.html")
NEITHER = ("captcha-mention.html", "interstitial-wall.html", "recaptcha-invisible.html", "static.html")
FORBIDDEN_PAGE = (
    "<html><head><title>403 Forbidden</title></head>"
    "<body><center><h1>403 Forbidden</h1></center><hr><center>nginx</center></body></html>"
)
FORBIDDEN_LOGIN = (
    "<!doctype html><html><head><title>Sign in</title></head><body>"
    '<form><label>Email <input name="email"></label><button type="submit">Sign in</button></form>'
    "</body></html>"
)


@pytest.mark.browser
@pytest.mark.parametrize(("name", "check"), CHECKS)
def test_a_check_a_person_can_clear_is_a_human_wall(session, fixture_server, name, check):
    found = wall(session.open(f"{fixture_server}/sites/{name}"))
    assert found is not None
    assert (found.kind, found.check) == (HUMAN, check)


@pytest.mark.browser
@pytest.mark.parametrize("name", REFUSALS)
def test_a_site_that_refuses_outright_is_a_refusal(session, fixture_server, name):
    found = wall(session.open(f"{fixture_server}/sites/{name}"))
    assert found is not None
    assert (found.kind, found.check) == (REFUSAL, "")


@pytest.mark.browser
@pytest.mark.parametrize("name", NEITHER)
def test_a_page_that_only_talks_about_checks_is_neither(session, fixture_server, name):
    assert wall(session.open(f"{fixture_server}/sites/{name}")) is None


@pytest.mark.browser
def test_a_check_that_was_answered_is_no_longer_a_wall(session, fixture_server):
    page = session.open(f"{fixture_server}/sites/recaptcha-wall.html")
    assert wall(page).kind == HUMAN
    session.evaluate("postMessage({jevRaCheck: 'solved'}, '*')")
    assert session.evaluate("new Promise(r => setTimeout(() => r(true), 0))", await_promise=True) is True
    assert wall(session.observe()) is None


@pytest.mark.browser
def test_a_bare_403_is_a_refusal(session, flaky_server):
    found = wall(session.open(flaky_server(status=403, failures=1, body=FORBIDDEN_PAGE)))
    assert (found.kind, found.said) == (REFUSAL, "http 403")


@pytest.mark.browser
def test_a_403_that_offers_a_field_to_fill_is_a_page_to_act_on(session, flaky_server):
    assert wall(session.open(flaky_server(status=403, failures=1, body=FORBIDDEN_LOGIN))) is None


def test_a_check_named_in_words_outranks_the_refusal_on_the_same_page():
    page = {"url": "https://shop.test/", "title": "Access denied", "text": "Press & Hold to confirm you are a human."}
    found = wall(page)
    assert (found.kind, found.check) == (HUMAN, "press & hold")


def test_a_widget_waiting_for_its_answer_is_a_check_however_long_the_page():
    page = {"url": "https://shop.test/", "title": "Sign up", "text": "word " * 800, "challenge": "reCAPTCHA"}
    assert wall(page).check == "reCAPTCHA"


def test_the_thin_host_wall_is_a_refusal():
    run = _Run.__new__(_Run)
    run.opens = ()
    thin = {"url": "https://shop.test/a", "title": ".", "text": "next"}
    found = [run.walled({**thin, "url": f"https://shop.test/{n}"}) for n in range(3)]
    assert found[:2] == [None, None]
    assert found[2].kind == REFUSAL


def certain(choice, criteria):
    return {"choice": choice, "confidence": 0.95, "probabilities": {key: float(key == choice) for key in criteria}}


def finish(_state, questions):
    answers = {"operation": certain("DONE", questions["operation"]["criteria"]), "goal_achieved": {"noul": 0.9}}
    return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})


@pytest.mark.browser
def test_a_refusal_escalates_with_its_kind(session, fixture_server):
    agent = Agent(session=session, config=config.load({}), decide=finish, prefetch=False)
    result = agent.run("Open the help centre.", url=f"{fixture_server}/sites/geo-block.html")
    assert (result.status, result.reason) == ("escalate", "blocked_by_site")
    assert result.detail["kind"] == REFUSAL
    assert result.detail["wall"] == "the page answered with 'not available in your country'"
