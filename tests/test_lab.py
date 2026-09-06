"""Tests for the `caasi lab` commands."""

from __future__ import annotations

import json

from caasi.cli.main import app


def test_lab_status_not_detected(runner):
    result = runner.invoke(app, ["lab", "status"])
    assert result.exit_code == 0
    assert "not detected" in result.output


def test_lab_status_json(runner):
    result = runner.invoke(app, ["lab", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "fail"
    assert data["path"] is None
    assert data["launcher"] is None


def test_lab_status_configured_tool(runner, tmp_path, monkeypatch):
    labdir = tmp_path / "lab"
    labdir.mkdir()
    (labdir / "isaaclab.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    config = tmp_path / "caasi-test.yaml"
    config.write_text(
        "tools:\n"
        "  isaaclab:\n"
        '    default: "2.0"\n'
        "    versions:\n"
        '      "2.0":\n'
        f"        path: {labdir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(config))

    result = runner.invoke(app, ["lab", "status"])
    assert result.exit_code == 0
    assert "Isaac Lab 2.0" in result.output
    assert "Launcher:" in result.output
    assert "isaaclab.sh" in result.output

    result = runner.invoke(app, ["lab", "status", "--json"])
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["launcher"] == str(labdir / "isaaclab.sh")
