"""Tests for `caasi train`."""

from __future__ import annotations

import time

from caasi import state
from caasi.cli.main import app
from caasi.core import runs

from .conftest import all_output

FINISHED = (runs.TERMINAL_OK, runs.TERMINAL_FAIL)

SCRIPT = "import sys\nprint('training', sys.argv[1:])\n"


def _experiment(tmp_path, backend: str = "python"):
    (tmp_path / "train.py").write_text(SCRIPT, encoding="utf-8")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        f"name: policy\nbackend: {backend}\nscript: train.py\n", encoding="utf-8"
    )
    return config


def _wait_finished(record, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in FINISHED:
            return
        time.sleep(0.05)


def test_train_dry_run(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(
        app,
        ["train", str(config), "--steps", "1000", "--envs", "4", "--seed", "42",
         "--device", "cuda:0", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    for token in ("--steps", "1000", "--envs", "4", "--seed", "42", "--device", "cuda:0", "--headless"):
        assert token in result.output
    assert runs.list_runs(state.cfg()) == []


def test_train_starts_run(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["train", str(config), "--steps", "10", "--envs", "2"])
    assert result.exit_code == 0
    assert "started in the background" in result.output

    record = runs.find_run(state.cfg(), "latest")
    assert record is not None
    assert record.kind == "train"
    _wait_finished(record)
    assert runs.effective_status(record) == runs.TERMINAL_OK
    stdout = (record.directory / "stdout.log").read_text()
    assert "--steps" in stdout and "10" in stdout
    assert "--envs" in stdout
    assert "--headless" in stdout


def test_train_missing_backend_tool(runner, tmp_path):
    config = _experiment(tmp_path, backend="lab")
    result = runner.invoke(app, ["train", str(config)])
    assert result.exit_code == 1
    assert "isaaclab" in all_output(result)


def test_train_missing_config(runner):
    result = runner.invoke(app, ["train", "nope.yaml"])
    assert result.exit_code == 1
    assert "not found" in all_output(result)
