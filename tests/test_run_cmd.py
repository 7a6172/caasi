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
    for sub in (
        "start", "restart", "list", "status", "logs", "attach",
        "stop", "pause", "resume", "delete", "inspect",
    ):
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


def test_run_list_backend_filter(runner):
    sim_record = _start("sim-one", ["sleep", "30"], backend="sim")
    py_record = _start("py-one", ["sleep", "30"], backend="python")
    try:
        result = runner.invoke(app, ["run", "list", "--backend", "sim"])
        assert result.exit_code == 0
        assert "sim-one" in result.output
        assert "py-one" not in result.output

        result = runner.invoke(app, ["run", "list", "--backend", "sim", "--json"])
        assert result.exit_code == 0
        assert [r["id"] for r in json.loads(result.output)] == [sim_record.run_id]
    finally:
        runs.stop_run(sim_record)
        runs.stop_run(py_record)


def test_run_backend_guard_rejects_mismatch(runner):
    record = _start("py-run", ["sleep", "30"], backend="python")
    try:
        result = runner.invoke(app, ["run", "stop", "latest", "--backend", "sim"])
        assert result.exit_code == 1
        assert "not 'sim'" in all_output(result)
        assert runs.effective_status(record) == runs.RUNNING
    finally:
        runs.stop_run(record)


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


# -- run start (canonical launcher, §5.4) ----------------------------------


def _experiment(tmp_path, backend: str = "python", name: str = "demo", extra_keys: str = ""):
    (tmp_path / "main.py").write_text("print('run-start-work')\n", encoding="utf-8")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        f"name: {name}\nbackend: {backend}\nscript: main.py\n{extra_keys}",
        encoding="utf-8",
    )
    return config


def test_run_start_launches_with_provenance(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["run", "start", str(config), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["backend"] == "python"
    assert data["kind"] == "experiment"

    record = runs.find_run(state.cfg(), data["id"])
    _wait_finished(record)
    assert runs.effective_status(record) == runs.TERMINAL_OK
    assert "run-start-work" in (record.directory / "stdout.log").read_text()
    for filename in (
        "manifest.yaml", "environment.yaml", "hardware.yaml",
        "dependencies.yaml", "configuration.yaml", "git.json", "processes.json",
    ):
        assert (record.directory / filename).is_file(), filename


def test_run_start_dry_run_starts_nothing(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["run", "start", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "main.py" in result.output
    assert runs.list_runs(state.cfg()) == []


def test_run_start_backend_override(runner, tmp_path):
    config = _experiment(tmp_path, backend="lab")
    result = runner.invoke(
        app, ["run", "start", str(config), "--backend", "python", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "backend is 'lab'" in result.output
    assert "launching with 'python'" in result.output
    assert "main.py" in result.output
    assert runs.list_runs(state.cfg()) == []


def test_run_start_bad_backend(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["run", "start", str(config), "--backend", "ros"])
    assert result.exit_code == 1
    assert "Unknown backend 'ros'" in all_output(result)
    assert runs.list_runs(state.cfg()) == []


def test_run_start_missing_config(runner):
    result = runner.invoke(app, ["run", "start", "nope.yaml"])
    assert result.exit_code == 1
    assert "not found" in all_output(result)


def test_run_start_passes_extra_args(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["run", "start", str(config), "--dry-run", "--", "--custom", "x"])
    assert result.exit_code == 0
    flat = " ".join(result.output.split())
    assert "--custom x" in flat


def test_root_start_alias(runner, tmp_path):
    config = _experiment(tmp_path)
    result = runner.invoke(app, ["start", str(config), "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "main.py" in result.output


# -- run restart -----------------------------------------------------------


def test_run_restart_finished_run(runner, tmp_path):
    config = _experiment(tmp_path, name="restart-demo")
    result = runner.invoke(app, ["run", "start", str(config)])
    assert result.exit_code == 0
    old = runs.find_run(state.cfg(), "restart-demo")
    _wait_finished(old)

    result = runner.invoke(app, ["run", "restart", old.run_id])
    assert result.exit_code == 0
    assert f"Restarted run {old.run_id} as" in result.output

    new = runs.find_run(state.cfg(), "latest")
    assert new is not None and new.run_id != old.run_id
    assert new.extra["restarted_from"] == old.run_id
    assert new.command == old.command
    _wait_finished(new)
    assert runs.effective_status(new) == runs.TERMINAL_OK
    # The new run gets its own provenance bundle.
    assert (new.directory / "dependencies.yaml").is_file()


def test_run_restart_stops_active_run(runner):
    record = _start("sleeper", ["sleep", "30"])
    try:
        result = runner.invoke(app, ["run", "restart", record.run_id])
        assert result.exit_code == 0
        old = runs.load_run(state.cfg(), record.run_id)
        assert runs.effective_status(old) == runs.STOPPED
        new = runs.find_run(state.cfg(), "latest")
        assert new.run_id != record.run_id
        assert runs.effective_status(new) == runs.RUNNING
    finally:
        for candidate in runs.list_runs(state.cfg()):
            runs.stop_run(candidate)


def test_run_restart_json(runner, tmp_path):
    config = _experiment(tmp_path, name="restart-json")
    runner.invoke(app, ["run", "start", str(config)])
    old = runs.find_run(state.cfg(), "restart-json")
    _wait_finished(old)
    result = runner.invoke(app, ["run", "restart", old.run_id, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] != old.run_id
    assert data["name"] == old.name


def test_run_restart_missing_cwd(runner, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    record = runs.start_run(
        state.cfg(), name="gone-cwd", command=["bash", "-c", "true"], cwd=work,
        backend="python", kind="test",
    )
    _wait_finished(record)
    import shutil

    shutil.rmtree(work)
    result = runner.invoke(app, ["run", "restart", record.run_id])
    assert result.exit_code == 1
    assert "no longer exists" in all_output(result)


def test_run_restart_unknown_run(runner):
    result = runner.invoke(app, ["run", "restart", "nope"])
    assert result.exit_code == 1
    assert "No run matching 'nope'" in all_output(result)


# -- log aggregation (§22) --------------------------------------------------


def _tagged_run(runner):
    script = (
        "echo '[10:00:01] [isaac-sim] starting up';"
        "echo '[10:00:02] [nav2] planner failed';"
        "echo '[10:00:03] [isaac-sim] all good';"
        "echo 'plain untagged line'"
    )
    record = _start("tagged", ["bash", "-c", script])
    _wait_finished(record)
    return record


def test_run_logs_component_filter(runner):
    record = _tagged_run(runner)
    result = runner.invoke(app, ["run", "logs", record.run_id, "--component", "nav2"])
    assert result.exit_code == 0
    assert "planner failed" in result.output
    assert "starting up" not in result.output
    assert "plain untagged" not in result.output

    result = runner.invoke(app, ["run", "logs", record.run_id, "--component", "NAV2"])
    assert "planner failed" in result.output


def test_run_logs_errors_filter(runner):
    record = _tagged_run(runner)
    result = runner.invoke(app, ["run", "logs", record.run_id, "--errors"])
    assert result.exit_code == 0
    assert "planner failed" in result.output
    assert "all good" not in result.output


def test_run_logs_since_filter(runner):
    from datetime import datetime, timedelta

    now = datetime.now()
    recent = now.strftime("%H:%M:%S")
    stale = (now - timedelta(hours=2)).strftime("%H:%M:%S")
    script = (
        f"echo '[{recent}] [a] fresh line';"
        f"echo '[{stale}] [a] stale line';"
        "echo 'untimestamped line'"
    )
    record = _start("windowed", ["bash", "-c", script])
    _wait_finished(record)

    result = runner.invoke(app, ["run", "logs", record.run_id, "--since", "10m"])
    assert result.exit_code == 0
    assert "fresh line" in result.output
    assert "stale line" not in result.output
    assert "untimestamped" not in result.output


def test_run_logs_since_invalid(runner):
    record = _tagged_run(runner)
    result = runner.invoke(app, ["run", "logs", record.run_id, "--since", "banana"])
    assert result.exit_code == 1
    assert "Invalid --since" in all_output(result)


def test_run_logs_json_envelope(runner):
    record = _tagged_run(runner)
    result = runner.invoke(app, ["run", "logs", record.run_id, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["run"] == record.run_id
    assert data["stream"] == "stdout"
    assert len(data["lines"]) == 4
    by_component = {line["component"]: line for line in data["lines"] if line["component"]}
    assert by_component["nav2"]["severity"] == "ERROR"
    assert by_component["isaac-sim"]["timestamp"] in ("10:00:01", "10:00:03")
    plain = [line for line in data["lines"] if line["component"] is None]
    assert plain[0]["message"] == "plain untagged line"


def test_run_logs_filters_combine(runner):
    record = _tagged_run(runner)
    result = runner.invoke(
        app, ["run", "logs", record.run_id, "--component", "isaac-sim", "--errors"]
    )
    assert result.exit_code == 0
    assert "planner failed" not in result.output
    assert "all good" not in result.output
