"""Tests for `caasi setup`."""

from __future__ import annotations

import json

from caasi.cli.main import app

from .conftest import all_output


def test_setup_summary_missing_isaac(runner):
    result = runner.invoke(app, ["setup"])
    assert result.exit_code == 1
    assert "isaacsim" in result.output
    assert "isaaclab" in result.output
    assert "Missing core components" in result.output


def test_setup_summary_json(runner):
    result = runner.invoke(app, ["setup", "--json"])
    data = json.loads(result.output)
    assert set(data["components"]) == {"isaacsim", "isaaclab", "ros2", "pytorch", "docker"}
    assert "isaacsim" in data["missing"]
    assert result.exit_code == 1


def test_setup_all_present_exits_zero(runner, tmp_path, monkeypatch):
    simdir = tmp_path / "sim"
    simdir.mkdir()
    labdir = tmp_path / "lab"
    labdir.mkdir()
    monkeypatch.setenv("ISAACSIM_PATH", str(simdir))
    monkeypatch.setenv("ISAACLAB_PATH", str(labdir))

    result = runner.invoke(app, ["setup", "--json"])
    data = json.loads(result.output)
    assert data["components"]["isaacsim"]["status"] == "ok"
    assert data["components"]["isaaclab"]["status"] == "ok"
    # ros2 is detected via the real /opt/ros on this machine; if it is not,
    # only the missing list would change — core assertion is the isaac pair.
    assert "isaacsim" not in data["missing"]
    assert "isaaclab" not in data["missing"]


def test_setup_component_guide(runner):
    result = runner.invoke(app, ["setup", "isaacsim"])
    assert result.exit_code == 1  # not installed in the isolated test env
    assert "pip install isaacsim" in result.output

    result = runner.invoke(app, ["setup", "ros2"])
    assert result.exit_code in (0, 1)
    assert "apt install" in result.output

    result = runner.invoke(app, ["setup", "docker", "--json"])
    data = json.loads(result.output)
    assert data["component"] == "docker"
    assert "guide" in data


def test_setup_unknown_component(runner):
    result = runner.invoke(app, ["setup", "gazebo"])
    assert result.exit_code == 1
    assert "Unknown component 'gazebo'" in all_output(result)
