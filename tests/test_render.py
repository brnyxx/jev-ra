"""The side-by-side renderer works on synthetic frames, with no browser and no network."""

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def renderer():
    return load("render_side_by_side")


def recording(directory, label, count=10, step=100, colour=(20, 80, 160), status="done"):
    directory.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(count):
        image = Image.new("RGB", (320, 220), (colour[0], colour[1], min(255, colour[2] + index * 8)))
        name = f"{index:06d}.jpg"
        image.save(directory / name)
        frames.append({"ms": index * step, "file": name})
    manifest = {
        "label": label,
        "task": "synthetic",
        "elapsed_ms": (count - 1) * step,
        "status": status,
        "frames": frames,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return directory


def test_a_manifest_is_read_with_monotonic_timestamps(renderer, tmp_path):
    manifest = renderer.read_manifest(recording(tmp_path / "a", "jev-ra"))
    stamps = [frame["ms"] for frame in manifest["frames"]]
    assert stamps == sorted(stamps)
    assert len(stamps) == 10
    assert manifest["label"] == "jev-ra"


def test_out_of_order_timestamps_are_refused(renderer, tmp_path):
    directory = recording(tmp_path / "bad", "jev-ra")
    broken = json.loads((directory / "manifest.json").read_text())
    broken["frames"][3]["ms"] = -50
    (directory / "manifest.json").write_text(json.dumps(broken))
    with pytest.raises(ValueError, match="not monotonic"):
        renderer.read_manifest(directory)


def test_the_frame_shown_at_a_moment_is_the_last_one_before_it(renderer, tmp_path):
    manifest = renderer.read_manifest(recording(tmp_path / "a", "jev-ra"))
    assert renderer.frame_at(manifest, 0)["file"] == "000000.jpg"
    assert renderer.frame_at(manifest, 250)["file"] == "000002.jpg"
    assert renderer.frame_at(manifest, 99999)["file"] == "000009.jpg"


def test_ten_frames_a_side_render_into_one_gif(renderer, tmp_path):
    left = recording(tmp_path / "jev-ra", "jev-ra", count=10, step=100)
    right = recording(tmp_path / "browser-use", "browser-use", count=10, step=300, colour=(160, 60, 20))
    written = renderer.render([left, right], tmp_path / "out" / "side-by-side", fps=10)
    gif = tmp_path / "out" / "side-by-side.gif"
    assert gif in written
    assert gif.exists() and gif.stat().st_size > 0
    with Image.open(gif) as image:
        assert image.format == "GIF"
        assert image.n_frames >= 27
        assert image.size[0] == renderer.COLUMN_WIDTH * 2 + renderer.GUTTER


def test_a_single_recording_renders_on_its_own(renderer, tmp_path):
    written = renderer.render([recording(tmp_path / "only", "jev-ra")], tmp_path / "solo", fps=5)
    assert written[0].exists()
    with Image.open(written[0]) as image:
        assert image.size[0] == renderer.COLUMN_WIDTH


def test_the_clock_is_formatted_in_seconds(renderer):
    assert renderer.clock(0).strip() == "0.00s"
    assert renderer.clock(23058).strip() == "23.06s"


def test_the_recorder_writes_frames_and_a_manifest(tmp_path):
    record = load("record_bench")

    class OneFrameSession:
        def __init__(self):
            self.taken = 0

        def screenshot(self):
            self.taken += 1
            image = Image.new("RGB", (40, 30), (self.taken * 10 % 255, 0, 0))
            path = tmp_path / "scratch.jpg"
            image.save(path)
            return path.read_bytes()

    session = OneFrameSession()
    directory = tmp_path / "frames"
    with record.Recorder(session, directory, fps=50):
        deadline = 0
        while session.taken < 3 and deadline < 200:
            deadline += 1
    assert session.taken >= 1
    manifest = record.write_manifest(directory, "jev-ra", "synthetic", [{"ms": 10, "file": "000000.jpg"}], 10, "done")
    assert json.loads(manifest.read_text())["label"] == "jev-ra"
