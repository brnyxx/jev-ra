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
    result = agent.run("Read this story.", url=fixture_server + FIXTURE)
    assert result.status == "done"
    assert STORY in result.final_page["text"]
