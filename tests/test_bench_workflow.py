"""The public-bench workflow spends a key against live websites, so it may only run on demand."""

from pathlib import Path

from tests.test_ci_workflow import blocks

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "public-bench.yml"


def text():
    return WORKFLOW.read_text()


def test_the_workflow_is_well_formed():
    body = text()
    blocks(body)
    assert body.startswith("name: public-bench\n")
    assert "jobs:\n" in body


def test_nothing_here_fires_on_a_push_or_a_pull_request():
    body = text()
    trigger = body.split("\non:\n", 1)[1].split("\njobs:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert "push:" not in trigger
    assert "pull_request:" not in trigger
    assert "schedule:" not in trigger


def test_the_key_comes_from_secrets_and_the_job_stops_without_one():
    body = text()
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" in body
    assert "This job needs the OPENROUTER_API_KEY repository secret." in body
    # The key is an environment value, never echoed and never written to the run directory.
    assert "echo $OPENROUTER_API_KEY" not in body
    assert "--api_key" not in body


def test_both_runners_run_and_the_task_count_is_an_input():
    body = text()
    assert "python -m bench.public.om2w" in body
    assert "python -m bench.public.webvoyager" in body
    assert '--tasks "${{ inputs.tasks }}"' in body
    assert 'default: "3"' in body
    assert "inputs.judge && '--judge'" in body


def test_the_trajectories_are_uploaded_so_a_run_can_be_read_after_it():
    body = text()
    assert "actions/upload-artifact@v4" in body
    assert "path: bench/public/runs/" in body


def test_the_job_drives_a_real_chrome_it_started_itself():
    body = text()
    assert "browser-actions/setup-chrome@v1" in body
    assert "--remote-debugging-port=9222" in body
    assert "BU_CDP_URL: http://127.0.0.1:9222" in body
    assert "--lang=en-US" in body


def test_the_text_helper_is_configured_because_typing_needs_one():
    body = text()
    assert "JEV_RA_TEXT_MODEL:" in body
    assert "JEV_RA_TEXT_BASE_URL: https://openrouter.ai/api/v1" in body


def test_the_workflow_says_why_its_numbers_are_not_the_published_ones():
    reason = [line.strip(" #") for line in text().splitlines() if line.strip().startswith("#")]
    assert any("headless" in line for line in reason), reason
    assert any("bench/public/README.md" in line for line in reason), reason
