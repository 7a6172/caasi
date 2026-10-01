"""Tests for the §4.7 run provenance bundle (core/provenance.py)."""

from __future__ import annotations

import json
import time

import pytest
import yaml

from caasi import __version__, state
from caasi.cli import run_cmd
from caasi.core import lock, provenance, runs
from caasi.utils import shell

FINISHED = (runs.TERMINAL_OK, runs.TERMINAL_FAIL)

needs_git = pytest.mark.skipif(shell.which("git") is None, reason="git not installed")


def _wait_finished(record, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runs.effective_status(record) in FINISHED:
            return
        time.sleep(0.05)


def _started_run(tmp_path, name: str = "prov", extra: dict | None = None):
    record = run_cmd.start_with_provenance(
        state.cfg(),
        name=name,
        command=["bash", "-c", "echo prov-work"],
        cwd=tmp_path,
        backend="python",
        kind="test",
        extra=extra,
    )
    _wait_finished(record)
    return record


# -- redaction -------------------------------------------------------------


def test_is_secret_key():
    assert provenance.is_secret_key("client_SECRET")
    assert provenance.is_secret_key("hf_token")
    assert provenance.is_secret_key("api_key")
    assert not provenance.is_secret_key("username")
    assert not provenance.is_secret_key("backend")


def test_redact_secrets_recursive():
    data = {
        "nested": {"api_key": "abc", "keep": "yes"},
        "list": [{"password": "p"}, {"ok": 1}],
        "HF_TOKEN": "t",
        "plain": "value",
    }
    redacted = provenance.redact_secrets(data)
    assert redacted == {
        "nested": {"api_key": provenance.REDACTED, "keep": "yes"},
        "list": [{"password": provenance.REDACTED}, {"ok": 1}],
        "HF_TOKEN": provenance.REDACTED,
        "plain": "value",
    }


# -- git info --------------------------------------------------------------


def test_git_info_without_git(monkeypatch, tmp_path):
    monkeypatch.setattr(provenance.shell, "which", lambda _name: None)
    assert provenance.git_info(tmp_path) == {"available": False}


@needs_git
def test_git_info_not_a_repo(tmp_path):
    assert provenance.git_info(tmp_path) == {"available": False}


@needs_git
def test_git_info_in_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str):
        return shell.run_cmd(["git", "-C", str(repo), *args], timeout=15.0)

    git("init", "-q")
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    git("add", "f.txt")
    git(
        "-c", "user.email=test@example.com",
        "-c", "user.name=Test",
        "commit", "-q", "-m", "init",
    )

    info = provenance.git_info(repo)
    assert info["available"] is True
    assert info["branch"]
    assert len(info["head"]) == 40
    assert info["dirty"] is False
    assert info["remotes"] == {}

    (repo / "f.txt").write_text("y\n", encoding="utf-8")
    assert provenance.git_info(repo)["dirty"] is True


# -- process snapshot ------------------------------------------------------


def test_process_snapshot_shape():
    snapshot = provenance.process_snapshot(5)
    assert snapshot["available"] in (True, False)
    if snapshot["available"]:
        assert len(snapshot["processes"]) <= 5
        assert {"pid", "rss_kb", "command"} <= set(snapshot["processes"][0])


# -- bundle ----------------------------------------------------------------


def test_write_bundle_creates_all_files(tmp_path):
    record = _started_run(tmp_path)
    for filename in provenance.BUNDLE_FILES:
        assert (record.directory / filename).is_file(), filename


def test_bundle_manifest_enriched_without_project(tmp_path):
    record = _started_run(tmp_path)
    data = yaml.safe_load((record.directory / "manifest.yaml").read_text(encoding="utf-8"))
    assert data["caasi"] == {"version": __version__}
    assert "project" not in data
    assert data["id"] == record.run_id


def test_bundle_includes_project_identity(tmp_path):
    (tmp_path / "caasi.yaml").write_text(
        yaml.safe_dump({"schema": 1, "name": "demo-proj", "version": "9.9.9"}),
        encoding="utf-8",
    )
    record = _started_run(tmp_path)
    manifest = yaml.safe_load((record.directory / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["project"] == {"name": "demo-proj", "version": "9.9.9"}

    deps = yaml.safe_load((record.directory / "dependencies.yaml").read_text(encoding="utf-8"))
    assert deps["schema"] == lock.SCHEMA
    assert deps["project"] == {"name": "demo-proj", "version": "9.9.9"}
    assert "collected_at" in deps
    assert isinstance(deps["resolved"], dict)


def test_bundle_splits_environment_and_hardware(tmp_path):
    record = _started_run(tmp_path)
    env_doc = yaml.safe_load((record.directory / "environment.yaml").read_text(encoding="utf-8"))
    hw_doc = yaml.safe_load((record.directory / "hardware.yaml").read_text(encoding="utf-8"))
    assert "collected_at" in env_doc
    assert "system" in env_doc
    assert "hardware" not in env_doc
    assert "collected_at" in hw_doc
    assert "cpu_count" in hw_doc


def test_bundle_configuration_redacts_experiment_secrets(tmp_path):
    experiment_file = tmp_path / "experiment.yaml"
    experiment_file.write_text(
        "name: secret-demo\nbackend: python\nscript: main.py\ntoken: super-secret\n",
        encoding="utf-8",
    )
    record = _started_run(tmp_path, extra={"experiment": str(experiment_file)})
    path = record.directory / "configuration.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["experiment"]["token"] == provenance.REDACTED
    assert doc["experiment"]["name"] == "secret-demo"
    assert "caasi" in doc
    assert "super-secret" not in path.read_text(encoding="utf-8")


def test_bundle_git_and_processes_are_valid_json(tmp_path):
    record = _started_run(tmp_path)
    git_doc = json.loads((record.directory / "git.json").read_text(encoding="utf-8"))
    assert "available" in git_doc
    proc_doc = json.loads((record.directory / "processes.json").read_text(encoding="utf-8"))
    assert "available" in proc_doc


def test_write_bundle_skips_unwritable_files(tmp_path):
    # The run already started; a read-only run dir must not take it down (§14.13).
    record = runs.start_run(
        state.cfg(),
        name="read-only",
        command=["bash", "-c", "true"],
        cwd=tmp_path,
        backend="python",
        kind="test",
    )
    _wait_finished(record)
    record.directory.chmod(0o500)
    try:
        written = provenance.write_bundle(state.cfg(), record)
        # manifest.yaml exists and is file-writable; new files cannot be created.
        assert [path.name for path in written] == ["manifest.yaml"]
    finally:
        record.directory.chmod(0o700)
