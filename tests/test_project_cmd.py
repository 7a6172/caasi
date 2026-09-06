"""Tests for `caasi init` and `caasi project`."""

from __future__ import annotations

import json

import yaml

from caasi.cli.main import app
from caasi.core import project as projects

from .conftest import all_output


def test_init_creates_scaffold(runner, tmp_path):
    target = tmp_path / "warehouse"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    assert "Created project 'warehouse'" in result.output
    assert (target / "caasi.yaml").is_file()
    for sub in projects.PROJECT_DIRS:
        assert (target / sub).is_dir()


def test_init_name_flag_and_json(runner, tmp_path):
    target = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(target), "--name", "custom", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "custom"
    assert set(data["dirs"]) == set(projects.PROJECT_DIRS)


def test_init_refuses_existing_without_force(runner, tmp_path):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 1
    assert "already exists" in all_output(result)

    result = runner.invoke(app, ["init", str(target), "--force"])
    assert result.exit_code == 0


def test_project_info_outside_project(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["project", "info"])
    assert result.exit_code == 1
    assert "Not inside a Caasi project" in all_output(result)


def test_project_info_and_validate(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target), "--name", "demo"])
    monkeypatch.chdir(target)

    result = runner.invoke(app, ["robot", "create", "go2"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["project", "info"])
    assert result.exit_code == 0
    assert "demo" in result.output

    result = runner.invoke(app, ["project", "info", "--json"])
    data = json.loads(result.output)
    assert data["name"] == "demo"
    assert data["counts"]["robot"] == 1

    result = runner.invoke(app, ["project", "validate"])
    assert result.exit_code == 0
    assert "is valid" in result.output


def test_project_validate_reports_issues(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    (target / "robots").rmdir()

    result = runner.invoke(app, ["project", "validate"])
    assert result.exit_code == 1
    assert "robots/" in result.output


def test_init_writes_valid_yaml(runner, tmp_path):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    data = yaml.safe_load((target / "caasi.yaml").read_text())
    assert data["kind"] == "project"
