"""Tests for the `caasi sensor` commands (fake /dev + sysfs)."""

from __future__ import annotations

import json

from caasi.cli.main import app
from caasi.core import sensors as sensors_core

from .conftest import all_output


def fake_devices(tmp_path, monkeypatch, cameras=True, serial=True):
    dev = tmp_path / "dev"
    dev.mkdir()
    sysv = tmp_path / "sys" / "class" / "video4linux"
    sysv.mkdir(parents=True)
    if cameras:
        (dev / "video0").write_text("")
        (sysv / "video0").mkdir()
        (sysv / "video0" / "name").write_text("Fake Cam", encoding="utf-8")
    if serial:
        (dev / "ttyUSB0").write_text("")
    monkeypatch.setattr(sensors_core, "DEV_ROOT", dev)
    monkeypatch.setattr(sensors_core, "V4L_SYS_ROOT", sysv)
    monkeypatch.setattr(sensors_core, "ZED_PATHS", (tmp_path / "no-zed",))
    return dev


def test_sensor_list(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch)
    result = runner.invoke(app, ["sensor", "list"])
    assert result.exit_code == 0
    assert "cameras" in result.output
    assert "lidar" in result.output
    assert "detected" in result.output


def test_sensor_list_json(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch)
    result = runner.invoke(app, ["sensor", "list", "--json"])
    assert result.exit_code == 0
    data = {entry["name"]: entry for entry in json.loads(result.output)}
    assert data["cameras"]["detected"] is True
    assert data["cameras"]["devices"] == [f"{tmp_path / 'dev' / 'video0'} (Fake Cam)"]
    assert data["lidar"]["detected"] is True
    assert data["isaacsim"]["detected"] is False  # nothing registered in tests


def test_sensor_list_no_devices(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch, cameras=False, serial=False)
    result = runner.invoke(app, ["sensor", "list", "--json"])
    data = {entry["name"]: entry for entry in json.loads(result.output)}
    assert data["cameras"]["detected"] is False
    assert data["lidar"]["detected"] is False


def test_sensor_inspect(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch)
    result = runner.invoke(app, ["sensor", "inspect", "cameras"])
    assert result.exit_code == 0
    assert "Fake Cam" in result.output
    assert "video4linux" in result.output

    result = runner.invoke(app, ["sensor", "inspect", "cameras", "--json"])
    data = json.loads(result.output)
    assert data["kind"] == "video4linux"
    assert data["detected"] is True


def test_sensor_inspect_unknown(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch)
    result = runner.invoke(app, ["sensor", "inspect", "flux-capacitor"])
    assert result.exit_code == 1
    assert "Unknown sensor" in all_output(result)


def test_sensor_test_pass(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch)
    result = runner.invoke(app, ["sensor", "test", "cameras"])
    assert result.exit_code == 0
    assert "is available" in result.output


def test_sensor_test_fail(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch)
    monkeypatch.setattr(sensors_core.pydist, "pip_version", lambda *c: None)
    result = runner.invoke(app, ["sensor", "test", "realsense"])
    assert result.exit_code == 1
    assert "not available" in result.output
    assert "pyrealsense2" in result.output


def test_sensor_test_json(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch)
    result = runner.invoke(app, ["sensor", "test", "cameras", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {
        "name": "cameras",
        "ok": True,
        "detail": "1 device(s)",
    }
