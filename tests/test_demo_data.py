"""The page may only replay a run that was really recorded."""

import json
import re
from pathlib import Path

import pytest

from tests.test_examples import load

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture
def checker():
    return load(ROOT / "scripts" / "check_demo_data.py", "check_demo_data")


def test_the_committed_demo_is_the_recorded_run(checker):
    assert checker.problems() == []
    assert checker.main(["--check"]) == 0


def test_an_edited_demo_is_caught(checker, tmp_path):
    recorded = tmp_path / "recorded.json"
    served = tmp_path / "served.json"
    recorded.write_text(json.dumps({"steps": [{"n": 1}]}))
    served.write_text(json.dumps({"steps": [{"n": 1}, {"n": 2, "invented": True}]}))
    problems = checker.problems(served, recorded)
    assert len(problems) == 1
    assert "is not the run recorded in" in problems[0]


def test_a_missing_file_is_reported_rather_than_raised(checker, tmp_path):
    problems = checker.problems(tmp_path / "gone.json", tmp_path / "also-gone.json")
    assert len(problems) == 2
    assert all("is missing" in problem for problem in problems)


def test_ci_runs_the_check():
    assert "scripts/check_demo_data.py --check" in CI.read_text()


def test_the_landing_page_copy_is_translated_everywhere():
    check = load(ROOT / "scripts" / "check_i18n.py", "check_i18n")
    assert check.page_copy() == []


def test_a_key_missing_from_one_locale_is_caught(tmp_path):
    check = load(ROOT / "scripts" / "check_i18n.py", "check_i18n")
    source = (ROOT / "docs" / "assets-site" / "i18n.js").read_text()
    broken = tmp_path / "i18n.js"
    broken.write_text(re.sub(r'"nav\.how": "[^"]*", ', "", source, count=1))
    problems = check.page_copy(broken)
    assert len(problems) == 1
    assert "nav.how" in problems[0]
