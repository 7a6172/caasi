"""Tests for `caasi native` and `caasi shell`."""

from __future__ import annotations

import json
import stat

import pytest

from caasi.cli.main import app

from .conftest import all_output


@pytest.fixture
def fake_sim(tmp_path, monkeypatch):
    """Register a fake Isaac Sim install whose python.sh echoes its args."""
    simdir = tmp_path / "isaac-sim"
    (simdir / "bin").mkdir(parents=True)
    launcher = simdir / "python.sh"
    launcher.write_text('#!/usr/bin/env bash\necho "fake-sim $@"\n')
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)

    config = tmp_path / "caasi-test.yaml"
    config.write_text(
        "tools:\n"
        "  isaacsim:\n"
        '    default: "6.0"\n'
        "    versions:\n"
        '      "6.0":\n'
        f"        path: {simdir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(config))
    return simdir


def test_native_sim(fake_sim, runner):
    result = runner.invoke(app, ["native", "sim", "hello.py", "--flag"])
    assert result.exit_code == 0
    assert "fake-sim hello.py --flag" in result.output


def test_native_sim_missing(runner):
    result = runner.invoke(app, ["native", "sim"])
    assert result.exit_code == 1
    assert "No install for isaacsim" in all_output(result)


def test_native_lab_missing(runner):
    result = runner.invoke(app, ["native", "lab"])
    assert result.exit_code == 1
    assert "No install for isaaclab" in all_output(result)


def test_native_ros_missing(runner, monkeypatch):
    monkeypatch.setattr(
        "caasi.cli.native_cmd.ros_core.find_ros2_binary", lambda: None
    )
    result = runner.invoke(app, ["native", "ros"])
    assert result.exit_code == 1
    assert "ros2 CLI not found" in all_output(result)


def test_native_run_python(runner, tmp_path):
    script = tmp_path / "script.py"
    script.write_text("import sys\nprint('ran', sys.argv[1:])\n", encoding="utf-8")
    result = runner.invoke(app, ["native", "run", str(script), "a", "b"])
    assert result.exit_code == 0
    assert "ran ['a', 'b']" in result.output


def test_native_run_sim_tool(fake_sim, runner, tmp_path):
    script = tmp_path / "script.py"
    script.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["native", "run", "--tool", "sim", str(script)])
    assert result.exit_code == 0
    assert f"fake-sim {script}" in result.output


def test_native_run_bad_tool(runner, tmp_path):
    script = tmp_path / "script.py"
    script.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["native", "run", "--tool", "gazebo", str(script)])
    assert result.exit_code == 1
    assert "Unknown --tool 'gazebo'" in all_output(result)


def test_shell_command_env(fake_sim, runner):
    result = runner.invoke(app, ["shell", "--command", "echo $ISAACSIM_PATH"])
    assert result.exit_code == 0
    assert "isaac-sim" in result.output


def test_shell_command_exit_code(fake_sim, runner):
    result = runner.invoke(app, ["shell", "--command", "exit 3"])
    assert result.exit_code == 3


def test_shell_command_json(fake_sim, runner):
    result = runner.invoke(app, ["shell", "--command", "echo hi", "--json"])
    data = json.loads(result.output)
    assert data["returncode"] == 0
    assert "hi" in data["stdout"]
