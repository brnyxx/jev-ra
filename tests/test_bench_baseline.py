"""The browser-use baseline re-run: it copies the recorded script and shells out to uv."""

import pytest

from jev_ra import bench


def recorded(tmp_path):
    directory = tmp_path / "docs" / "benchmarks" / "2026-09-18-browser-use-baseline"
    directory.mkdir(parents=True)
    (directory / "bench.py").write_text("print('baseline')\n")
    return directory


def finished(returncode=0):
    return type("Finished", (), {"returncode": returncode, "stdout": "ok", "stderr": ""})()


def test_uv_missing_says_which_environment_needs_it(monkeypatch):
    monkeypatch.setattr(bench.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="uv is not on PATH"):
        bench.uv_command()


def test_a_root_without_a_checkout_has_no_baseline(tmp_path):
    assert bench.repo_root(tmp_path) is None
    assert bench.baseline_dir(tmp_path) is None


def test_a_missing_recorded_script_is_refused(tmp_path):
    with pytest.raises(RuntimeError, match="No browser-use bench script"):
        bench.run_baseline(directory=tmp_path, out_dir=tmp_path / "out")


def test_the_baseline_rerun_copies_the_script_before_running_it(monkeypatch, tmp_path):
    calls = []

    def run(argv, capture_output, text):
        calls.append(argv)
        return finished()

    monkeypatch.setattr(bench, "uv_command", lambda: "/usr/local/bin/uv")
    monkeypatch.setattr(bench.subprocess, "run", run)
    completed = bench.run_baseline(runs=2, directory=recorded(tmp_path), out_dir=tmp_path / "out")
    copy = tmp_path / "out" / "bench.py"
    assert copy.read_text() == "print('baseline')\n"
    assert len(completed) == 2 and completed[0]["returncode"] == 0
    assert calls[0] == [
        "/usr/local/bin/uv",
        "run",
        "--no-project",
        "--with",
        bench.BROWSER_USE_PIN,
        "python",
        str(copy),
        bench.FLASH_MODEL,
        "flash",
    ]


def test_a_failed_baseline_run_stops_the_repeats(monkeypatch, tmp_path):
    codes = iter([1, 0])

    def run(_argv, capture_output, text):
        return finished(next(codes))

    monkeypatch.setattr(bench, "uv_command", lambda: "uv")
    monkeypatch.setattr(bench.subprocess, "run", run)
    completed = bench.run_baseline(runs=3, directory=recorded(tmp_path), out_dir=tmp_path / "out")
    assert len(completed) == 1 and completed[0]["returncode"] == 1


def test_the_default_variant_is_asked_for_by_its_recorded_name(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(bench, "uv_command", lambda: "uv")
    monkeypatch.setattr(bench.subprocess, "run", lambda argv, **_kwargs: (seen.append(argv), finished())[1])
    bench.run_baseline(runs=1, flash=False, directory=recorded(tmp_path), out_dir=tmp_path / "out")
    assert seen[0][-1] == "default"
