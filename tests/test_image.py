"""The container image: a Chromium inside it, and a CI job that proves doctor finds one."""

import json
import re
from pathlib import Path

import pytest

from jev_ra import cli
from tests.test_agent import FakeSession

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_the_image_is_the_supported_python_with_a_chromium_in_it():
    text = DOCKERFILE.read_text()
    assert "FROM python:3.12-slim" in text
    assert re.search(r"^\s+chromium\b", text, re.MULTILINE)
    assert "JEV_RA_CHROME=/usr/bin/chromium" in text


def test_the_image_runs_as_a_user_with_a_short_home():
    text = DOCKERFILE.read_text()
    assert re.search(r"^USER jev$", text, re.MULTILINE)
    # Chrome's own sandbox needs an unprivileged user, and browser-harness names a unix socket
    # under HOME, which the kernel caps at about a hundred characters.
    assert "HOME=/home/jev" in text
    assert len("/home/jev") < cli.SOCKET_PATH_LIMIT


def test_the_image_is_the_cli():
    text = DOCKERFILE.read_text()
    assert '\nENTRYPOINT ["jev-ra"]' in text
    assert '\nCMD ["doctor"]' in text


def test_the_build_context_leaves_out_what_the_image_does_not_need():
    ignored = set(DOCKERIGNORE.read_text().split())
    assert {".git", ".venv", "tests", "docs", "corpus"} <= ignored


def test_ci_builds_the_image_and_asks_it_about_chrome():
    text = CI.read_text()
    assert re.search(r"^  image:$", text, re.MULTILINE)
    assert "docker build" in text
    assert "doctor --json" in text
    assert "chrome" in text.split("  image:", 1)[1]


@pytest.fixture
def no_key(monkeypatch, tmp_path):
    for name in ("JEV_RA_API_KEY", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_doctor_reports_chrome_even_when_no_key_is_set(no_key, monkeypatch, capsys):
    # The image is checked without a key, so the Chrome row has to be there before the key gate.
    monkeypatch.setattr(cli, "Session", lambda *_a, **_k: FakeSession())
    assert cli.main(["doctor", "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["key"] is False
    assert report["chrome"]["ok"] is True
    assert "decision" not in report
