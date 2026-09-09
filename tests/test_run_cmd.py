"""Tests for the `caasi run` and top-level `caasi logs` commands."""

from __future__ import annotations

import json
import time

from caasi import state
from caasi.cli.main import app
from caasi.core import runs

from .conftest import all_output

FINISHED = (runs.TERMINAL_OK, runs.TERMINAL_FAIL)


def _start(name: str, command: list[str], backend: str = "python"):
    record = runs.start_run(state.cfg(), name=name, command=command, backend=backend, kind="test")
    return record


def _wait_finished(record, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in FINISHED:
            return
        time.sleep(0.05)


def test_run_list_empty(runner):
    result = runner.invoke(app, ["run", "list"])
    assert result.exit_code == 0
    assert "No runs recorded yet" in result.output


def test_run_help_lists_subcommands(runner):
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    for sub in ("list", "status", "logs", "attach", "stop", "pause", "resume", "delete", "inspect"):
        assert sub in result.output


def test_run_list_and_status(runner):
    record = _start("hello", ["bash", "-c", "echo hi"])
    _wait_finished(record)

    result = runner.invoke(app, ["run", "list"])
    assert result.exit_code == 0
    assert record.run_id in result.output
    assert "succeeded" in result.output

    result = runner.invoke(app, ["run", "status", record.run_id])
    assert result.exit_code == 0
    assert record.name in result.output
    assert str(record.directory) in result.output

    result = runner.invoke(app, ["run", "status", record.run_id, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == record.run_id
    assert data["status"] == "succeeded"


def test_run_list_json(runner):
    record = _start("hello", ["bash", "-c", "true"])
    _wait_finished(record)
    result = runner.invoke(app, ["run", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert [r["id"] for r in data] == [record.run_id]


def test_run_status_not_found(runner):
    result = runner.invoke(app, ["run", "status", "nope"])
    assert result.exit_code == 1
    assert "No run matching 'nope'" in all_output(result)


def test_run_logs(runner):
    record = _start("talker", ["bash", "-c", "echo out-line; echo err-line >&2"])
    _wait_finished(record)

    result = runner.invoke(app, ["run", "logs", record.run_id])
    assert result.exit_code == 0
    assert "out-line" in result.output

    result = runner.invoke(app, ["run", "logs", record.run_id, "--stream", "stderr"])
    assert result.exit_code == 0
    assert "err-line" in result.output

    result = runner.invoke(app, ["run", "logs", record.run_id, "--stream", "bogus"])
    assert result.exit_code == 1
    assert "Unknown stream" in all_output(result)


def test_top_level_logs_alias(runner):
    record = _start("talker", ["bash", "-c", "echo alias-line"])
    _wait_finished(record)
    result = runner.invoke(app, ["logs", "latest"])
    assert result.exit_code == 0
    assert "alias-line" in result.output


def test_run_lifecycle_pause_resume_stop_delete(runner):
    _start("sleeper", ["sleep", "30"])

    result = runner.invoke(app, ["run", "pause", "latest"])
    assert result.exit_code == 0
    assert "paused" in result.output

    result = runner.invoke(app, ["run", "resume", "latest"])
    assert result.exit_code == 0
    assert "resumed" in result.output

    result = runner.invoke(app, ["run", "stop", "latest"])
    assert result.exit_code == 0
    assert "stopped" in result.output

    result = runner.invoke(app, ["run", "delete", "latest"])
    assert result.exit_code == 0
    assert "deleted" in result.output

    result = runner.invoke(app, ["run", "list"])
    assert "No runs recorded yet" in result.output


def test_run_delete_refuses_active_then_force(runner):
    record = _start("sleeper", ["sleep", "30"])

    result = runner.invoke(app, ["run", "delete", "latest"])
    assert result.exit_code == 1
    assert "still active" in all_output(result)

    result = runner.invoke(app, ["run", "delete", "latest", "--force"])
    assert result.exit_code == 0
    assert "deleted" in result.output
    assert runs.load_run(state.cfg(), record.run_id) is None


def test_run_inspect(runner):
    record = _start("inspected", ["bash", "-c", "echo data"])
    _wait_finished(record)

    result = runner.invoke(app, ["run", "inspect", record.run_id])
    assert result.exit_code == 0
    assert "manifest.yaml" in result.output
    assert "stdout.log" in result.output

    result = runner.invoke(app, ["run", "inspect", record.run_id, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    paths = {f["path"] for f in data["files"]}
    assert {"manifest.yaml", "run.sh", "stdout.log", "stderr.log"} <= paths


def test_run_attach_shows_both_streams(runner):
    record = _start("talker", ["bash", "-c", "echo out-line; echo err-line >&2"])
    _wait_finished(record)

    result = runner.invoke(app, ["run", "attach", record.run_id])
    assert result.exit_code == 0, result.output
    assert "Attached to run" in result.output
    assert "[stdout] out-line" in result.output
    assert "[stderr] err-line" in result.output


def test_run_attach_follows_a_live_run(runner):
    record = _start("slow", ["bash", "-c", "echo first; sleep 0.6; echo second"])
    result = runner.invoke(app, ["run", "attach", record.run_id])
    assert result.exit_code == 0, result.output
    assert "[stdout] first" in result.output
    assert "[stdout] second" in result.output


def test_run_attach_detaches_on_ctrl_c(runner, monkeypatch):
    record = _start("sleeper", ["sleep", "30"])
    original_sleep = time.sleep
    try:
        def interrupt(_seconds):
            raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", interrupt)
        result = runner.invoke(app, ["run", "attach", record.run_id])
        assert result.exit_code == 0, result.output
        assert "Detached from run" in result.output
        assert runs.effective_status(record) == runs.RUNNING
    finally:
        monkeypatch.setattr(time, "sleep", original_sleep)
        runs.stop_run(record)


def test_run_attach_without_logs(runner):
    record = _start("talker", ["bash", "-c", "echo hi"])
    _wait_finished(record)
    (record.directory / "stdout.log").unlink()
    (record.directory / "stderr.log").unlink()

    result = runner.invoke(app, ["run", "attach", record.run_id])
    assert result.exit_code == 1
    assert "No log files" in all_output(result)


def test_run_attach_unknown_run(runner):
    result = runner.invoke(app, ["run", "attach", "nope"])
    assert result.exit_code == 1
    assert "No run matching 'nope'" in all_output(result)
