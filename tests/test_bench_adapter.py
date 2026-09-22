"""The public-benchmark adapter: one frame per landed step, and never one frame out."""

import base64
from pathlib import Path

import pytest

from bench.public.adapter import Adapter
from jev_ra import config
from jev_ra.browser.session import StalePage
from jev_ra.decide import Reply

ACTIONS = [
    {"id": "e1", "node": 1, "role": "textbox", "kind": "fill", "label": "Search", "value": ""},
    {"id": "e2", "node": 2, "role": "button", "kind": "click", "label": "Go"},
    {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
]

ELEMENTS = [
    {"ref": "e1", "node": 1, "role": "textbox", "label": "Search", "value": ""},
    {"ref": "e2", "node": 2, "role": "button", "label": "Go"},
]

JPEG = b"\xff\xd8\xff\xe0jpeg"
PNG = b"\x89PNG\r\n\x1a\n"


def page(marker, url="https://example.test/", text="Results for lasagna"):
    return {
        "url": url,
        "title": "Example",
        "text": text,
        "elements": ELEMENTS,
        "actions": ACTIONS,
        "marker": marker,
        "page_key": [0, url, 0, 0, 1280, 900, [[1, "", None, None, False, False]]],
        "guards": {},
        "omitted": 0,
    }


class FakeSession:
    """Replays pages and hands out recognisable image bytes; `stale` makes act() refuse."""

    def __init__(self, pages=None, stale=0):
        self.pages = list(pages or [page(n) for n in range(10)])
        self.index = 0
        self.stale = stale
        self.max_elements = 250
        self.shots = 0
        self.closed = False

    def open(self, url):
        return self.observe()

    def observe(self, timer=None):
        return self.pages[min(self.index, len(self.pages) - 1)]

    def act(self, action, page, text=None, timer=None):
        if self.stale > 0:
            self.stale -= 1
            raise StalePage("Page changed since this decision. Observe again.")
        self.index = min(self.index + 1, len(self.pages) - 1)
        return {"executed": action["id"]}

    def screenshot(self):
        self.shots += 1
        return JPEG

    def call(self, method, timeout=None, **params):
        assert method == "Page.captureScreenshot"
        assert params["format"] == "png"
        self.shots += 1
        return {"data": base64.b64encode(PNG).decode()}

    def close(self):
        self.closed = True


def answer(choice, confidence=0.9):
    return {"choice": choice, "confidence": confidence, "probabilities": {choice: 1.0}}


def decider(script):
    """One scripted answer set per request; the last one repeats."""
    steps = list(script)
    seen = []

    def decide(state, questions):
        answers = dict(steps[min(len(seen), len(steps) - 1)])
        seen.append(questions)
        for name in list(answers):
            if name not in questions:
                del answers[name]
        return Reply(answers=answers, latency_ms=10, usage={"cost": 0.0001})

    decide.seen = seen
    return decide


CLICK = {"operation": answer("CLICK"), "click_target": answer("e2"), "goal_achieved": {"noul": 0.1}}
DONE = {"operation": answer("DONE"), "goal_achieved": {"noul": 0.9}}


def adapter_for(script, shots, session=None, image="jpg"):
    return Adapter(shots, config=config.load({}), session=session or FakeSession(), decide=decider(script), image=image)


def test_a_run_writes_one_frame_for_the_navigation_and_one_per_step(tmp_path):
    with adapter_for([CLICK, CLICK, DONE], tmp_path / "trajectory") as adapter:
        result = adapter.run("find the lasagna recipe", url="https://example.test/")
    assert result["status"] == "done"
    assert result["steps"] == 2
    names = sorted(path.name for path in (tmp_path / "trajectory").iterdir())
    assert names == ["0000.jpg", "0001.jpg", "0002.jpg"]
    assert [entry["step"] for entry in result["trajectory"]] == [0, 1, 2]
    assert [entry["operation"] for entry in result["trajectory"]] == ["NAVIGATE", "CLICK", "CLICK"]
    assert all(Path(entry["screenshot_path"]).read_bytes() == JPEG for entry in result["trajectory"])


def test_the_trajectory_names_the_page_each_frame_was_taken_on(tmp_path):
    pages = [page(0, url="https://example.test/"), page(1, url="https://example.test/results")]
    session = FakeSession(pages=pages)
    with adapter_for([CLICK, DONE], tmp_path / "t", session=session) as adapter:
        result = adapter.run("find the lasagna recipe", url="https://example.test/")
    assert [entry["url"] for entry in result["trajectory"]] == [
        "https://example.test/",
        "https://example.test/results",
    ]
    assert result["final_url"] == "https://example.test/results"


def test_an_action_that_never_landed_leaves_no_frame_behind(tmp_path):
    """A stale act() is retried; the retry must not leave a frame the trajectory cannot name."""
    session = FakeSession(stale=2)
    with adapter_for([CLICK, CLICK, CLICK, DONE], tmp_path / "t", session=session) as adapter:
        result = adapter.run("find the lasagna recipe", url="https://example.test/")
    assert session.shots == len(result["trajectory"])
    assert result["steps"] == 1
    assert [entry["step"] for entry in result["trajectory"]] == [0, 1]


def test_the_answer_is_the_text_of_the_page_the_run_finished_on(tmp_path):
    with adapter_for([DONE], tmp_path / "t") as adapter:
        result = adapter.run("find the lasagna recipe", url="https://example.test/")
    assert result["final_answer"] == "Results for lasagna"
    assert result["cost"] == pytest.approx(0.0001)


def test_a_blank_page_answers_nothing_rather_than_an_empty_string(tmp_path):
    session = FakeSession(pages=[page(0, text="")])
    with adapter_for([DONE], tmp_path / "t", session=session) as adapter:
        result = adapter.run("find the lasagna recipe", url="https://example.test/")
    assert result["final_answer"] is None


def test_start_and_step_drive_the_same_session_one_action_at_a_time(tmp_path):
    session = FakeSession()
    adapter = adapter_for([CLICK], tmp_path / "t", session=session)
    try:
        opened = adapter.start("https://example.test/")
        assert opened["status"] == "opened"
        assert opened["url"] == "https://example.test/"
        assert [element["ref"] for element in opened["elements"]] == ["e1", "e2"]
        assert opened["screenshot_path"].endswith("0000.jpg")
        seen = adapter.step("click Go")
        assert seen["screenshot_path"].endswith("0001.jpg")
        assert seen["status"] == "budget"
    finally:
        adapter.close()
    assert session.closed


def test_a_png_harness_gets_real_png_bytes(tmp_path):
    with adapter_for([CLICK, DONE], tmp_path / "t", image="png") as adapter:
        result = adapter.run("find the lasagna recipe", url="https://example.test/")
    frames = sorted((tmp_path / "t").iterdir())
    assert [path.name for path in frames] == ["0000.png", "0001.png"]
    assert all(path.read_bytes() == PNG for path in frames)
    assert result["trajectory"][0]["screenshot_path"].endswith("0000.png")


def test_an_unknown_image_format_is_refused_before_anything_is_opened(tmp_path):
    with pytest.raises(ValueError, match="image must be one of"):
        Adapter(tmp_path / "t", config=config.load({}), session=FakeSession(), decide=decider([DONE]), image="gif")
