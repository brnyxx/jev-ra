"""The Online-Mind2Web runner: a submission that passes the benchmark's own validation rules."""

import json
import re
from pathlib import Path

import pytest

from bench.public import om2w
from jev_ra import config
from jev_ra.errors import JevRaError
from tests.test_bench_adapter import CLICK, DONE, FakeSession, decider, page

TASKS = [
    {
        "task_id": "aaa111",
        "confirmed_task": "Find a lasagna recipe.",
        "website": "https://a.test/",
        "reference_length": 6,
        "level": "easy",
    },
    {
        "task_id": "bbb222",
        "confirmed_task": "Find a store near 90028.",
        "website": "https://b.test/",
        "reference_length": 8,
        "level": "medium",
    },
    {
        "task_id": "ccc333",
        "confirmed_task": "Compare two flights.",
        "website": "https://c.test/",
        "reference_length": 12,
        "level": "hard",
    },
    {
        "task_id": "ddd444",
        "confirmed_task": "Open the help page.",
        "website": "https://d.test/",
        "reference_length": 4,
        "level": "easy",
    },
]

# The v2 submission rules, README.md section 6 of the benchmark repository.
TASK_ID = re.compile(r"^[A-Za-z0-9_\-]+$")
SCREENSHOT = re.compile(r"^(\d{4}|\d+_full_screenshot_\d+)\.(png|jpg|jpeg|webp)$")
RESULT_KEYS = {"schema_version", "task", "task_id", "agent_final_answer", "reference_length", "action_history"}
STEP_KEYS = {"step", "screenshot", "url", "action", "action_status", "thought"}


def validate(directory):
    """Every v2 rule a consumer enforces, applied to one written submission directory."""
    result = json.loads((directory / "result.json").read_text())
    assert set(result) <= RESULT_KEYS
    assert RESULT_KEYS - {"agent_final_answer"} <= set(result)
    assert result["schema_version"] == "online-mind2web-v2"
    assert TASK_ID.match(result["task_id"])
    assert result["task"]
    assert isinstance(result["reference_length"], int) and result["reference_length"] >= 1
    history = result["action_history"]
    assert history
    names = []
    for index, step in enumerate(history):
        assert set(step) <= STEP_KEYS, step
        assert step["step"] == index
        assert "thought" in step
        assert step["action"]
        assert SCREENSHOT.match(step["screenshot"]), step["screenshot"]
        assert (directory / "trajectory" / step["screenshot"]).exists()
        names.append(step["screenshot"])
        suffix = step["action"].rsplit("|", 1)[-1].strip() if "|" in step["action"] else None
        if step.get("action_status"):
            assert step["action_status"] == suffix
        else:
            assert suffix not in {"SUCCESS", "FAILED"}
    assert names == sorted(names)
    assert history[-1]["action"].startswith("TASK_COMPLETE")
    if result.get("agent_final_answer") is not None:
        answer = history[-1]["action"].split("ANSWER:", 1)[1].strip()
        assert answer == result["agent_final_answer"].strip()
    return result


def run_one(task, out, script, session=None):
    return om2w.run_task(
        task, out, config.load({}), max_steps=10, session=session or FakeSession(), decide=decider(script)
    )


def test_a_finished_task_is_written_in_the_v2_layout_and_passes_its_rules(tmp_path):
    row = run_one(TASKS[0], tmp_path, [CLICK, CLICK, DONE])
    result = validate(tmp_path / "aaa111")
    assert result["task_id"] == "aaa111"
    assert result["reference_length"] == 6
    assert [step["action"].split()[0] for step in result["action_history"]] == [
        "page",
        "CLICK",
        "CLICK",
        "TASK_COMPLETE",
    ]
    assert row["status"] == "done"
    assert row["steps"] == 2


def test_the_navigation_is_step_zero_and_names_the_page_it_landed_on(tmp_path):
    run_one(TASKS[0], tmp_path, [DONE])
    result = json.loads((tmp_path / "aaa111" / "result.json").read_text())
    first = result["action_history"][0]
    assert first["action"] == "page -> NAVIGATE -> open the website the task starts from | SUCCESS"
    assert first["action_status"] == "SUCCESS"
    assert first["url"] == "https://example.test/"


def test_no_answer_is_claimed_and_no_reasoning_is_put_in_the_history(tmp_path):
    """The benchmark asks for factual actions only, and jev-ra writes no prose to claim."""
    run_one(TASKS[0], tmp_path, [CLICK, DONE])
    result = json.loads((tmp_path / "aaa111" / "result.json").read_text())
    assert result["agent_final_answer"] is None
    assert all(step["thought"] is None for step in result["action_history"])
    assert result["action_history"][-1]["action"] == "TASK_COMPLETE"


def test_an_action_the_page_ignored_is_recorded_as_failed(tmp_path):
    session = FakeSession(pages=[page(7)])
    run_one(TASKS[0], tmp_path, [CLICK, DONE], session=session)
    result = json.loads((tmp_path / "aaa111" / "result.json").read_text())
    click = result["action_history"][1]
    assert click["action"].endswith("| FAILED")
    assert click["action_status"] == "FAILED"
    validate(tmp_path / "aaa111")


def test_a_wait_carries_no_status_because_it_changes_nothing(tmp_path):
    entry = {"operation": "WAIT", "target": "wait", "label": "Wait", "landed": False}
    action, status = om2w.render(entry)
    assert status is None
    assert action == "WAIT page -> wait for the page to finish updating"


def test_ten_tasks_are_drawn_from_every_level_and_the_draw_repeats(tmp_path):
    chosen = om2w.select(TASKS, 3)
    assert [task["level"] for task in chosen] == ["easy", "medium", "hard"]
    assert om2w.select(TASKS, 3) == chosen
    assert om2w.select(TASKS, 99) == TASKS
    assert [task["task_id"] for task in om2w.select(TASKS, 2, level="easy")] == ["aaa111", "ddd444"]


def test_named_tasks_are_run_in_the_order_they_were_named(tmp_path):
    assert [task["task_id"] for task in om2w.select(TASKS, ids=["ccc333", "aaa111"])] == ["ccc333", "aaa111"]
    with pytest.raises(JevRaError, match="No such Online-Mind2Web task: zzz"):
        om2w.select(TASKS, ids=["zzz"])


def test_a_local_task_file_is_read_instead_of_downloading_anything(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(TASKS))
    tasks, source = om2w.fetch_tasks(path)
    assert tasks == TASKS
    assert source == str(path)


def test_the_judge_labels_are_read_back_per_task_and_gaps_are_named(tmp_path):
    path = tmp_path / "judged.json"
    path.write_text(
        json.dumps({"task_id": "aaa111", "predicted_label": 1})
        + "\n"
        + json.dumps({"task_id": "bbb222", "predicted_label": 0})
        + "\n"
    )
    verdict = om2w.read_labels(path, ["aaa111", "bbb222", "ccc333"])
    assert verdict["labels"] == {"aaa111": 1, "bbb222": 0}
    assert verdict["missing"] == ["ccc333"]


def test_an_unjudged_pass_says_so_instead_of_reporting_a_rate(tmp_path):
    rows = [
        {
            "task_id": "aaa111",
            "level": "easy",
            "status": "done",
            "reason": "goal_achieved",
            "steps": 2,
            "elapsed_ms": 1000,
            "cost": 0.001,
        },
    ]
    assert "not judged" in om2w.report(rows)
    assert "1/1 = 100.0% by WebJudge" in om2w.report(rows, {"aaa111": 1})
    assert "0/1 = 0.0% by WebJudge" in om2w.report(rows, {"aaa111": 0})


def test_judging_an_empty_directory_is_refused_before_a_key_is_needed(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(JevRaError, match="No trajectories to judge"):
        om2w.judge(tmp_path / "empty")


def test_the_pinned_upstream_repositories_are_named_by_commit():
    from bench.public.vendor import PINS

    assert set(PINS) == {"online-mind2web", "webvoyager"}
    for pin in PINS.values():
        assert re.fullmatch(r"[0-9a-f]{40}", pin.commit), pin
        assert pin.url.startswith("https://github.com/")


def test_the_vendor_and_run_directories_are_never_committed():
    ignored = Path(__file__).resolve().parents[1] / ".gitignore"
    text = ignored.read_text()
    for name in ("bench/public/vendor/", "bench/public/data/", "bench/public/runs/"):
        assert name in text
