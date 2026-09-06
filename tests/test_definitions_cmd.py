"""Tests for `caasi robot` / `caasi scene` / `caasi task`."""

from __future__ import annotations

import json

import pytest

from caasi.cli.main import app

from .conftest import all_output


@pytest.fixture
def project_dir(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    monkeypatch.chdir(target)
    return target


def test_create_list_inspect_info(runner, project_dir):
    result = runner.invoke(
        app, ["robot", "create", "go2", "--description", "Quadruped robot"]
    )
    assert result.exit_code == 0
    assert "go2" in result.output
    assert (project_dir / "robots" / "go2.yaml").is_file()

    result = runner.invoke(app, ["robot", "list"])
    assert result.exit_code == 0
    assert "go2" in result.output
    assert "Quadruped robot" in result.output

    result = runner.invoke(app, ["robot", "list", "--json"])
    data = json.loads(result.output)
    assert data[0]["name"] == "go2"

    result = runner.invoke(app, ["robot", "inspect", "go2"])
    assert result.exit_code == 0
    assert "kind: robot" in result.output

    result = runner.invoke(app, ["robot", "inspect", "go2", "--json"])
    data = json.loads(result.output)
    assert data["name"] == "go2"

    result = runner.invoke(app, ["robot", "info", "go2"])
    assert result.exit_code == 0
    assert "go2" in result.output
    assert "Quadruped robot" in result.output


def test_scene_and_task(runner, project_dir):
    result = runner.invoke(app, ["scene", "create", "warehouse"])
    assert result.exit_code == 0
    result = runner.invoke(app, ["task", "create", "navigation"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["scene", "list"])
    assert "warehouse" in result.output
    result = runner.invoke(app, ["task", "list"])
    assert "navigation" in result.output

    result = runner.invoke(app, ["scene", "inspect", "warehouse"])
    assert "kind: scene" in result.output
    result = runner.invoke(app, ["task", "inspect", "navigation"])
    assert "kind: task" in result.output


def test_list_empty_hint(runner, project_dir):
    result = runner.invoke(app, ["robot", "list"])
    assert result.exit_code == 0
    assert "caasi robot create" in result.output


def test_outside_project(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["robot", "list"])
    assert result.exit_code == 1
    assert "Not inside a Caasi project" in all_output(result)


def test_create_duplicate_and_invalid_name(runner, project_dir):
    runner.invoke(app, ["robot", "create", "go2"])
    result = runner.invoke(app, ["robot", "create", "go2"])
    assert result.exit_code == 1
    assert "already exists" in all_output(result)

    result = runner.invoke(app, ["robot", "create", "bad name"])
    assert result.exit_code == 1
    assert "invalid name" in all_output(result)


def test_inspect_missing(runner, project_dir):
    result = runner.invoke(app, ["robot", "inspect", "nope"])
    assert result.exit_code == 1
    assert "No robot named 'nope'" in all_output(result)

    result = runner.invoke(app, ["robot", "info", "nope"])
    assert result.exit_code == 1
