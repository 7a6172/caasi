"""Tests for the `caasi control` commands."""

from __future__ import annotations

import json
import textwrap

import yaml

from caasi.cli.main import app
from caasi.core import ros as ros_core
from caasi.utils import shell
from .test_ros_cmd import fake_ros  # noqa: F401

GOOD_PARAMS = textwrap.dedent(
    """\
    controller_manager:
      ros__parameters:
        update_rate: 100
        joint_state_broadcaster:
          type: joint_state_broadcaster/JointStateBroadcaster
        diff_drive_controller:
          type: diff_drive_controllers/DiffDriveController
    diff_drive_controller:
      ros__parameters:
        left_wheel_names: ["left_wheel_joint"]
    """
)

BAD_PARAMS = textwrap.dedent(
    """\
    controller_manager:
      ros__parameters:
        joint_state_broadcaster:
          type: joint_state_broadcaster/JointStateBroadcaster
        broken_controller:
          name: missing-type
    """
)


def test_control_status(runner, fake_ros):  # noqa: F811
    result = runner.invoke(app, ["control", "status", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["installed"] is True
    assert data["managers"] == ["/controller_manager"]

    result = runner.invoke(app, ["control", "status"])
    assert result.exit_code == 0
    assert "/controller_manager" in result.output


def test_control_status_not_installed(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ros_core, "pkg_prefix", lambda name: None)
    result = runner.invoke(app, ["control", "status", "--json"])
    data = json.loads(result.output)
    assert data["installed"] is False


def test_control_list(runner, fake_ros):  # noqa: F811
    result = runner.invoke(app, ["control", "list"])
    assert result.exit_code == 0
    assert "joint_state_broadcaster" in result.output
    assert "diff_drive_controller" in result.output

    result = runner.invoke(app, ["control", "list", "--json"])
    data = json.loads(result.output)
    assert len(data) == 2
    assert any("active" in line for line in data)


def test_control_list_without_cli(runner, fake_ros, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        ros_core,
        "run_ros2",
        lambda args, timeout=None: shell.ShellResult(1, "", "unknown command"),
    )
    result = runner.invoke(app, ["control", "list"])
    assert result.exit_code == 1
    assert "ros2_control CLI not found" in result.output


def test_control_check_good(runner, fake_ros, tmp_path):  # noqa: F811
    params = tmp_path / "controllers.yaml"
    params.write_text(GOOD_PARAMS, encoding="utf-8")

    result = runner.invoke(app, ["control", "check", str(params), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["controllers"] == ["joint_state_broadcaster", "diff_drive_controller"]
    assert data["issues"] == []

    result = runner.invoke(app, ["control", "check", str(params)])
    assert result.exit_code == 0
    assert "looks good (2 controller(s))" in result.output


def test_control_check_issues(runner, fake_ros, tmp_path):  # noqa: F811
    params = tmp_path / "bad.yaml"
    params.write_text(BAD_PARAMS, encoding="utf-8")

    result = runner.invoke(app, ["control", "check", str(params), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    issues = "\n".join(data["issues"])
    assert "update_rate" in issues
    assert "broken_controller" in issues

    result = runner.invoke(app, ["control", "check", str(params)])
    assert result.exit_code == 1
    assert "no 'update_rate'" in result.output
    assert "broken_controller" in result.output


def test_control_check_missing_manager(runner, fake_ros, tmp_path):  # noqa: F811
    params = tmp_path / "empty.yaml"
    params.write_text(yaml.safe_dump({"something_else": {}}), encoding="utf-8")
    result = runner.invoke(app, ["control", "check", str(params), "--json"])
    assert result.exit_code == 1
    assert "controller_manager" in "\n".join(json.loads(result.output)["issues"])


def test_control_check_requires_file(runner, fake_ros, tmp_path):  # noqa: F811
    result = runner.invoke(app, ["control", "check"])
    assert result.exit_code == 1
    assert "Provide a params file" in result.output

    result = runner.invoke(app, ["control", "check", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1
    assert "No params file found" in result.output
