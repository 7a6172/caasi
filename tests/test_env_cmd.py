"""Tests for `caasi env` (inspect/fingerprint/compare/show/lock)."""

from __future__ import annotations

import copy
import json

from caasi.cli.main import app
from caasi.core import check, fingerprint, lock, manifest as manifests, project as projects

from .conftest import all_output


def _patch_collect(monkeypatch, environment: dict) -> None:
    monkeypatch.setattr(fingerprint, "collect", lambda config, sections=None: environment)


def _home(tmp_path):
    return tmp_path / "home"


# -- registration -------------------------------------------------------------

def test_env_group_is_registered(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "env" in result.output


# -- env inspect ----------------------------------------------------------------

def test_env_inspect_json(runner, fake_fingerprint, monkeypatch):
    _patch_collect(monkeypatch, fake_fingerprint)
    result = runner.invoke(app, ["env", "inspect", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["system"]["os"] == "Ubuntu 24.04.3 LTS"
    assert data["python"]["version"] == "3.12.3"


def test_env_inspect_renders_panels(runner, fake_fingerprint, monkeypatch):
    _patch_collect(monkeypatch, fake_fingerprint)
    result = runner.invoke(app, ["env", "inspect"])
    assert result.exit_code == 0
    out = result.output
    assert "Environment" in out
    assert "Ubuntu 24.04.3 LTS" in out
    assert "ROS 2" in out
    assert "jazzy" in out


# -- env fingerprint --------------------------------------------------------------

def test_env_fingerprint_prints_hash_without_saving(runner, fake_fingerprint, monkeypatch, tmp_path):
    _patch_collect(monkeypatch, fake_fingerprint)
    result = runner.invoke(app, ["env", "fingerprint"])
    assert result.exit_code == 0
    assert fingerprint.stable_hash(fake_fingerprint) in result.output
    assert not (_home(tmp_path) / ".caasi" / "environment" / "fingerprint.json").exists()


def test_env_fingerprint_json(runner, fake_fingerprint, monkeypatch):
    _patch_collect(monkeypatch, fake_fingerprint)
    result = runner.invoke(app, ["env", "fingerprint", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["hash"].startswith("caasi-env-sha256:")
    assert data["saved"] is False
    assert data["environment"] == fake_fingerprint


def test_env_fingerprint_save_writes_user_store(runner, fake_fingerprint, monkeypatch, tmp_path):
    _patch_collect(monkeypatch, fake_fingerprint)
    result = runner.invoke(app, ["env", "fingerprint", "--save"])
    assert result.exit_code == 0
    store = _home(tmp_path) / ".caasi" / "environment"
    assert (store / "fingerprint.json").is_file()
    assert (store / "system.yaml").is_file()
    document = json.loads((store / "fingerprint.json").read_text(encoding="utf-8"))
    assert document["hash"] == fingerprint.stable_hash(fake_fingerprint)


def test_env_fingerprint_save_prefers_project_store(runner, fake_fingerprint, monkeypatch, tmp_path):
    _patch_collect(monkeypatch, fake_fingerprint)
    root = projects.create_project(tmp_path / "proj", name="demo")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["env", "fingerprint", "--save"])
    assert result.exit_code == 0
    assert (root / ".caasi" / "environment" / "fingerprint.json").is_file()
    # nothing leaked into the user store
    assert not (_home(tmp_path) / ".caasi" / "environment").exists()


# -- env show -----------------------------------------------------------------------

def test_env_show_without_stored_fails(runner, tmp_path):
    result = runner.invoke(app, ["env", "show"])
    assert result.exit_code == 1
    assert "No stored fingerprint" in all_output(result)


def test_env_show_prints_stored(runner, fake_fingerprint, monkeypatch, tmp_path):
    _patch_collect(monkeypatch, fake_fingerprint)
    runner.invoke(app, ["env", "fingerprint", "--save"])
    result = runner.invoke(app, ["env", "show"])
    assert result.exit_code == 0
    assert fingerprint.stable_hash(fake_fingerprint) in result.output
    assert "Stored fingerprint" in result.output


def test_env_show_json(runner, fake_fingerprint, monkeypatch):
    _patch_collect(monkeypatch, fake_fingerprint)
    runner.invoke(app, ["env", "fingerprint", "--save"])
    result = runner.invoke(app, ["env", "show", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["hash"] == fingerprint.stable_hash(fake_fingerprint)
    assert data["environment"]["system"]["os"] == "Ubuntu 24.04.3 LTS"
    assert data["path"].endswith("fingerprint.json")


# -- env compare -----------------------------------------------------------------------

def test_env_compare_stored_vs_current(runner, fake_fingerprint, monkeypatch):
    _patch_collect(monkeypatch, fake_fingerprint)
    runner.invoke(app, ["env", "fingerprint", "--save"])

    changed = copy.deepcopy(fake_fingerprint)
    changed["python"]["version"] = "3.11.9"
    _patch_collect(monkeypatch, changed)

    result = runner.invoke(app, ["env", "compare", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["left"]["label"] == "stored"
    assert data["right"]["label"] == "current"
    assert data["count"] == 1
    diff = data["differences"][0]
    assert (diff["component"], diff["key"]) == ("python", "version")
    assert (diff["left"], diff["right"]) == ("3.12.3", "3.11.9")


def test_env_compare_no_differences(runner, fake_fingerprint, monkeypatch):
    _patch_collect(monkeypatch, fake_fingerprint)
    runner.invoke(app, ["env", "fingerprint", "--save"])
    result = runner.invoke(app, ["env", "compare"])
    assert result.exit_code == 0
    assert "No meaningful differences" in result.output


def test_env_compare_ignores_volatile(runner, fake_fingerprint, monkeypatch):
    _patch_collect(monkeypatch, fake_fingerprint)
    runner.invoke(app, ["env", "fingerprint", "--save"])
    noisy = copy.deepcopy(fake_fingerprint)
    noisy["hardware"]["memory_available_kib"] = 12345
    _patch_collect(monkeypatch, noisy)
    result = runner.invoke(app, ["env", "compare"])
    assert result.exit_code == 0
    assert "No meaningful differences" in result.output


def test_env_compare_two_stored_paths(runner, fake_fingerprint, tmp_path):
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    fingerprint.write(left_root, fake_fingerprint)
    changed = copy.deepcopy(fake_fingerprint)
    changed["drivers"]["cuda"] = "12.4"
    fingerprint.write(right_root, changed)

    left_path = fingerprint.environment_dir(left_root) / fingerprint.FINGERPRINT_FILE
    right_path = fingerprint.environment_dir(right_root) / fingerprint.FINGERPRINT_FILE
    result = runner.invoke(app, ["env", "compare", str(left_path), str(right_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["count"] == 1
    assert data["differences"][0]["component"] == "drivers"


def test_env_compare_directory_argument(runner, fake_fingerprint, tmp_path, monkeypatch):
    fingerprint.write(tmp_path / "store", fake_fingerprint)
    _patch_collect(monkeypatch, fake_fingerprint)
    result = runner.invoke(app, ["env", "compare", str(tmp_path / "store")])
    assert result.exit_code == 0
    assert "No meaningful differences" in result.output


def test_env_compare_missing_path_fails(runner, tmp_path):
    result = runner.invoke(app, ["env", "compare", str(tmp_path / "nope.json")])
    assert result.exit_code == 1
    assert "No fingerprint found" in all_output(result)


def test_env_compare_without_stored_fails(runner):
    result = runner.invoke(app, ["env", "compare"])
    assert result.exit_code == 1
    assert "No stored fingerprint" in all_output(result)


# -- env lock -------------------------------------------------------------------


def _fake_versions(monkeypatch, versions=None):
    """Deterministic detection so `env lock` never probes the real machine."""
    table = {"python": "3.12.3", "ros2": "jazzy"} if versions is None else versions
    monkeypatch.setattr(check, "detect", lambda config, name: table.get(name))


def test_env_lock_outside_project_fails(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["env", "lock"])
    assert result.exit_code == 1
    assert "Not inside a Caasi project" in all_output(result)


def test_env_lock_writes_lock_file(runner, tmp_path, monkeypatch):
    _fake_versions(monkeypatch)
    root = projects.create_project(tmp_path / "proj", name="demo")
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["env", "lock"])
    assert result.exit_code == 0, all_output(result)
    assert (root / "caasi.lock").is_file()
    assert "Wrote" in result.output
    assert "resolved version(s) recorded" in result.output

    document = lock.read(root)
    assert document["project"] == {"name": "demo", "version": "0.0.0"}
    assert document["resolved"] == {"python": "3.12.3", "ros2": "jazzy"}


def test_env_lock_json(runner, tmp_path, monkeypatch):
    _fake_versions(monkeypatch)
    root = projects.create_project(tmp_path / "proj", name="demo")
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["env", "lock", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["schema"] == 1
    assert data["path"].endswith("caasi.lock")
    assert data["project"]["name"] == "demo"
    assert data["resolved"]["python"] == "3.12.3"


def test_env_lock_records_requirements_without_freezing_them(runner, tmp_path, monkeypatch):
    _fake_versions(monkeypatch)
    root = projects.create_project(tmp_path / "proj", name="demo")
    manifest = manifests.read(root)
    manifest.requires = {"isaac_sim": ">=5.0"}
    manifests.write(root, manifest)
    monkeypatch.chdir(root)

    assert runner.invoke(app, ["env", "lock"]).exit_code == 0
    document = lock.read(root)
    # the requirement is copied verbatim; nothing that was not detected is claimed
    assert document["required"] == {"isaac_sim": ">=5.0"}
    assert "isaac_sim" not in document["resolved"]


def test_env_lock_uses_the_project_root_from_a_subdirectory(runner, tmp_path, monkeypatch):
    _fake_versions(monkeypatch)
    root = projects.create_project(tmp_path / "proj", name="demo")
    nested = root / "experiments" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert runner.invoke(app, ["env", "lock"]).exit_code == 0
    assert (root / "caasi.lock").is_file()
    assert not (nested / "caasi.lock").exists()

