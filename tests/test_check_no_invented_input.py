"""A run that typed what it was never given fails the check, not just the reviewer's eye."""

import json
from pathlib import Path

import pytest

from tests.test_examples import load

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "tests" / "fixtures" / "corpus-results.jsonl"


@pytest.fixture
def checker():
    return load(ROOT / "scripts" / "check_no_invented_input.py", "check_no_invented_input")


def row(task, text, status="done"):
    return {
        "task": task,
        "family": "f",
        "status": status,
        "trace": [{"operation": "TYPE_TEXT", "target": "e1", "label": "Field", "text": text}],
    }


def test_the_fixture_finds_the_invented_text_and_the_row_that_cannot_be_checked(checker):
    rows, broken = checker.read_rows(RESULTS)
    assert broken == []
    found = checker.faults(rows, checker.tasks_by_name())
    assert len(found) == 2
    assert any("gov_kr_search" in one and "'여권'" in one for one in found)
    assert any("musinsa_search" in one and "no step trace" in one for one in found)


def test_the_fixture_holds_the_steps_a_clean_file_is_measured_on(checker):
    rows, _broken = checker.read_rows(RESULTS)
    assert checker.typed_steps(rows) == 5


def test_a_run_that_typed_only_its_values_passes(checker, tmp_path, capsys):
    path = tmp_path / "clean.jsonl"
    path.write_text(json.dumps(row("selenium_form_submit", "Ada Lovelace")) + "\n")
    assert checker.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "1 TYPE_TEXT step(s)" in out and "0 fault(s)" in out


def test_a_value_from_another_task_is_still_invented_here(checker, tmp_path, capsys):
    path = tmp_path / "borrowed.jsonl"
    path.write_text(json.dumps(row("gov_kr_search", "Ada Lovelace")) + "\n")
    assert checker.main([str(path)]) == 1
    err = capsys.readouterr().err
    assert "gov_kr_search step 1 typed 'Ada Lovelace'" in err


def test_a_shortened_value_is_invented_too(checker, tmp_path, capsys):
    path = tmp_path / "shortened.jsonl"
    path.write_text(json.dumps(row("gov_kr_search", "여권")) + "\n")
    assert checker.main([str(path)]) == 1
    assert "'여권'" in capsys.readouterr().err


def test_a_missing_file_is_a_fault_and_not_a_traceback(checker, tmp_path, capsys):
    assert checker.main([str(tmp_path / "gone.jsonl")]) == 1
    assert "unreadable" in capsys.readouterr().err


def test_a_line_that_is_not_json_is_a_fault(checker, tmp_path, capsys):
    path = tmp_path / "broken.jsonl"
    path.write_text(json.dumps(row("selenium_form_submit", "Ada Lovelace")) + "\nnot json\n")
    assert checker.main([str(path)]) == 1
    captured = capsys.readouterr()
    assert "broken.jsonl:2 is not JSON" in captured.err
    assert "FAIL" in captured.out


def test_a_type_text_step_with_no_text_is_a_fault(checker, tmp_path):
    rows = [{"task": "selenium_form_submit", "trace": [{"operation": "TYPE_TEXT", "target": "e1"}]}]
    assert checker.faults(rows, checker.tasks_by_name()) == [
        "row 1: selenium_form_submit step 1 typed None, which is not one of the values it was given"
    ]
