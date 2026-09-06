"""Tests for the project/definitions core module."""

from __future__ import annotations

import pytest

from caasi.core import project as projects


def test_create_project(tmp_path):
    target = tmp_path / "warehouse"
    root = projects.create_project(target)
    assert root == target
    assert (root / "caasi.yaml").is_file()
    for sub in projects.PROJECT_DIRS:
        assert (root / sub).is_dir()
    meta = projects.load_project_meta(root)
    assert meta == {"kind": "project", "name": "warehouse", "version": 1}


def test_create_project_custom_name_and_twice(tmp_path):
    target = tmp_path / "p"
    projects.create_project(target, name="custom")
    assert projects.load_project_meta(target)["name"] == "custom"

    with pytest.raises(projects.ProjectError, match="already exists"):
        projects.create_project(target)
    # --force overwrites the meta file without touching existing dirs
    projects.create_project(target, name="forced", force=True)
    assert projects.load_project_meta(target)["name"] == "forced"


def test_create_project_rejects_file(tmp_path):
    file = tmp_path / "file.txt"
    file.write_text("x")
    with pytest.raises(projects.ProjectError, match="is a file"):
        projects.create_project(file)


def test_find_project_root_walks_up(tmp_path, monkeypatch):
    projects.create_project(tmp_path / "proj")
    nested = tmp_path / "proj" / "tasks" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert projects.find_project_root() == (tmp_path / "proj").resolve()


def test_find_project_root_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert projects.find_project_root() is None


def test_definitions_roundtrip(tmp_path):
    root = projects.create_project(tmp_path / "proj")
    path = projects.save_definition(root, "robot", "go2", description="Quadruped")
    assert path == root / "robots" / "go2.yaml"
    assert "kind: robot" in path.read_text()

    data = projects.load_definition(root, "robot", "go2")
    assert data["name"] == "go2"
    assert data["description"] == "Quadruped"

    projects.save_definition(root, "robot", "aaa")
    names = [e["name"] for e in projects.list_definitions(root, "robot")]
    assert names == ["aaa", "go2"]

    assert projects.load_definition(root, "robot", "nope") is None
    assert projects.list_definitions(root, "scene") == []


def test_save_definition_validation(tmp_path):
    root = projects.create_project(tmp_path / "proj")
    with pytest.raises(projects.ProjectError, match="invalid name"):
        projects.save_definition(root, "robot", "bad name")
    projects.save_definition(root, "robot", "go2")
    with pytest.raises(projects.ProjectError, match="already exists"):
        projects.save_definition(root, "robot", "go2")
    # overwrite is allowed explicitly
    projects.save_definition(root, "robot", "go2", overwrite=True)


def test_validate_project_ok(tmp_path):
    root = projects.create_project(tmp_path / "proj")
    projects.save_definition(root, "robot", "go2")
    assert projects.validate_project(root) == []


def test_validate_project_missing_pieces(tmp_path):
    root = projects.create_project(tmp_path / "proj")
    (root / "robots").rmdir()
    issues = projects.validate_project(root)
    assert any("robots/" in issue for issue in issues)


def test_validate_project_bad_definition(tmp_path):
    root = projects.create_project(tmp_path / "proj")
    (root / "tasks" / "nav.yaml").write_text("kind: robot\n", encoding="utf-8")
    issues = projects.validate_project(root)
    assert any("kind is 'robot'" in issue for issue in issues)


def test_validate_project_missing_name(tmp_path):
    root = projects.create_project(tmp_path / "proj")
    (root / "caasi.yaml").write_text("kind: project\n", encoding="utf-8")
    issues = projects.validate_project(root)
    assert any("'name' is missing" in issue for issue in issues)
