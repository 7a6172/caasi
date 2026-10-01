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


def test_project_init_is_canonical(runner, tmp_path):
    # v0.3.0 IA: `project init` is canonical; root `init` is a thin alias.
    target = tmp_path / "warehouse"
    result = runner.invoke(app, ["project", "init", str(target), "--name", "wh"])
    assert result.exit_code == 0
    assert "Created project 'wh'" in result.output
    assert (target / "caasi.yaml").is_file()
    for sub in projects.PROJECT_DIRS:
        assert (target / sub).is_dir()
    assert "init" in runner.invoke(app, ["project", "--help"]).output


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

    result = runner.invoke(app, ["project", "robot", "create", "go2"])
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
    assert data["schema"] == 1
    assert data["name"] == "proj"
    assert data["version"] == "0.0.0"
    assert "kind" not in data


def test_project_add_creates_component_dirs(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target), "--name", "demo"])
    monkeypatch.chdir(target)

    result = runner.invoke(app, ["project", "add", "isaac.lab"])
    assert result.exit_code == 0
    assert (target / "isaac" / "lab" / "tasks").is_dir()

    data = yaml.safe_load((target / "caasi.yaml").read_text())
    assert data["components"]["isaac_lab"] is True
    # requires stub merged on add
    assert "isaac_lab" in data["requires"]

    # underscore form resolves to the same component
    result = runner.invoke(app, ["project", "add", "nav2"])
    assert result.exit_code == 0
    assert (target / "nav" / "maps").is_dir()


def test_project_add_unknown_component(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["project", "add", "bogus"])
    assert result.exit_code == 1
    assert "Unknown component" in all_output(result)


def test_project_list_shows_catalog(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    runner.invoke(app, ["project", "add", "ros2"])

    result = runner.invoke(app, ["project", "list", "--json"])
    assert result.exit_code == 0
    rows = {row["component"]: row for row in json.loads(result.output)}
    assert rows["ros2"]["registered"] is True
    assert rows["isaac.sim"]["registered"] is False


def test_project_inspect_reports_manifest(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target), "--name", "demo"])
    monkeypatch.chdir(target)
    runner.invoke(app, ["project", "add", "nav2"])

    result = runner.invoke(app, ["project", "inspect", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema"] == 1
    assert data["name"] == "demo"
    assert "nav2" in data["components"]


def test_project_remove_unregisters(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    runner.invoke(app, ["project", "add", "ros2"])
    assert (target / "ros" / "launch").is_dir()

    result = runner.invoke(app, ["project", "remove", "ros2"])
    assert result.exit_code == 0
    data = yaml.safe_load((target / "caasi.yaml").read_text())
    assert "ros2" not in (data.get("components") or {})
    # empty dirs removed
    assert not (target / "ros" / "launch").exists()


def test_project_remove_keeps_non_empty_without_purge(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    runner.invoke(app, ["project", "add", "ros2"])
    (target / "ros" / "launch" / "keep.py").write_text("x", encoding="utf-8")

    result = runner.invoke(app, ["project", "remove", "ros2"])
    assert result.exit_code == 0
    assert (target / "ros" / "launch" / "keep.py").is_file()

    result = runner.invoke(app, ["project", "remove", "ros2", "--purge"])
    # already unregistered -> second remove reports not registered
    assert result.exit_code == 1


def test_project_remove_purge_deletes_non_empty(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    runner.invoke(app, ["project", "add", "ros2"])
    (target / "ros" / "launch" / "keep.py").write_text("x", encoding="utf-8")

    result = runner.invoke(app, ["project", "remove", "ros2", "--purge"])
    assert result.exit_code == 0
    assert not (target / "ros" / "launch").exists()


def test_project_add_file_places_deterministically(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    source = tmp_path / "robot.urdf"
    source.write_text("<robot/>", encoding="utf-8")

    result = runner.invoke(app, ["project", "add-file", "robot", "urdf", str(source), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["relative"] == "robot/urdf/robot.urdf"
    assert (target / "robot" / "urdf" / "robot.urdf").is_file()


def test_project_add_file_scene_and_config(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)
    usd = tmp_path / "room.usd"
    usd.write_text("#usda", encoding="utf-8")
    cfg = tmp_path / "params.yaml"
    cfg.write_text("a: 1", encoding="utf-8")

    runner.invoke(app, ["project", "add-file", "isaac.sim", "scene", str(usd)])
    assert (target / "isaac" / "sim" / "scenes" / "room.usd").is_file()
    runner.invoke(app, ["project", "add-file", "ros", "config", str(cfg)])
    assert (target / "ros" / "config" / "params.yaml").is_file()


def test_project_config_get_set(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target)])
    monkeypatch.chdir(target)

    result = runner.invoke(app, ["project", "config", "set", "defaults.layout", "plain"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["project", "config", "get", "defaults.layout"])
    assert result.exit_code == 0
    assert result.output.strip() == "plain"

    result = runner.invoke(app, ["project", "config", "get", "nope.missing"])
    assert result.exit_code == 1


def test_project_config_show(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target), "--name", "demo"])
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["project", "config", "show", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "demo"
    assert data["schema"] == 1


def test_project_validate_component_aware(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target), "--name", "demo"])
    monkeypatch.chdir(target)
    runner.invoke(app, ["project", "add", "isaac.lab"])
    # remove a component directory -> validate must flag it
    import shutil

    shutil.rmtree(target / "isaac" / "lab" / "tasks")
    result = runner.invoke(app, ["project", "validate"])
    assert result.exit_code == 1
    assert "isaac/lab/tasks" in result.output


def test_migrate_legacy_manifest_is_read_not_rewritten(runner, tmp_path, monkeypatch):
    target = tmp_path / "legacy"
    target.mkdir()
    (target / "caasi.yaml").write_text(
        yaml.safe_dump({"kind": "project", "name": "legacy", "version": 1}),
        encoding="utf-8",
    )
    monkeypatch.chdir(target)

    # validate bridges the legacy file (schema 1, version 0.0.0) without a rewrite
    result = runner.invoke(app, ["project", "inspect", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema"] == 1
    assert data["version"] == "0.0.0"
    assert data["name"] == "legacy"
    # read never rewrote the file on disk
    on_disk = yaml.safe_load((target / "caasi.yaml").read_text())
    assert on_disk["kind"] == "project"
    assert on_disk["version"] == 1

