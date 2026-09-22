"""A verify spec that cannot prove its own goal is worse than no spec at all."""

from pathlib import Path

import pytest

from jev_ra.corpus import VERIFY_KEYS, Task, check, load_tasks
from tests.test_examples import load

ROOT = Path(__file__).resolve().parents[1]

ROW = {
    "url": "https://www.seoul.go.kr/news/news_tender.do",
    "text": "입찰공고 목록",
    "elements": [{"label": "입찰공고", "selected": "true"}],
}

FAILING = {
    "url_contains": ["realmnews"],
    "url_not_contains": ["news_tender"],
    "text_contains": ["새소식"],
    "text_any": ["새소식"],
    "label_any": ["새소식"],
    "active_label": ["새소식"],
    "min_text": 4000,
}


@pytest.fixture
def reviewer():
    return load(ROOT / "scripts" / "check_corpus_specs.py", "check_corpus_specs")


def task(**overrides):
    base = {"name": "t", "family": "f", "url": "https://example.com/start", "goal": "g", "expect": "done"}
    return Task(**{**base, **overrides})


def test_every_committed_spec_proves_its_own_goal(reviewer):
    assert reviewer.review()[1] == []
    assert reviewer.main(["--check"]) == 0


def test_the_review_puts_each_goal_beside_its_spec(reviewer):
    lines = "\n".join(reviewer.review()[0])
    for one in load_tasks():
        assert one.name in lines
        assert one.goal.split()[0] in lines


def test_a_finished_run_with_nothing_to_prove_it_is_a_fault(reviewer):
    assert reviewer.faults(task(verify={})) == ["expect is done with no verify spec, so any finished run passes"]


def test_a_spec_on_an_outcome_that_never_reads_one_is_a_fault(reviewer):
    problems = reviewer.faults(task(expect="escalate:needs_value", verify={"text_any": ["x"]}))
    assert problems == ["verify is never consulted for an outcome other than done"]


def test_a_key_the_checker_ignores_is_a_fault(reviewer):
    problems = reviewer.faults(task(verify={"text_includes": ["x"]}))
    assert problems == ["verify keys ['text_includes'] are not read by the checker, so they prove nothing"]


def test_a_check_the_starting_address_already_passes_is_a_fault(reviewer):
    problems = reviewer.faults(task(verify={"url_contains": ["example.com"]}))
    assert problems == ["url_contains 'example.com' is already true of the starting address"]


def test_an_outcome_the_runner_cannot_classify_is_a_fault(reviewer):
    assert reviewer.faults(task(expect="finished", verify={"text_any": ["x"]}))[0].startswith("expect is 'finished'")


@pytest.mark.parametrize("key", VERIFY_KEYS)
def test_every_declared_verify_key_is_one_the_checker_reads(key):
    assert check({key: FAILING[key]}, ROW)[0] is False
    assert check({}, ROW) == (True, "")


def test_the_seoul_spec_and_its_goal_name_the_same_list():
    one = next(task for task in load_tasks() if task.name == "seoul_go_kr_notice")
    assert "입찰공고" in one.goal
    assert one.verify == {"url_contains": ["news_tender"], "text_any": ["입찰공고"]}
