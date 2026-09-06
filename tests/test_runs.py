"""Tests for the detached run manager."""

from __future__ import annotations

import time

import pytest

from caasi import state
from caasi.core import runs


def _wait_status(record, wanted: tuple[str, ...], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in wanted:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def cfg():
    return state.cfg()


def test_new_run_id_slug():
    run_id = runs.new_run_id("My Experiment!")
    assert run_id.endswith("-my-experiment")
    assert run_id[:8].isdigit()


def test_start_run_succeeds(cfg):
    record = runs.start_run(
        cfg, name="hello", command=["bash", "-c", "echo caasi-run"], backend="python", kind="test"
    )
    assert record.pid
    assert record.directory and record.directory.is_dir()
    assert (record.directory / "manifest.yaml").is_file()
    assert (record.directory / "run.sh").is_file()
    assert _wait_status(record, (runs.TERMINAL_OK,))
    assert "caasi-run" in (record.directory / "stdout.log").read_text()


def test_failed_run_records_exit_code(cfg):
    record = runs.start_run(
        cfg, name="boom", command=["bash", "-c", "echo oops >&2; exit 3"], kind="test"
    )
    assert _wait_status(record, (runs.TERMINAL_FAIL,))
    assert runs.effective_status(record) == runs.TERMINAL_FAIL
    assert "oops" in (record.directory / "stderr.log").read_text()


def test_list_find_latest(cfg):
    first = runs.start_run(cfg, name="aaa", command=["bash", "-c", "echo 1"], kind="test")
    assert _wait_status(first, (runs.TERMINAL_OK, runs.TERMINAL_FAIL))
    time.sleep(1.1)  # guarantee a newer timestamp-prefixed run id
    second = runs.start_run(cfg, name="bbb", command=["bash", "-c", "echo 2"], kind="test")

    listed = runs.list_runs(cfg)
    assert [r.run_id for r in listed][:2] == [second.run_id, first.run_id]

    assert runs.find_run(cfg, "latest").run_id == second.run_id
    assert runs.find_run(cfg, second.run_id).run_id == second.run_id
    assert runs.find_run(cfg, second.run_id[:15]).run_id == second.run_id
    assert runs.find_run(cfg, "aaa").run_id == first.run_id
    assert runs.find_run(cfg, "nothing") is None

    assert _wait_status(second, (runs.TERMINAL_OK, runs.TERMINAL_FAIL))


def test_load_run_missing(cfg):
    assert runs.load_run(cfg, "does-not-exist") is None


def test_status_running_then_stopped(cfg):
    record = runs.start_run(cfg, name="sleeper", command=["sleep", "30"], kind="test")
    assert runs.effective_status(record) == runs.RUNNING
    assert runs.stop_run(record)
    assert runs.effective_status(record) in (runs.STOPPED, runs.TERMINAL_FAIL)
    reloaded = runs.load_run(cfg, record.run_id)
    assert reloaded.stopped is True


def test_pause_and_resume(cfg):
    record = runs.start_run(cfg, name="pauser", command=["sleep", "30"], kind="test")
    assert runs.effective_status(record) == runs.RUNNING
    assert runs.pause_run(record)
    assert runs.effective_status(record) == runs.PAUSED
    # a paused run cannot be paused again
    assert not runs.pause_run(runs.load_run(cfg, record.run_id))
    assert runs.resume_run(runs.load_run(cfg, record.run_id))
    record = runs.load_run(cfg, record.run_id)
    assert runs.effective_status(record) == runs.RUNNING
    runs.stop_run(runs.load_run(cfg, record.run_id))


def test_delete_refuses_running_then_works(cfg):
    record = runs.start_run(cfg, name="deleter", command=["sleep", "30"], kind="test")
    assert not runs.delete_run(record)
    runs.stop_run(runs.load_run(cfg, record.run_id))
    record = runs.load_run(cfg, record.run_id)
    run_dir = record.directory
    assert runs.delete_run(record)
    assert not run_dir.exists()
    assert runs.load_run(cfg, record.run_id) is None


def test_log_path(cfg):
    record = runs.start_run(cfg, name="logger", command=["bash", "-c", "echo x"], kind="test")
    assert _wait_status(record, (runs.TERMINAL_OK, runs.TERMINAL_FAIL))
    assert runs.log_path(record, "stdout").name == "stdout.log"
    assert runs.log_path(record, "stderr").name == "stderr.log"
    assert runs.log_path(record, "nope") is None
