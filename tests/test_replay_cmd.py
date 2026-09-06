"""Tests for the `caasi replay` command (viewer orchestration)."""

from __future__ import annotations

import json
import os
import sys
import time

import yaml

from caasi.cli.main import app
from caasi.core import runs
from caasi.core import viewers as viewers_core

from .conftest import all_output


def configure_runs(tmp_path, monkeypatch):
    cfg = tmp_path / "caasi-test.yaml"
    cfg.write_text(
        yaml.safe_dump({"paths": {"runs": str(tmp_path / "runs")}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg))


def make_record(tmp_path, script_body="print('done')\n"):
    from caasi import state

    script = tmp_path / "rec.py"
    script.write_text(script_body, encoding="utf-8")
    return runs.start_run(state.cfg(), name="rec", command=["python3", str(script)])


def add_artifacts(record, files=("recordings/traj.txt",)):
    for rel in files:
        target = record.directory / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("data", encoding="utf-8")


def fake_viewer(tmp_path, monkeypatch, name="rviz2"):
    bin_dir = tmp_path / "viewerbin"
    bin_dir.mkdir(exist_ok=True)
    marker = tmp_path / "viewer.log"
    script = bin_dir / name
    script.write_text(f'#!/usr/bin/env bash\necho "$@" > "{marker}"\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return marker


def wait_marker(marker, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if marker.is_file():
            return marker.read_text(encoding="utf-8")
        time.sleep(0.05)
    raise AssertionError("viewer was not launched")


def test_replay_unknown_run(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(app, ["replay", "nope"])
    assert result.exit_code == 1
    assert "No run matching" in all_output(result)


def test_replay_no_data(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    result = runner.invoke(app, ["replay", record.run_id])
    assert result.exit_code == 1
    assert "no recorded data" in all_output(result)


def test_replay_dry_run(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    result = runner.invoke(app, ["replay", record.run_id, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert "rviz2" in result.output
    assert "recordings/traj.txt" in result.output


def test_replay_launch(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    marker = fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    result = runner.invoke(app, ["replay", record.run_id, "--speed", "2"])
    assert result.exit_code == 0, result.output
    assert "launched" in result.output
    wait_marker(marker)


def test_replay_json(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    fake_viewer(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    result = runner.invoke(app, ["replay", record.run_id, "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["id"] == record.run_id
    assert data["viewer"] == "rviz"
    assert data["artifacts"] == ["recordings/traj.txt"]


def test_replay_no_viewer(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    monkeypatch.setattr(viewers_core.shell, "which", lambda name: None)
    result = runner.invoke(app, ["replay", record.run_id])
    assert result.exit_code == 1
    assert "No viewer found" in all_output(result)


def test_replay_bad_viewer(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)
    result = runner.invoke(app, ["replay", record.run_id, "--viewer", "blender"])
    assert result.exit_code == 1
    assert "Unknown viewer" in all_output(result)


def test_replay_open3d_without_3d_data(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record)  # only a text file
    monkeypatch.setattr(viewers_core.pydist, "pip_version", lambda *c: "0.18")
    result = runner.invoke(app, ["replay", record.run_id, "--viewer", "open3d"])
    assert result.exit_code == 1
    assert "No 3D data" in all_output(result)


def test_replay_open3d_with_3d_data(runner, tmp_path, monkeypatch):
    configure_runs(tmp_path, monkeypatch)
    record = make_record(tmp_path)
    add_artifacts(record, files=("recordings/scan.ply",))
    monkeypatch.setattr(viewers_core.pydist, "pip_version", lambda *c: "0.18")
    result = runner.invoke(
        app, ["replay", record.run_id, "--viewer", "open3d", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert sys.executable in result.output
    assert "scan.ply" in result.output
