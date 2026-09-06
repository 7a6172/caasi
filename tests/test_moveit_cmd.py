"""Tests for the `caasi moveit` commands."""

from __future__ import annotations

import json

import yaml

from caasi.cli.main import app
from caasi.core import ros as ros_core
from .test_ros_cmd import configure_runs, fake_ros, wait_for_run  # noqa: F401


def test_moveit_status(runner, fake_ros):  # noqa: F811
    result = runner.invoke(app, ["moveit", "status", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["installed"] is True
    assert data["package"] == str(fake_ros["prefix"])
    assert data["move_group_nodes"] == ["/move_group"]

    result = runner.invoke(app, ["moveit", "status"])
    assert result.exit_code == 0
    assert "/move_group" in result.output


def test_moveit_status_not_installed(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ros_core, "pkg_prefix", lambda name: None)
    result = runner.invoke(app, ["moveit", "status", "--json"])
    data = json.loads(result.output)
    assert data["installed"] is False
    assert data["move_group_nodes"] == ["/move_group"]  # node detection is independent


def test_moveit_launch_dry_run(runner, fake_ros, tmp_path):  # noqa: F811
    result = runner.invoke(
        app,
        [
            "moveit", "launch", "demo.launch.py",
            "--package", "panda_moveit_config", "--dry-run", "rviz:=false",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "launch panda_moveit_config demo.launch.py rviz:=false" in result.output

    result = runner.invoke(app, ["moveit", "launch", str(tmp_path / "missing.launch.py")])
    assert result.exit_code == 1
    assert "No such launch file" in result.output


def test_moveit_launch_tracked_run(runner, fake_ros, tmp_path, monkeypatch):  # noqa: F811
    runs_base = configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(
        app,
        ["moveit", "launch", "demo.launch.py", "--package", "panda_moveit_config", "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "moveit"

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text())
    assert manifest["kind"] == "moveit"


def test_moveit_plan_ready(runner, fake_ros):  # noqa: F811
    result = runner.invoke(app, ["moveit", "plan", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ready"] is True
    assert data["move_group_nodes"] == ["/move_group"]

    result = runner.invoke(app, ["moveit", "plan", "--group", "arm"])
    assert result.exit_code == 0
    assert "Motion planning available" in result.output
    assert "arm" in result.output


def test_moveit_plan_not_ready(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ros_core, "ros2_lines", lambda args, timeout=None: [])
    result = runner.invoke(app, ["moveit", "plan", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["ready"] is False

    result = runner.invoke(app, ["moveit", "plan"])
    assert result.exit_code == 1
    assert "No move_group node is running" in result.output


def test_moveit_test_pass(runner, fake_ros):  # noqa: F811
    result = runner.invoke(app, ["moveit", "test", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert [check["check"] for check in data["checks"]] == [
        "ros2", "moveit_ros_move_group", "move_group",
    ]

    result = runner.invoke(app, ["moveit", "test"])
    assert result.exit_code == 0
    assert "MoveIt 2 is ready" in result.output


def test_moveit_test_fail(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ros_core, "pkg_prefix", lambda name: None)
    result = runner.invoke(app, ["moveit", "test"])
    assert result.exit_code == 1
    assert "not ready" in result.output
