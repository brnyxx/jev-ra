"""The WebVoyager runner: a layout its own evaluator parses, and dated tasks held back."""

import json
from datetime import date

import pytest

from bench.public import webvoyager
from jev_ra import config
from jev_ra.errors import JevRaError
from tests.test_bench_adapter import CLICK, DONE, FakeSession, decider

TASKS = [
    {
        "web_name": "Allrecipes",
        "id": "Allrecipes--0",
        "ques": "Find a vegetarian lasagna recipe.",
        "web": "https://www.allrecipes.com/",
    },
    {
        "web_name": "Allrecipes",
        "id": "Allrecipes--1",
        "ques": "Find a chocolate cake recipe.",
        "web": "https://www.allrecipes.com/",
    },
    {"web_name": "ArXiv", "id": "ArXiv--0", "ques": "Find the latest paper on retrieval.", "web": "https://arxiv.org/"},
    {
        "web_name": "Booking",
        "id": "Booking--5",
        "ques": "Search a hotel in Bali from Jan 1 to Jan 4, 2024.",
        "web": "https://www.booking.com/",
    },
    {
        "web_name": "Booking",
        "id": "Booking--0",
        "ques": "Find a Mexico hotel with deals for December 25-26.",
        "web": "https://www.booking.com/",
    },
    {
        "web_name": "Booking",
        "id": "Booking--99",
        "ques": "Find the cheapest hotel in Seoul with free wifi.",
        "web": "https://www.booking.com/",
    },
    {
        "web_name": "Google Flights",
        "id": "Google Flights--3",
        "ques": "Find a flight on 03/20/2024.",
        "web": "https://www.google.com/travel/flights/",
    },
]

TODAY = date(2026, 9, 22)


def test_a_dated_booking_task_is_held_back_and_says_which_date():
    assert "2024" in webvoyager.past_dated(TASKS[3], TODAY)
    assert "December" in webvoyager.past_dated(TASKS[4], TODAY)
    assert webvoyager.past_dated(TASKS[6], TODAY) == "names 2024, which is past"


def test_an_evergreen_booking_task_still_runs():
    assert webvoyager.past_dated(TASKS[5], TODAY) is None


def test_a_date_on_a_site_that_is_not_time_sensitive_is_left_alone():
    dated = {"web_name": "ArXiv", "id": "ArXiv--14", "ques": "Papers announced in October 2023?", "web": "https://x/"}
    assert webvoyager.past_dated(dated, TODAY) is None


def test_the_selection_walks_the_sites_and_reports_what_it_held_back():
    chosen, skipped = webvoyager.select(TASKS, 3, today=TODAY)
    assert [task["id"] for task in chosen] == ["Allrecipes--0", "ArXiv--0", "Booking--99"]
    assert [row["id"] for row in skipped] == ["Booking--5", "Booking--0", "Google Flights--3"]
    assert webvoyager.select(TASKS, 3, today=TODAY)[0] == chosen


def test_named_tasks_are_run_even_when_they_are_dated():
    chosen, skipped = webvoyager.select(TASKS, ids=["Booking--5"])
    assert [task["id"] for task in chosen] == ["Booking--5"]
    assert skipped == []
    with pytest.raises(JevRaError, match="No such WebVoyager task: nope"):
        webvoyager.select(TASKS, ids=["nope"])


def run_one(task, out, script, session=None):
    return webvoyager.run_task(
        task, out, config.load({}), max_steps=10, session=session or FakeSession(), decide=decider(script)
    )


def test_the_written_trajectory_is_what_the_evaluator_parses(tmp_path):
    row = run_one(TASKS[0], tmp_path, [CLICK, CLICK, DONE])
    directory = tmp_path / "taskAllrecipes--0"
    spoken = json.loads((directory / "interact_messages.json").read_text())
    assert len(spoken) > 1
    opening = spoken[1]["content"]
    assert "Now given a task:" in opening
    assert "Please interact with" in opening
    assert "Find a vegetarian lasagna recipe." in opening.split("Please interact with")[0]
    assert "Action: ANSWER" in spoken[-1]["content"]
    assert sorted(path.name for path in directory.glob("*.png")) == [
        "screenshot0.png",
        "screenshot1.png",
        "screenshot2.png",
    ]
    assert row["frames"] == 3


def test_the_answer_carries_no_bracket_that_would_truncate_it(tmp_path):
    run_one(TASKS[0], tmp_path, [DONE])
    spoken = json.loads((tmp_path / "taskAllrecipes--0" / "interact_messages.json").read_text())
    answer = spoken[-1]["content"].split("ANSWER; [", 1)[1]
    assert answer.endswith("]")
    assert "]" not in answer[:-1]


def test_a_run_that_answered_nothing_still_says_so_in_the_evaluators_grammar(tmp_path):
    result = {"status": "blocked", "final_answer": None, "final_page_text": None, "trajectory": []}
    spoken = webvoyager.messages(TASKS[0], result)
    assert spoken[-1]["content"].endswith("[no answer; the run ended on the page above]")


def test_a_one_sentence_answer_is_what_the_evaluator_is_shown(tmp_path):
    result = {
        "status": "done",
        "final_answer": "The recipe takes 1 hour 20 minutes.",
        "final_page_text": "Lasagna. Total 1 hour 20 minutes. Ingredients ...",
        "trajectory": [],
    }
    spoken = webvoyager.messages(TASKS[0], result)
    assert spoken[-1]["content"].endswith("[The recipe takes 1 hour 20 minutes.]")


def test_without_a_sentence_the_page_it_finished_on_is_still_shown(tmp_path):
    result = {
        "status": "blocked",
        "final_answer": None,
        "final_page_text": "Lasagna. Total 1 hour 20 minutes.",
        "trajectory": [],
    }
    spoken = webvoyager.messages(TASKS[0], result)
    assert spoken[-1]["content"].endswith("[Lasagna. Total 1 hour 20 minutes.]")


def test_the_evaluators_own_output_is_read_back_per_task():
    printed = "\n".join(
        [
            "--------------------- /runs/wv/taskAllrecipes--0 ---------------------",
            "Calling gpt4v API to get the auto evaluation......",
            "Auto_eval_res: 1",
            "",
            "--------------------- /runs/wv/taskArXiv--0 ---------------------",
            "Auto_eval_res: 0",
            "",
            "--------------------- /runs/wv/taskESPN--2 ---------------------",
            "Auto_eval_res: None",
            "Not find answer for /runs/wv/taskGitHub--1",
            "Not find answer for /runs/wv/taskApple--4 only system messages",
        ]
    )
    assert webvoyager.read_verdicts(printed) == {
        "taskAllrecipes--0": 1,
        "taskArXiv--0": 0,
        "taskESPN--2": 0,
        "taskGitHub--1": 0,
        "taskApple--4": 0,
    }


def test_an_unjudged_pass_says_so_and_names_what_was_held_back():
    rows = [
        {
            "id": "Allrecipes--0",
            "status": "done",
            "reason": "goal_achieved",
            "steps": 3,
            "elapsed_ms": 4000,
            "cost": 0.002,
        }
    ]
    plain = webvoyager.report(rows, skipped=[{"id": "Booking--0", "why": "dated"}])
    assert "not judged" in plain
    assert "1 time-sensitive tasks held back: Booking--0" in plain
    assert "1/1 = 100.0% by the WebVoyager evaluator" in webvoyager.report(rows, {"taskAllrecipes--0": 1})


def test_judging_an_empty_directory_is_refused_before_a_key_is_needed(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(JevRaError, match="No trajectories to judge"):
        webvoyager.judge(tmp_path / "empty")
