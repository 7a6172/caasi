"""Tests for the `caasi view` commands (viewer orchestration)."""

from __future__ import annotations

import json
import sys
import time

from caasi.cli.main import app
from caasi.core import runs
from caasi.core import viewers as viewers_core

from .conftest import all_output
from .test_replay_cmd import add_artifacts, configure_runs, fake_viewer, make_record, wait_marker


def make_sleeper(tmp_path):
    from caasi import state

    script = tmp_path / "sleeper.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    return runs.start_run(state.cfg(), name="sleeper", command=["python3", str(script)])


def test_view_rviz_dry_run(runner, tmp_path, monkeypatch):
    fake_viewer(tmp_path, monkeypatch)
    result = runner.invoke(app, ["view", "rviz", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "rviz2" in result.output


def test_view_rviz_launch_with_config(runner, tmp_path, monkeypatch):
    marker = fake_viewer(tmp_path, monkeypatch)
    config = tmp_path / "layout.rviz"
    config.write_text("panels: []", encoding="utf-8")
    result = runner.invoke(app, ["view", "rviz", str(config)])
    assert result.exit_code == 0, result.output
    assert "launched" in result.output
    assert wait_marker(marker).strip() == f"-d {config}"


def test_view_rviz_missing(runner, monkeypatch):
    monkeypatch.setattr(viewers_core.shell, "which", lambda name: None)
    result = runner.invoke(app, ["view", "rviz"])
    assert result.exit_code == 1
    assert "Viewer 'rviz' not found" in all_output(result)
    assert "caasi setup ros2" in all_output(result)


def test_view_foxglove_dry_run(runner, tmp_path, monkeypatch):
    fake_viewer(tmp_path, monkeypatch, name="foxglove")
    result = runner.invoke(app, ["view", "foxglove", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "foxglove" in result.output


def test_view_foxglove_missing(runner, monkeypatch):
    monkeypatch.setattr(viewers_core.shell, "which", lambda name: None)
    result = runner.invoke(app, ["view", "foxglove"])
    assert result.exit_code == 1
    assert "foxglove.dev" in all_output(result)


def test_view_open3d_missing(runner, monkeypatch):
    monkeypatch.setattr(viewers_core.pydist, "pip_version", lambda *c: None)
    result = runner.invoke(app, ["view", "open3d", "scan.ply"])
    assert result.exit_code == 1
    assert "pip install open3d" in all_output(result)


def test_view_open3d_dry_run(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(viewers_core.pydist, "pip_version", lambda *c: "0.18")
    target = tmp_path / "scan.ply"
    target.write_text("ply", encoding="utf-8")
    result = runner.invoke(app, ["view", "open3d", str(target), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert sys.executable in result.output
    assert str(target) in result.output


def test_view_open3d_missing_target(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(viewers_core.pydist, "pip_version", lambda *c: "0.18")
    result = runner.invoke(app, ["view", "open3d", str(tmp_path / "nope.ply")])
    assert result.exit_code == 1
    assert "No such file" in all_output(result)


def test_view_attach(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    marker = fake_viewer(tmp_path, monkeypatch)
    record = make_sleeper(tmp_path)
    try:
        result = runner.invoke(app, ["view", "attach", record.run_id, "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "rviz2" in result.output

        result = runner.invoke(app, ["view", "attach", record.run_id])
        assert result.exit_code == 0, result.output
        assert "launched" in result.output
        wait_marker(marker)
    finally:
        runs.stop_run(record)


def test_view_attach_bad_viewer(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_sleeper(tmp_path)
    try:
        result = runner.invoke(
            app, ["view", "attach", record.run_id, "--viewer", "blender"]
        )
        assert result.exit_code == 1
        assert "Unknown viewer" in all_output(result)
    finally:
        runs.stop_run(record)


def test_view_attach_not_active(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    fake_viewer(tmp_path, monkeypatch)
    script = tmp_path / "quick.py"
    script.write_text("print('done')\n", encoding="utf-8")
    from caasi import state

    record = runs.start_run(state.cfg(), name="quick", command=["python3", str(script)])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and runs.effective_status(record) == runs.RUNNING:
        time.sleep(0.05)
    result = runner.invoke(app, ["view", "attach", record.run_id])
    assert result.exit_code == 1
    assert "is not running" in all_output(result)


def test_view_attach_unknown_run(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(app, ["view", "attach", "nope"])
    assert result.exit_code == 1
    assert "No run matching" in all_output(result)


def test_view_run_dry_run(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    result = runner.invoke(app, ["view", "run", record.run_id, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "rviz2" in result.output
    assert "recordings/traj.txt" in result.output


def test_view_run_launch(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    marker = fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record, files=("recordings/scan.ply",))
    result = runner.invoke(app, ["view", "run", record.run_id])
    assert result.exit_code == 0, result.output
    assert "launched" in result.output
    wait_marker(marker)


def test_view_run_json(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    result = runner.invoke(app, ["view", "run", record.run_id, "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["id"] == record.run_id
    assert data["viewer"] == "rviz"
    assert data["artifacts"] == ["recordings/traj.txt"]
    assert "pid" not in data


def test_view_run_no_data(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    result = runner.invoke(app, ["view", "run", record.run_id])
    assert result.exit_code == 1
    assert "no recorded data" in all_output(result)


def test_view_run_bad_viewer(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    result = runner.invoke(app, ["view", "run", record.run_id, "--viewer", "blender"])
    assert result.exit_code == 1
    assert "Unknown viewer" in all_output(result)


def test_view_run_open3d_needs_3d_data(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)  # text file only
    monkeypatch.setattr(viewers_core.pydist, "pip_version", lambda *c: "0.18")
    result = runner.invoke(app, ["view", "run", record.run_id, "--viewer", "open3d"])
    assert result.exit_code == 1
    assert "No 3D data" in all_output(result)


def test_view_run_open3d_with_3d_data(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record, files=("recordings/scan.ply",))
    monkeypatch.setattr(viewers_core.pydist, "pip_version", lambda *c: "0.18")
    result = runner.invoke(app, ["view", "run", record.run_id, "--viewer", "open3d", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert sys.executable in result.output
    assert "scan.ply" in result.output
