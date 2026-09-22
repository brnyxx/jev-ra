"""The per-step categories have to add up, or the profile is worse than no profile."""

import pytest

from jev_ra import bench, config
from jev_ra.agent import Agent
from jev_ra.profile import CATEGORIES, MEASURED, NullTimer, StepTimer, shares, table, totals
from tests.test_agent import DONE, FakeSession, agent_with, decider

CLICK = {
    "operation": {"choice": "CLICK", "confidence": 0.9, "probabilities": {"CLICK": 1.0}},
    "click_target": {"choice": "e2", "confidence": 0.9, "probabilities": {"e2": 1.0}},
    "goal_achieved": {"noul": 0.1},
}


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, milliseconds):
        self.now += milliseconds / 1000


def test_the_categories_sum_to_the_step_total():
    clock = FakeClock()
    timer = StepTimer(clock)
    for category, milliseconds in (("snapshot", 30), ("actions", 5), ("decide", 300), ("act", 40), ("wait", 60)):
        with timer.measure(category):
            clock.advance(milliseconds)
    clock.advance(7)
    result = timer.result()
    assert result["snapshot_ms"] == 30
    assert result["decide_ms"] == 300
    assert result["overhead_ms"] == 7
    assert result["total_ms"] == 442
    assert sum(result[name] for name in CATEGORIES) == result["total_ms"]


def test_overhead_absorbs_the_rounding_so_the_parts_always_add_up():
    clock = FakeClock()
    timer = StepTimer(clock)
    for category in MEASURED:
        with timer.measure(category[:-3]):
            clock.advance(0.4)
    clock.advance(0.4)
    result = timer.result()
    assert sum(result[name] for name in CATEGORIES) == result["total_ms"]
    assert result["overhead_ms"] >= 0


def test_a_category_can_be_charged_time_something_else_measured():
    clock = FakeClock()
    timer = StepTimer(clock)
    timer.add("decide", 312)
    clock.advance(320)
    result = timer.result()
    assert result["decide_ms"] == 312
    assert result["overhead_ms"] == 8


def test_an_unknown_category_is_refused_rather_than_silently_lost():
    with pytest.raises(KeyError, match="thinking is not one of"), StepTimer().measure("thinking"):
        pass


def test_the_null_timer_has_the_same_shape_and_costs_nothing():
    timer = NullTimer()
    with timer.measure("snapshot"):
        pass
    timer.add("decide", 100)
    assert timer.result() == dict.fromkeys((*CATEGORIES, "total_ms"), 0)


def test_totals_add_every_step_up():
    steps = [
        {"snapshot_ms": 10, "actions_ms": 1, "decide_ms": 300, "act_ms": 20, "wait_ms": 50, "overhead_ms": 2},
        {"snapshot_ms": 12, "actions_ms": 1, "decide_ms": 280, "act_ms": 22, "wait_ms": 55, "overhead_ms": 3},
    ]
    assert totals(steps) == {
        "snapshot_ms": 22,
        "actions_ms": 2,
        "decide_ms": 580,
        "act_ms": 42,
        "wait_ms": 105,
        "overhead_ms": 5,
    }


def test_shares_report_what_no_step_accounted_for():
    steps = [{"snapshot_ms": 100, "actions_ms": 0, "decide_ms": 300, "act_ms": 0, "wait_ms": 0, "overhead_ms": 0}]
    rows = {row["category"]: row for row in shares(steps, wall_ms=1000)}
    assert rows["decide"]["share"] == pytest.approx(0.3)
    assert rows["outside steps"]["ms"] == 600
    assert sum(row["ms"] for row in shares(steps, 1000)) == 1000


def test_shares_survive_a_run_with_no_wall_time():
    assert all(row["share"] is None for row in shares([], wall_ms=0))


def test_every_recorded_step_carries_the_profile():
    agent = agent_with(decider([CLICK, DONE]))
    result = agent.run("find flights")
    assert result.status == "done"
    step = result.steps[0]
    for name in (*CATEGORIES, "total_ms"):
        assert name in step, f"steps are missing {name}"
    assert sum(step[name] for name in CATEGORIES) == step["total_ms"]


def test_a_fake_decider_still_leaves_the_categories_consistent():
    agent = Agent(session=FakeSession(), config=config.load({}), decide=decider([CLICK, CLICK, CLICK]))
    result = agent.run("find flights")
    for step in result.steps:
        assert sum(step[name] for name in CATEGORIES) == step["total_ms"]


@pytest.mark.browser
def test_a_real_run_attributes_most_of_its_time(session):
    measured = bench.run_offline(config.load({}), session=session)
    rows = {row["category"]: row for row in bench.profile_rows(measured)}
    assert set(rows) == {"snapshot", "actions", "decide", "act", "wait", "overhead", "outside steps"}
    assert rows["snapshot"]["ms"] > 0
    assert rows["wait"]["ms"] > 0
    # The scripted decider makes no network call, so the wait dominates offline.
    assert rows["decide"]["ms"] < rows["wait"]["ms"]
    assert rows["outside steps"]["share"] < 0.5


@pytest.mark.browser
def test_the_profile_table_renders(session):
    table = bench.profile_table(bench.run_offline(config.load({}), session=session))
    assert table.splitlines()[0] == "| category | ms | share |"
    assert "| snapshot |" in table


def test_the_table_names_every_category_and_adds_them_up():
    payload = {
        "run_id": "abc123",
        "status": "done",
        "reason": "goal_achieved",
        "elapsed_ms": 1500,
        "steps": [
            {
                "n": 1,
                "operation": "CLICK",
                "target_label": "Search flights",
                "snapshot_ms": 100,
                "actions_ms": 1,
                "decide_ms": 300,
                "act_ms": 40,
                "wait_ms": 200,
                "overhead_ms": 9,
                "total_ms": 650,
            }
        ],
    }
    lines = table(payload)
    assert lines[0] == "run abc123 · done · goal_achieved"
    assert lines[2].split() == ["n", "operation", "target", *(name[:-3] for name in CATEGORIES), "total"]
    assert lines[4].split() == ["1", "CLICK", "Search", "flights", "100", "1", "300", "40", "200", "9", "650"]
    assert lines[5].split() == ["total", "1", "step", "100", "1", "300", "40", "200", "9", "650"]
    assert lines[-1] == "1500 ms in the run, 850 ms of it outside the steps (the first page, and the last)"


def test_a_run_with_no_steps_still_renders():
    assert table({"run_id": "abc123", "status": "escalate", "reason": "stale", "steps": []})[4].split() == [
        "total",
        "0",
        "steps",
        *["0"] * 7,
    ]
