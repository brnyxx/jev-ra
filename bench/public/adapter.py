"""One act/observe surface a public benchmark harness can drive, with a screenshot per step.

Every public web benchmark wants the same three things from an agent: start somewhere, take steps,
and hand back a trajectory it can show a judge. jev-ra's own API is a single `Agent.run()` that
never stops to be photographed, so the screenshots are taken by a session that sits between the
agent and Chrome: it saves the viewport after every action that actually landed, which is exactly
once per recorded step, so a frame can never be paired with the wrong action.
"""

import base64
import logging
from pathlib import Path

from jev_ra.agent import Agent
from jev_ra.browser.actions import element_view
from jev_ra.browser.session import EVALUATE_TIMEOUT_S, Session
from jev_ra.config import load

logger = logging.getLogger(__name__)

MAX_STEPS = 25
# The page a run finished on, for a judge that is shown it beside the screenshot. It is not an
# answer: a question-shaped goal gets one sentence of its own from jev-ra's text helper, and a
# goal that is an instruction gets none at all.
ANSWER_CHARS = 600
IMAGES = {"jpg": "jpeg", "png": "png"}
NAVIGATE = "NAVIGATE"


def shoot(session, image):
    """The viewport as bytes, in the format the harness's own judge expects."""
    if image == "jpg":
        return session.screenshot()
    shot = session.call("Page.captureScreenshot", timeout=EVALUATE_TIMEOUT_S, format=IMAGES[image])
    return base64.b64decode(shot["data"])


class Recorder:
    """A session that saves the viewport once per action the agent lands, and no other time.

    The agent acts, then observes; a frame is due after an action returns and is taken by the next
    observation that settles. An action that raised never marks a frame due, and an observation
    that never settles ends the run without recording a step, so frames and steps stay in step.
    """

    def __init__(self, session, shots, image="jpg"):
        self.session = session
        self.shots = Path(shots)
        self.image = image
        self.frames = []
        self.due = False
        self.shots.mkdir(parents=True, exist_ok=True)

    def __getattr__(self, name):
        return getattr(self.session, name)

    def open(self, url):
        """Navigate, observe, and save the page the run starts on."""
        page = self.session.open(url)
        self.capture(page)
        return page

    def act(self, action, page, text=None, timer=None):
        """Execute one action and mark a frame due for the observation that follows it."""
        executed = self.session.act(action, page, text=text, timer=timer)
        self.due = True
        return executed

    def observe(self, timer=None):
        """Observe, and save the viewport when the last action left a frame due."""
        page = self.session.observe(timer)
        if self.due:
            self.due = False
            self.capture(page)
        return page

    def capture(self, page):
        """Write one frame and remember the address it was taken at."""
        path = self.shots / f"{len(self.frames):04d}.{self.image}"
        path.write_bytes(shoot(self.session, self.image))
        frame = {"path": path, "url": page.get("url", "")}
        self.frames.append(frame)
        return frame


class Adapter:
    """jev-ra behind `start`, `step` and `run`, the surface a benchmark harness drives.

    One adapter is one attempt at one task: it owns the shots directory and the frames in it.
    """

    def __init__(self, shots, config=None, session=None, decide=None, image="jpg"):
        if image not in IMAGES:
            raise ValueError(f"image must be one of {', '.join(IMAGES)}")
        self.config = config or load()
        self.recorder = Recorder(session or Session(self.config), shots, image)
        self.agent = Agent(session=self.recorder, config=self.config, decide=decide)
        self.opened = False

    def start(self, url):
        """Open the task's starting page and observe it."""
        page = self.agent.open(url)
        self.opened = True
        return {**self.view(page), "status": "opened", "reason": ""}

    def step(self, instruction):
        """One decided action towards an instruction, and what the page became."""
        result = self.agent.act(instruction)
        return {
            "url": result.url,
            "title": result.title,
            "text": result.final_page.get("text", ""),
            "elements": result.final_page.get("elements", []),
            "screenshot_path": self.latest(),
            "status": result.status,
            "reason": result.reason,
        }

    def run(self, task_text, max_steps=MAX_STEPS, url=None):
        """Pursue the whole task and hand back the trajectory a judge is shown."""
        if url is not None:
            self.opened = True
        result = self.agent.run(task_text, max_steps=max_steps, url=url)
        text = (result.final_page.get("text") or "").strip()
        return {
            "final_url": result.url,
            "final_answer": result.final_answer,
            "final_page_text": text[:ANSWER_CHARS] or None,
            "trajectory": self.trajectory(result),
            "status": result.status,
            "reason": result.reason,
            "run_id": result.run_id,
            "steps": len(result.steps),
            "decisions": result.decisions,
            "text_calls": len(result.text_calls),
            "cost": result.cost,
            "elapsed_ms": result.elapsed_ms,
            "detail": result.detail,
        }

    def trajectory(self, result):
        """One entry per frame: the navigation that opened the task, then every step it took."""
        entries = []
        frames = self.recorder.frames
        if self.opened and frames:
            entries.append(
                {
                    "step": 0,
                    "url": frames[0]["url"],
                    "action": NAVIGATE,
                    "screenshot_path": str(frames[0]["path"]),
                    "operation": NAVIGATE,
                    "target": "page",
                    "label": "",
                    "text": None,
                    "landed": True,
                }
            )
        for index, step in enumerate(result.steps, start=len(entries)):
            if index >= len(frames):
                # An action landed but its page never settled, so the run ended without a frame
                # for it. Dropping the tail keeps step and screenshot aligned, which is the one
                # thing a submission may not get wrong.
                logger.warning("No frame for step %s of %s; dropping it from the trajectory", index, result.run_id)
                break
            frame = frames[index]
            label = step.get("target_label") or ""
            entries.append(
                {
                    "step": index,
                    "url": frame["url"] or step.get("url", ""),
                    "action": f"{step['operation']} {step['target']} {label}".strip(),
                    "screenshot_path": str(frame["path"]),
                    "operation": step["operation"],
                    "target": step["target"],
                    "label": label,
                    "text": step.get("text"),
                    "landed": landed(step),
                }
            )
        return entries

    def view(self, page):
        """The observation a harness reads between steps."""
        space = self.agent.space(page)
        return {
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "text": page.get("text", ""),
            "elements": [element_view(element) for element in space.elements],
            "screenshot_path": self.latest(),
        }

    def latest(self):
        """The frame taken most recently, or an empty string before the first one."""
        frames = self.recorder.frames
        return str(frames[-1]["path"]) if frames else ""

    def close(self):
        """Close the session and the decision client this attempt owns."""
        self.agent.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def evidence(result):
    """The first words of the page a run ended on, which is what a `blocked` has to be read against."""
    detail = result.get("detail") or {}
    text = detail.get("error") or detail.get("page_text") or result.get("final_page_text") or ""
    return " ".join(text.split())[:200]


def landed(step):
    """Whether the page showed that an action took effect, by the checks jev-ra already makes."""
    return bool(step.get("page_changed") or any((step.get("verified") or {}).values()))
