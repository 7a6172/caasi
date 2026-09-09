"""Tests for the `caasi lab` commands."""

from __future__ import annotations

import json
import time

from caasi import state
from caasi.cli.main import app
from caasi.core import runs

from .conftest import all_output

FINISHED = (runs.TERMINAL_OK, runs.TERMINAL_FAIL)


def test_lab_status_not_detected(runner):
    result = runner.invoke(app, ["lab", "status"])
    assert result.exit_code == 0
    assert "not detected" in result.output


def test_lab_status_json(runner):
    result = runner.invoke(app, ["lab", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "fail"
    assert data["path"] is None
    assert data["launcher"] is None


def test_lab_status_configured_tool(runner, tmp_path, monkeypatch):
    labdir = tmp_path / "lab"
    labdir.mkdir()
    (labdir / "isaaclab.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    config = tmp_path / "caasi-test.yaml"
    config.write_text(
        "tools:\n"
        "  isaaclab:\n"
        '    default: "2.0"\n'
        "    versions:\n"
        '      "2.0":\n'
        f"        path: {labdir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(config))

    result = runner.invoke(app, ["lab", "status"])
    assert result.exit_code == 0
    assert "Isaac Lab 2.0" in result.output
    assert "Launcher:" in result.output
    assert "isaaclab.sh" in result.output

    result = runner.invoke(app, ["lab", "status", "--json"])
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["launcher"] == str(labdir / "isaaclab.sh")


def _make_experiment(tmp_path, backend: str = "python", name: str = "lab-demo", extra_keys: str = ""):
    (tmp_path / "main.py").write_text("print('lab-work')\n", encoding="utf-8")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        f"name: {name}\nbackend: {backend}\nscript: main.py\nargs: ['--flag']\n{extra_keys}",
        encoding="utf-8",
    )
    return config


def _make_lab_tool(tmp_path, monkeypatch, executable: bool = False):
    labdir = tmp_path / "lab"
    labdir.mkdir()
    launcher = labdir / "isaaclab.sh"
    if executable:
        launcher.write_text('#!/usr/bin/env bash\necho "launcher $*"\n', encoding="utf-8")
        launcher.chmod(0o755)
    else:
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    config = tmp_path / "caasi-lab.yaml"
    config.write_text(
        "tools:\n"
        "  isaaclab:\n"
        '    default: "2.0"\n'
        "    versions:\n"
        '      "2.0":\n'
        f"        path: {labdir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(config))
    return labdir


def _wait_finished(record, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in FINISHED:
            return
        time.sleep(0.05)


def test_lab_run_dry_run_backend_note(runner, tmp_path):
    config = _make_experiment(tmp_path)
    result = runner.invoke(app, ["lab", "run", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "backend is 'python'" in result.output
    assert "Dry run" in result.output
    assert "--flag" in result.output
    assert runs.list_runs(state.cfg()) == []


def test_lab_run_json_is_pure(runner, tmp_path):
    config = _make_experiment(tmp_path)
    result = runner.invoke(app, ["lab", "run", str(config), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["backend"] == "python"
    assert data["kind"] == "experiment"
    record = runs.find_run(state.cfg(), "lab-demo")
    _wait_finished(record)
    assert runs.effective_status(record) == runs.TERMINAL_OK
    assert "lab-work" in (record.directory / "stdout.log").read_text()


def test_lab_run_missing_config(runner):
    result = runner.invoke(app, ["lab", "run", "nope.yaml"])
    assert result.exit_code == 1
    assert "not found" in all_output(result)


def test_lab_run_missing_lab_tool(runner, tmp_path):
    config = _make_experiment(tmp_path, backend="lab")
    result = runner.invoke(app, ["lab", "run", str(config)])
    assert result.exit_code == 1
    assert "isaaclab" in all_output(result)


def test_lab_train_passes_training_args(runner, tmp_path):
    config = _make_experiment(tmp_path)
    result = runner.invoke(
        app, ["lab", "train", str(config), "--steps", "10", "--envs", "2", "--dry-run"]
    )
    assert result.exit_code == 0
    flat = " ".join(result.output.split())
    assert "--steps 10" in flat
    assert "--envs 2" in flat
    assert "--headless" in flat
    assert runs.list_runs(state.cfg()) == []


def test_lab_play_dry_run_uses_play_script_and_checkpoint(runner, tmp_path, monkeypatch):
    _make_lab_tool(tmp_path, monkeypatch)
    config = _make_experiment(tmp_path, backend="lab", extra_keys="play_script: play.py\n")
    (tmp_path / "play.py").write_text("", encoding="utf-8")
    result = runner.invoke(
        app, ["lab", "play", str(config), "--checkpoint", "ckpt.pt", "--dry-run"]
    )
    assert result.exit_code == 0
    flat = " ".join(result.output.split())
    assert "isaaclab.sh -p" in flat
    assert "play.py" in flat
    assert "--checkpoint ckpt.pt" in flat


def test_lab_play_falls_back_to_script(runner, tmp_path, monkeypatch):
    _make_lab_tool(tmp_path, monkeypatch)
    config = _make_experiment(tmp_path, backend="lab")
    result = runner.invoke(app, ["lab", "play", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "main.py" in result.output


def test_lab_evaluate_prefers_evaluate_script(runner, tmp_path, monkeypatch):
    _make_lab_tool(tmp_path, monkeypatch)
    config = _make_experiment(
        tmp_path,
        backend="lab",
        extra_keys="play_script: play.py\nevaluate_script: eval.py\n",
    )
    result = runner.invoke(app, ["lab", "evaluate", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "eval.py" in result.output
    assert "play.py" not in result.output


def test_lab_play_starts_tracked_run(runner, tmp_path, monkeypatch):
    _make_lab_tool(tmp_path, monkeypatch, executable=True)
    config = _make_experiment(
        tmp_path, backend="lab", name="play-demo", extra_keys="play_script: play.py\n"
    )
    (tmp_path / "play.py").write_text("", encoding="utf-8")
    result = runner.invoke(
        app, ["lab", "play", str(config), "--checkpoint", "ckpt.pt", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["backend"] == "lab"
    assert data["kind"] == "play"
    record = runs.find_run(state.cfg(), "play-demo")
    _wait_finished(record)
    assert runs.effective_status(record) == runs.TERMINAL_OK
    stdout = (record.directory / "stdout.log").read_text()
    assert "launcher -p" in stdout
    assert "--checkpoint ckpt.pt" in stdout
