"""The time a run spent waiting for a person is printed apart from the time it spent working."""

from jev_ra import cli, profile

RESULT = {
    "status": "done",
    "reason": "goal_achieved",
    "url": "https://shop.test/",
    "steps": [],
    "decisions": 1,
    "text_calls": [],
    "elapsed_ms": 9_000,
    "cost": 0.0,
    "run_id": "abc",
}


def test_the_run_summary_says_how_long_it_waited_for_a_person():
    lines = cli.result_lines({**RESULT, "human_wait_ms": 7_500})
    assert any("7500 ms" in line and "person" in line for line in lines)


def test_a_run_that_never_waited_says_nothing_about_it():
    assert not any("person" in line for line in cli.result_lines({**RESULT, "human_wait_ms": 0}))


def test_the_profile_names_the_wait_inside_the_time_outside_the_steps():
    lines = profile.table({**RESULT, "human_wait_ms": 7_500})
    assert any("7500 ms" in line and "person" in line for line in lines)
    assert not any("person" in line for line in profile.table(RESULT))
