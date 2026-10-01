"""Tests for `caasi monitor` (Layer 7) and the core/monitor sampler."""

from __future__ import annotations

import json
import threading
import time

from caasi import state
from caasi.cli.main import app
from caasi.core import monitor, runs

from .conftest import all_output


def _finished_run(tmp_path, name: str, script: str) -> runs.RunRecord:
    """Start a run and wait until the wrapper recorded its exit code."""
    record = runs.start_run(
        state.cfg(), name=name, command=["bash", "-c", script], cwd=tmp_path
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        if runs.effective_status(record) in (runs.TERMINAL_OK, runs.TERMINAL_FAIL):
            break
        time.sleep(0.05)
    return record


# -- core sampler ----------------------------------------------------------


def test_sample_machine_only(no_nvidia_smi):
    snap = monitor.sample(None, state.cfg())
    assert snap.gpu is None
    assert snap.vram_used is None
    assert snap.vram_total is None
    assert snap.runtime_s is None
    assert snap.steps_per_s is None
    assert snap.cpu is None or 0.0 <= snap.cpu <= 100.0
    assert snap.ram_total is not None and snap.ram_total > 0
    assert snap.ram_used is not None and snap.ram_used <= snap.ram_total
    assert isinstance(snap.processes, list)


def test_sample_gpu_fields(fake_nvidia_smi):
    snap = monitor.sample(None, state.cfg())
    assert snap.gpu == 42.0
    assert snap.vram_used == 4.0
    assert snap.vram_total == 24.0


def test_steps_per_s_explicit_metric(tmp_path):
    record = _finished_run(tmp_path, "steps", "echo 'caasi_metric steps_per_sec=1234.5'")
    assert monitor.steps_per_s(record) == 1234.5
    assert monitor.sample(record, state.cfg()).to_dict()["steps_per_s"] == 1234.5


def test_steps_per_s_label_alias(tmp_path):
    record = _finished_run(tmp_path, "fps", "echo 'Simulation FPS: 241'")
    assert monitor.steps_per_s(record) == 241.0


def test_steps_per_s_absent(tmp_path):
    record = _finished_run(tmp_path, "quiet", "echo 'training warmup'")
    assert monitor.steps_per_s(record) is None
    assert "steps_per_s" not in monitor.sample(record, state.cfg()).to_dict()


def test_runtime_seconds(tmp_path):
    record = _finished_run(tmp_path, "quick", "echo done")
    value = monitor.runtime_seconds(record)
    assert value is not None
    assert 0.0 <= value < 60.0
    assert monitor.runtime_seconds(None) is None


# -- CLI snapshot ----------------------------------------------------------


def test_monitor_once_json_without_runs(runner, no_nvidia_smi):
    result = runner.invoke(app, ["monitor", "--once", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["run"] is None
    assert data["status"] is None
    for key in ("cpu", "ram_used", "gpu", "runtime_s"):
        assert key in data
    assert data["gpu"] is None
    assert "steps_per_s" not in data


def test_monitor_defaults_to_latest_run(runner, tmp_path):
    runs.start_run(state.cfg(), name="first", command=["bash", "-c", "echo one"], cwd=tmp_path)
    second = runs.start_run(
        state.cfg(), name="second", command=["bash", "-c", "echo two"], cwd=tmp_path
    )
    result = runner.invoke(app, ["monitor", "--once", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["run"] == second.run_id
    assert data["name"] == "second"
    assert data["backend"] == "python"


def test_monitor_explicit_query(runner, tmp_path):
    record = _finished_run(tmp_path, "target", "echo hi")
    result = runner.invoke(app, ["monitor", record.run_id, "--once", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["run"] == record.run_id
    assert data["status"] == runs.TERMINAL_OK
    assert data["runtime_s"] is not None


def test_monitor_query_not_found(runner, no_nvidia_smi):
    result = runner.invoke(app, ["monitor", "nope", "--once"])
    assert result.exit_code == 1
    assert "No run matching 'nope'" in all_output(result)


def test_monitor_once_text(runner, tmp_path, fake_nvidia_smi):
    _finished_run(tmp_path, "train-demo", "echo 'caasi_metric steps_per_sec=1234.5'")
    result = runner.invoke(app, ["monitor", "--once"])
    out = all_output(result)
    assert result.exit_code == 0
    assert "train-demo" in out
    assert "CPU" in out
    assert "RAM" in out
    assert "Runtime" in out
    assert "1234.5 steps/s" in out
    assert "42.0%" in out
    assert "4.0 / 24.0 GiB" in out
    assert "Top processes by memory" in out


def test_monitor_once_without_runs_shows_note(runner, no_nvidia_smi):
    result = runner.invoke(app, ["monitor", "--once"])
    out = all_output(result)
    assert result.exit_code == 0
    assert "No runs recorded" in out
    assert "CPU" in out


def test_monitor_in_root_help(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "monitor" in all_output(result)


# -- CLI live mode ----------------------------------------------------------


def test_monitor_live_exits_when_run_finishes(runner, tmp_path):
    _finished_run(tmp_path, "quick", "echo done")
    result = runner.invoke(app, ["monitor", "--interval", "0.2"])
    assert result.exit_code == 0


def test_monitor_live_keyboard_interrupt(runner, tmp_path, monkeypatch):
    record = runs.start_run(
        state.cfg(), name="sleeper", command=["bash", "-c", "sleep 5"], cwd=tmp_path
    )
    real_sleep = time.sleep
    main_thread = threading.get_ident()
    fired: list[float] = []

    def fake_sleep(seconds):
        # Only the first main-thread sleep raises; rich's refresh thread and
        # the cleanup stop_run below must still sleep normally.
        if threading.get_ident() == main_thread and not fired:
            fired.append(seconds)
            raise KeyboardInterrupt
        real_sleep(seconds)

    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)
    try:
        result = runner.invoke(app, ["monitor", "--interval", "0.2"])
    finally:
        runs.stop_run(runs.load_run(state.cfg(), record.run_id) or record)
    assert result.exit_code == 0
    assert "Monitor stopped" in all_output(result)
