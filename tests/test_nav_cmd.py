"""Tests for the `caasi nav` commands."""

from __future__ import annotations

import json

import yaml

from caasi.cli.main import app
from caasi.core import ros as ros_core
from .test_ros_cmd import configure_runs, fake_ros, wait_for_run  # noqa: F401


def test_nav_status(runner, fake_ros):  # noqa: F811
    result = runner.invoke(app, ["nav", "status", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["installed"] is True
    assert data["bringup"] == str(fake_ros["prefix"])
    assert data["nodes"] == ["/bt_navigator"]

    result = runner.invoke(app, ["nav", "status"])
    assert result.exit_code == 0
    assert "Nav2" in result.output and "/bt_navigator" in result.output


def test_nav_status_not_installed(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ros_core, "pkg_prefix", lambda name: None)
    result = runner.invoke(app, ["nav", "status", "--json"])
    data = json.loads(result.output)
    assert data["installed"] is False

    result = runner.invoke(app, ["nav", "status"])
    assert "nav2_bringup" in result.output  # not-installed hint mentions the package


def test_nav_launch_dry_run(runner, fake_ros, tmp_path):  # noqa: F811
    result = runner.invoke(
        app,
        [
            "nav", "launch",
            "--params", str(tmp_path / "params.yaml"),
            "--map", str(tmp_path / "map.yaml"),
            "--dry-run", "use_sim_time:=true",
        ],
    )
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert f"params_file:={tmp_path / 'params.yaml'}" in result.output
    assert f"map:={tmp_path / 'map.yaml'}" in result.output
    assert "launch nav2_bringup bringup_launch.py" in result.output
    assert "use_sim_time:=true" in result.output


def test_nav_launch_requires_bringup(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ros_core, "pkg_prefix", lambda name: None)
    result = runner.invoke(app, ["nav", "launch"])
    assert result.exit_code == 1
    assert "Nav2 not found" in result.output


def test_nav_launch_tracked_run(runner, fake_ros, tmp_path, monkeypatch):  # noqa: F811
    runs_base = configure_runs(tmp_path, monkeypatch)
    result = runner.invoke(app, ["nav", "launch", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "nav" and data["name"] == "nav2-bringup"

    run_dir = wait_for_run(runs_base)
    assert (run_dir / "exit_code").read_text().strip() == "0"
    assert "launch nav2_bringup bringup_launch.py" in (run_dir / "stdout.log").read_text()


def test_nav_inspect_default_params(runner, fake_ros):  # noqa: F811
    expected = fake_ros["prefix"] / "share" / "nav2_bringup" / "params" / "nav2_params.yaml"
    result = runner.invoke(app, ["nav", "inspect", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["path"] == str(expected)
    assert data["nodes"] == ["amcl", "bt_navigator", "planner_server"]

    result = runner.invoke(app, ["nav", "inspect"])
    assert result.exit_code == 0
    assert "bt_navigator" in result.output


def test_nav_inspect_explicit_and_missing(runner, fake_ros, tmp_path):  # noqa: F811
    custom = tmp_path / "custom.yaml"
    custom.write_text(yaml.safe_dump({"my_planner": {"ros__parameters": {}}}), encoding="utf-8")
    result = runner.invoke(app, ["nav", "inspect", str(custom), "--json"])
    assert json.loads(result.output)["nodes"] == ["my_planner"]

    result = runner.invoke(app, ["nav", "inspect", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1
    assert "No params file found" in result.output


def test_nav_test_pass(runner, fake_ros):  # noqa: F811
    result = runner.invoke(app, ["nav", "test", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert [check["check"] for check in data["checks"]] == ["ros2", "nav2_bringup", "nodes"]

    result = runner.invoke(app, ["nav", "test"])
    assert result.exit_code == 0
    assert "Nav2 is ready" in result.output


def test_nav_test_fail_without_nodes(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ros_core, "ros2_lines", lambda args, timeout=None: [])
    result = runner.invoke(app, ["nav", "test", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["checks"][2]["ok"] is False

    result = runner.invoke(app, ["nav", "test"])
    assert result.exit_code == 1
    assert "not ready" in result.output
