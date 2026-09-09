"""Tests for `caasi motion` — planner servers, action goals and benchmark scripts."""

from __future__ import annotations

import json
import sys

import yaml

from caasi.cli.main import app

from .conftest import all_output
from .test_ros_cmd import configure_runs, no_ros2, wait_for_run


def test_motion_status_reports_gpu(runner, fake_ros_world, fake_nvidia_smi):
    fake_ros_world.packages("isaac_ros_cumotion")
    result = runner.invoke(app, ["motion", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "motion"
    assert data["total"] == 7
    assert data["installed"] == 1
    assert data["gpu"] == "FakeGPU RTX 9090"
    states = {item["key"]: item for item in data["capabilities"]}
    assert states["cumotion"]["found"] is True
    assert states["curobo"]["found"] is False

    result = runner.invoke(app, ["motion", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "Motion Planning" in result.output
    assert "FakeGPU RTX 9090" in result.output


def test_motion_serve_starts_tracked_run(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    fake_ros_world.packages("isaac_ros_cumotion")
    result = runner.invoke(app, ["motion", "serve"])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "motion"
    assert manifest["backend"] == "ros"
    assert manifest["command"][-2:] == [
        "isaac_ros_cumotion",
        "isaac_ros_cumotion.launch.py",
    ]
    assert manifest["extra"] == {"domain": "motion", "capability": "cumotion"}


def test_motion_serve_nothing_installed(runner, fake_ros_world):
    fake_ros_world.packages()
    result = runner.invoke(app, ["motion", "serve"])
    assert result.exit_code == 1
    assert "No motion capability is installed." in all_output(result)


def test_motion_plan_sends_goal(runner, fake_ros_world):
    fake_ros_world.actions("/compute_ik", "/follow_joint_trajectory")
    result = runner.invoke(app, ["motion", "plan", "/compute_ik"])
    assert result.exit_code == 0, all_output(result)
    assert "action send_goal /compute_ik" in result.output


def test_motion_execute_passes_extra_args(runner, fake_ros_world):
    fake_ros_world.actions("/follow_joint_trajectory")
    result = runner.invoke(
        app, ["motion", "execute", "/follow_joint_trajectory", "--feedback"]
    )
    assert result.exit_code == 0, all_output(result)
    assert "action send_goal /follow_joint_trajectory --feedback" in result.output


def test_motion_plan_json(runner, fake_ros_world):
    fake_ros_world.actions("/compute_ik")
    result = runner.invoke(app, ["motion", "plan", "/compute_ik", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["returncode"] == 0
    assert data["command"][-2:] == ["send_goal", "/compute_ik"]
    assert data["stdout"].strip() == "action send_goal /compute_ik"


def test_motion_plan_unknown_action(runner, fake_ros_world):
    fake_ros_world.actions("/compute_ik")
    result = runner.invoke(app, ["motion", "plan", "/move_arm"])
    assert result.exit_code == 1
    assert "No action server for '/move_arm'. Available: /compute_ik" in all_output(result)


def test_motion_plan_without_action_server(runner, fake_ros_world):
    fake_ros_world.actions()
    result = runner.invoke(app, ["motion", "plan", "/compute_ik"])
    assert result.exit_code == 1
    assert "No action server is reachable." in all_output(result)
    assert "caasi motion serve" in all_output(result)


def test_motion_plan_without_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["motion", "plan", "/compute_ik"])
    assert result.exit_code == 1
    assert "ros2 CLI not found" in all_output(result)


def test_motion_benchmark_runs_script(runner, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    script = tmp_path / "plan_time.py"
    script.write_text("print('plan 0.31 s')\n", encoding="utf-8")
    result = runner.invoke(app, ["motion", "benchmark", str(script), "--name", "planner"])
    assert result.exit_code == 0, all_output(result)
    assert "caasi benchmark report" in result.output
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "benchmark"
    assert manifest["backend"] == "script"
    assert manifest["name"] == "planner"
    assert manifest["command"][:2] == [sys.executable, str(script)]
    assert manifest["extra"] == {"domain": "motion", "script": str(script)}
    assert "plan 0.31 s" in (run_dir / "stdout.log").read_text(encoding="utf-8")


def test_motion_benchmark_runs_shell_script(runner, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    script = tmp_path / "bench.sh"
    script.write_text("#!/usr/bin/env bash\necho 'bench done'\n", encoding="utf-8")
    script.chmod(0o755)
    result = runner.invoke(app, ["motion", "benchmark", str(script)])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["command"] == [str(script)]
    assert manifest["name"] == "bench"


def test_motion_benchmark_missing_script(runner, tmp_path):
    result = runner.invoke(app, ["motion", "benchmark", str(tmp_path / "nope.py")])
    assert result.exit_code == 1
    assert "Script not found:" in all_output(result)
