"""Outcome predicates and the statistics built on top of them."""

from datetime import date

import pytest

from jev_ra import bench
from jev_ra.bench import verify

DAY = verify.DEPART
FLIGHT_TEXT = (
    f"Zurich to London\n{DAY.strftime('%b')} {DAY.day}, {DAY.year}\nOne way\n"
    "7:05 AM - 8:15 AM\nSWISS\n1 hr 40 min\nNonstop\n$182\n"
    "9:30 AM - 10:40 AM\nBritish Airways\n1 hr 40 min\nNonstop\n$204"
)
FLIGHT_URL = "https://www.google.com/travel/flights/search?tfs=CBwQAhooEgoyMDI2LTA5LTIw"
KOREAN_FLIGHT_TEXT = (
    f"영국항공\n1시간 45분\n직항\n₩316,695\n{DAY.isoformat()} 취리히에서 출발하여 런던에 도착하는 항공편 가격 추적"
)


def test_wikipedia_wants_the_article_not_a_search_result():
    assert verify.wikipedia({"url": "https://en.wikipedia.org/wiki/G%C3%B6del%27s_incompleteness_theorems"})
    assert not verify.wikipedia({"url": "https://en.wikipedia.org/wiki/Main_Page"})
    assert not verify.wikipedia({"url": "https://en.wikipedia.org/w/index.php?search=incompleteness"})
    assert not verify.wikipedia({})


def test_flights_reads_the_page_in_whatever_language_it_came_back_in():
    assert verify.flights({"url": FLIGHT_URL, "text": KOREAN_FLIGHT_TEXT})
    assert not verify.flights({"url": FLIGHT_URL, "text": KOREAN_FLIGHT_TEXT.replace("런던", "리스본")})
    assert not verify.flights({"url": FLIGHT_URL, "text": KOREAN_FLIGHT_TEXT.replace("₩316,695", "")})


def test_flights_wants_the_search_the_cities_the_date_and_a_result_card():
    assert verify.flights({"url": FLIGHT_URL, "text": FLIGHT_TEXT})
    # The form filled in but never submitted.
    assert not verify.flights({"url": "https://www.google.com/travel/flights", "text": FLIGHT_TEXT})
    # Submitted, but nothing came back.
    assert not verify.flights(
        {"url": FLIGHT_URL, "text": f"Zurich to London\n{DAY.strftime('%b')} {DAY.day}, {DAY.year}\nNo results"}
    )
    # The wrong route.
    assert not verify.flights({"url": FLIGHT_URL, "text": FLIGHT_TEXT.replace("London", "Lisbon")})
    assert not verify.flights({"url": "", "text": ""})


def test_oliveyoung_accepts_either_the_sorted_url_or_the_active_tab():
    assert verify.oliveyoung_sort({"url": "https://www.oliveyoung.co.kr/...&prdSort=02&pageIdx=1"})
    assert verify.oliveyoung_sort(
        {"url": "https://www.oliveyoung.co.kr/x", "elements": [{"label": "신상품순", "selected": "true"}]}
    )
    assert not verify.oliveyoung_sort(
        {"url": "https://www.oliveyoung.co.kr/x", "elements": [{"label": "신상품순", "selected": "false"}]}
    )
    assert not verify.oliveyoung_sort({"url": "https://www.oliveyoung.co.kr/...&prdSort=01"})
    assert not verify.oliveyoung_sort({"url": "https://www.oliveyoung.co.kr/x", "elements": []})


def test_search_fact_wants_the_year_and_a_page_to_cite():
    assert verify.search_fact({"results": [{"url": "https://python.org/x", "text": "Python 3.12 arrived in 2023."}]})
    assert not verify.search_fact({"results": [{"url": "", "text": "Python 3.12 arrived in 2023."}]})
    assert not verify.search_fact({"results": [{"url": "https://python.org/x", "text": "Python 3.12 is out."}]})
    assert not verify.search_fact({"results": []})
    assert not verify.search_fact({})


def test_form_fill_wants_the_confirmation_with_the_typed_values():
    good = "Checkout\nOrder confirmed\nName: Ada Lovelace\nEmail: ada@example.com\nShipping: Express"
    assert verify.form_fill({"text": good})
    assert not verify.form_fill({"text": good.replace("Express", "Standard")})
    assert not verify.form_fill({"text": good.replace("Order confirmed", "")})
    assert not verify.form_fill({"text": ""})


def test_every_live_task_carries_a_predicate():
    assert all(callable(task.verify) for task in bench.LIVE_TASKS)
    assert {task.key for task in bench.LIVE_TASKS} == {
        "wikipedia",
        "flights",
        "oliveyoung_sort",
        "search_fact",
        "form_fill",
    }


def test_a_run_that_finishes_without_doing_the_task_is_a_failure():
    row = bench.verified({"status": "done", "url": "https://en.wikipedia.org/wiki/Main_Page"}, verify.wikipedia)
    assert row["ok"] is False
    assert row["reason"] == "finished but the page does not show the task done"


def test_a_run_that_finishes_and_verifies_is_a_success():
    row = bench.verified({"status": "done", "url": "https://en.wikipedia.org/wiki/Incompleteness"}, verify.wikipedia)
    assert row["ok"] is True


def test_without_a_predicate_the_status_decides():
    assert bench.verified({"status": "done"}, None)["ok"] is True
    assert bench.verified({"status": "blocked"}, None)["ok"] is False


def test_median_and_p90_over_the_runs():
    assert bench.median([]) is None
    assert bench.median([100]) == 100
    assert bench.median([100, 200, 300]) == 200
    assert bench.median([100, 200, 300, 400]) == 250
    assert bench.percentile([100, 200, 300, 400, 5000]) == 5000
    assert bench.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 9
    assert bench.percentile([]) is None


def row(task, ok, elapsed_ms, decisions=3, cost=0.001, reason=""):
    return {
        "task": task,
        "ok": ok,
        "status": "done" if ok else "blocked",
        "reason": reason,
        "elapsed_ms": elapsed_ms,
        "steps": 2,
        "decisions": decisions,
        "cost": cost,
        "text_calls": 0,
    }


def test_a_failed_verify_counts_against_the_rate_but_not_as_a_time():
    summary = bench.summarise(
        [
            row("wikipedia", True, 2000),
            row("wikipedia", True, 3000),
            row("wikipedia", True, 4000),
            row("wikipedia", False, 12, reason="blocked"),
        ]
    )[0]
    assert summary["runs"] == 4
    assert summary["successes"] == 3
    assert summary["success_rate"] == 0.75
    # The 12 ms failure must not drag the median down.
    assert summary["median_ms"] == 3000
    assert summary["p90_ms"] == 4000
    assert summary["failures"] == ["blocked"]


def test_a_task_that_never_verifies_has_no_median_at_all():
    summary = bench.summarise([row("flights", False, 1900, reason="blocked")] * 3)[0]
    assert summary["success_rate"] == 0.0
    assert summary["median_ms"] is None
    assert summary["median_cost"] is None


def test_the_ratio_table_needs_both_speed_and_every_run_verified():
    baseline = {"wikipedia": 23058, "flights": 66414}
    summaries = [
        {
            "task": "wikipedia",
            "runs": 5,
            "success_rate": 1.0,
            "median_ms": 2200,
            "median_decisions": 4,
            "median_cost": 0.0008,
        },
        {
            "task": "flights",
            "runs": 5,
            "success_rate": 0.8,
            "median_ms": 9000,
            "median_decisions": 14,
            "median_cost": 0.004,
        },
        {
            "task": "search_fact",
            "runs": 5,
            "success_rate": 1.0,
            "median_ms": 5000,
            "median_decisions": 4,
            "median_cost": 0.001,
        },
    ]
    rows = {item["task"]: item for item in bench.ratio_rows(summaries, baseline=baseline)}
    assert rows["wikipedia"]["ratio"] == pytest.approx(10.48, abs=0.01)
    assert rows["wikipedia"]["passed"] is True
    # Fast enough, but one run in five did not do the task.
    assert rows["flights"]["ratio"] == pytest.approx(7.38, abs=0.01)
    assert rows["flights"]["passed"] is False
    # No recorded browser-use row: it still has to verify every time.
    assert rows["search_fact"]["ratio"] is None
    assert rows["search_fact"]["passed"] is True


def test_the_markdown_table_renders_the_columns_it_is_given():
    table = bench.markdown_table(
        [{"task": "wikipedia", "median_ms": 2200, "p90_ms": None}], ("task", "median_ms", "p90_ms")
    )
    assert table.splitlines() == [
        "| task | median_ms | p90_ms |",
        "|---|---|---|",
        "| wikipedia | 2200 |  |",
    ]


def test_the_recorded_flight_asks_for_a_day_a_site_still_offers():
    assert date.today() < verify.DEPART
    task = next(t for t in bench.LIVE_TASKS if t.key == "flights")
    assert verify.DEPART.isoformat() in task.goal
    assert task.values["departure_date"] == verify.DEPART.isoformat()


def test_the_departure_reads_in_every_form_the_page_prints_it():
    pattern = verify.departure(date(2026, 10, 22))
    for text in ("2026-10-22", "Oct 22", "October 22", "10월 22일"):
        assert pattern.search(text)
    assert not pattern.search("Oct 2")
