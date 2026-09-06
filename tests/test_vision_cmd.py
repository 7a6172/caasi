"""Tests for the `caasi vision` commands."""

from __future__ import annotations

import json
import stat

from caasi.cli.main import app
from caasi.core import vision as vision_core
from caasi.core.vision import VisionComponent

from .conftest import all_output


def fake_components(monkeypatch, opencv_installed=True):
    components = [
        VisionComponent("opencv", opencv_installed, "4.10.0" if opencv_installed else None, "cv2"),
        VisionComponent("open3d", False, None, "open3d"),
    ]
    monkeypatch.setattr(vision_core, "component_status", lambda: components)
    return components


def fake_python(tmp_path, body: str) -> str:
    script = tmp_path / "fake-python"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_vision_status(runner, monkeypatch):
    fake_components(monkeypatch)
    result = runner.invoke(app, ["vision", "status"])
    assert result.exit_code == 0
    assert "opencv" in result.output
    assert "installed" in result.output
    assert "missing" in result.output


def test_vision_status_json(runner, monkeypatch):
    fake_components(monkeypatch)
    result = runner.invoke(app, ["vision", "status", "--json"])
    assert result.exit_code == 0
    data = {c["name"]: c for c in json.loads(result.output)}
    assert data["opencv"] == {
        "name": "opencv",
        "installed": True,
        "version": "4.10.0",
        "module": "cv2",
    }
    assert data["open3d"]["installed"] is False


def test_vision_inspect(runner, monkeypatch):
    fake_components(monkeypatch)
    result = runner.invoke(app, ["vision", "inspect", "opencv"])
    assert result.exit_code == 0
    assert "4.10.0" in result.output
    assert "cv2" in result.output


def test_vision_inspect_unknown(runner, monkeypatch):
    fake_components(monkeypatch)
    result = runner.invoke(app, ["vision", "inspect", "photoshop"])
    assert result.exit_code == 1
    assert "Unknown vision component" in all_output(result)


def test_vision_test_pass(runner, tmp_path, monkeypatch):
    fake_components(monkeypatch)
    python = fake_python(tmp_path, "echo 4.10.0")
    result = runner.invoke(app, ["vision", "test", "opencv", "--python", python])
    assert result.exit_code == 0
    assert "opencv: 4.10.0" in result.output


def test_vision_test_probe_failure(runner, tmp_path, monkeypatch):
    fake_components(monkeypatch)
    python = fake_python(tmp_path, "echo boom >&2\nexit 1")
    result = runner.invoke(app, ["vision", "test", "opencv", "--python", python])
    assert result.exit_code == 1
    assert "opencv: boom" in result.output


def test_vision_test_missing_component(runner, tmp_path, monkeypatch):
    fake_components(monkeypatch, opencv_installed=False)
    python = fake_python(tmp_path, "echo unused")
    result = runner.invoke(app, ["vision", "test", "opencv", "--python", python])
    assert result.exit_code == 1
    assert "opencv: missing" in result.output


def test_vision_test_unknown_component(runner, monkeypatch):
    fake_components(monkeypatch)
    result = runner.invoke(app, ["vision", "test", "photoshop"])
    assert result.exit_code == 1
    assert "Unknown vision component" in all_output(result)


def test_vision_test_json(runner, tmp_path, monkeypatch):
    fake_components(monkeypatch)
    python = fake_python(tmp_path, "echo 4.10.0")
    result = runner.invoke(
        app, ["vision", "test", "opencv", "--python", python, "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == [{"name": "opencv", "ok": True, "detail": "4.10.0"}]
