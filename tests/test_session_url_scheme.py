"""Only a web scheme reaches Chrome; a local file needs an explicit opt-in."""

import pytest

from jev_ra import config
from jev_ra.browser import session as session_module
from jev_ra.browser.session import Session, check_url
from jev_ra.errors import BadUrl


class Reached(Exception):
    """The stub CDP raises this, so a navigation that happened is never a silent pass."""


def session_for(env, monkeypatch):
    """A Session that owns no target: anything it sends to Chrome fails the test loudly."""

    def reached(*_args, **_params):
        raise Reached("the url reached Chrome")

    monkeypatch.setattr(session_module, "cdp", reached)
    made = Session.__new__(Session)
    made.config = config.load(env)
    made.cache = {}
    made.session_id = "stub"
    made.after_input = None
    return made


def test_a_javascript_url_is_refused_before_anything_is_sent_to_chrome(monkeypatch):
    session = session_for({}, monkeypatch)
    with pytest.raises(BadUrl, match="javascript"):
        session.open("javascript:alert(1)")


@pytest.mark.parametrize("url", ("data:text/html,<p>hi", "chrome://version", "ftp://example.test/x", "example.test"))
def test_every_other_scheme_is_refused_too(url, monkeypatch):
    session = session_for({}, monkeypatch)
    with pytest.raises(BadUrl):
        session.open(url)


def test_a_file_url_is_refused_until_the_environment_opts_in(monkeypatch):
    session = session_for({}, monkeypatch)
    with pytest.raises(BadUrl) as caught:
        session.open("file:///etc/passwd")
    assert "JEV_RA_ALLOW_FILE_URLS" in caught.value.render()
    allowed = session_for({"JEV_RA_ALLOW_FILE_URLS": "1"}, monkeypatch)
    with pytest.raises(Reached):
        allowed.open("file:///etc/passwd")


@pytest.mark.parametrize("url", ("http://example.test/", "https://example.test/", "about:blank"))
def test_a_web_scheme_and_a_blank_page_get_through(url, monkeypatch):
    session = session_for({}, monkeypatch)
    with pytest.raises(Reached):
        session.open(url)


def test_the_check_names_what_it_refused_and_what_to_do_about_it():
    with pytest.raises(BadUrl) as caught:
        check_url("javascript:alert(1)", config.load({}))
    assert "javascript" in caught.value.render()
    assert "http" in caught.value.render()


def test_the_opt_in_reads_the_same_false_values_as_the_other_flags():
    assert config.load({"JEV_RA_ALLOW_FILE_URLS": "1"}).allow_file_urls is True
    assert config.load({"JEV_RA_ALLOW_FILE_URLS": "0"}).allow_file_urls is False
    assert config.load({}).allow_file_urls is False
