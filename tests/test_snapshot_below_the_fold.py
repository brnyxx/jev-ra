"""The page a run ends on is the whole document, not the strip that happens to be on screen."""

import pytest

pytestmark = pytest.mark.browser

FIXTURE = "/sites/below-the-fold-article.html"
STORY = "reasonable grounds to believe"


def test_visible_text_is_still_only_what_the_viewport_shows(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert "UN experts publish their findings" in page["text"]
    assert STORY not in page["text"]


def test_the_document_text_carries_the_story_under_the_fold(session, fixture_server):
    page = session.open(fixture_server + FIXTURE)
    assert STORY in page["doc_text"]
    assert "UN experts publish their findings" in page["doc_text"]
    assert len(page["doc_text"]) > len(page["text"])


def test_the_page_a_run_reports_is_the_document_not_the_viewport(session, fixture_server):
    from jev_ra.agent import Agent
    from jev_ra.decide import Reply

    def done(_state, questions):
        criteria = questions["operation"]["criteria"]
        answers = {
            "operation": {
                "choice": "DONE",
                "confidence": 0.95,
                "probabilities": {key: (1.0 if key == "DONE" else 0.0) for key in criteria},
            },
            "goal_achieved": {"noul": 0.95},
        }
        return Reply(answers=answers, model="scripted", latency_ms=1, usage={"cost": 0.0})

    agent = Agent(session=session, decide=done)
    page = session.open(fixture_server + FIXTURE)
    result = agent.run("Read this story.", url=fixture_server + FIXTURE)
    assert result.status == "done"
    reported = result.final_page["text"]
    assert STORY in reported
    assert reported.startswith(page["text"])


def test_what_the_reader_can_see_is_never_dropped_for_what_is_below_it():
    from jev_ra.agent import page_text

    merged = page_text({"text": "Theme\nDark", "doc_text": "Skip to content\nArticle body\nTheme"})
    assert merged.startswith("Theme\nDark")
    assert "Article body" in merged
    assert merged.count("Theme") == 1
    assert page_text({"text": "only visible"}) == "only visible"
    assert page_text({"doc_text": "only document"}) == "only document"
