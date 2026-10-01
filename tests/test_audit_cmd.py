"""Tests for the Layer 8 audit verb (§24-26): root ``caasi audit``.

Covers each scope, the default (all scopes), the §26 safe-fix contract
(``--fix`` creates a missing CAASI directory but never touches a user file),
the ``audit.fix`` config key (§7.3, absent by default) and the JSON envelope.
No test needs a GPU, Isaac, ROS or a real run: run records are fabricated and
GPU detection is pinned with ``no_nvidia_smi``.
"""

from __future__ import annotations

import json
import platform
import shutil

import yaml

from caasi import state
from caasi.cli import audit_cmd
from caasi.cli.main import app
from caasi.core import check, runs
from caasi.core import manifest as manifests
from caasi.core import project as projects

from .conftest import all_output

# -- helpers ------------------------------------------------------------------


def _project(tmp_path, *, name="demo", components=None, requires=None):
    """A full project scaffold (base dirs + flat manifest)."""
    root = tmp_path / "proj"
    projects.create_project(root, name=name)
    if components or requires:
        manifest = manifests.read(root)
        if components:
            manifest.components.update(components)
        if requires:
            manifest.requires.update(requires)
        manifests.write(root, manifest)
    return root


def _fabricate_run(run_id, *, name="demo", stdout="", manifest=True):
    """Create a run record directly in the run store (no subprocess)."""
    base = runs.runs_dir(state.cfg())
    run_dir = base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if manifest:
        (run_dir / "manifest.yaml").write_text(
            yaml.safe_dump(
                {
                    "id": run_id,
                    "name": name,
                    "backend": "python",
                    "kind": "run",
                    "command": ["echo", "hi"],
                    "cwd": str(run_dir),
                    "created": "2026-01-01T00:00:00+00:00",
                    "pid": None,
                    "paused": False,
                    "stopped": True,
                    "extra": {},
                }
            ),
            encoding="utf-8",
        )
    if stdout:
        (run_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    return run_dir


def _findings(data, scope_index=0):
    return data["groups"][scope_index]["findings"]


def _messages(data, scope_index=0):
    return [f["message"] for f in _findings(data, scope_index)]


# -- registration & guards ----------------------------------------------------


def test_audit_is_registered_at_the_root(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "audit" in result.output


def test_audit_outside_a_project_fails(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["audit"])
    assert result.exit_code == 1
    assert "Not inside a Caasi project" in all_output(result)


def test_audit_rejects_unknown_scope(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "bogus"])
    assert result.exit_code == 1
    out = all_output(result)
    assert "Unknown audit scope 'bogus'" in out
    assert "reproducibility" in out


# -- scope selection ----------------------------------------------------------


def test_audit_default_covers_all_scopes(runner, tmp_path, monkeypatch, no_nvidia_smi):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["scope"] == "all"
    assert [g["scope"] for g in data["groups"]] == list(audit_cmd.SCOPES)
    assert data["errors"] == 0  # a clean scaffold only accrues warnings


def test_audit_single_scope_json(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "project", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["scope"] == "project"
    assert [g["scope"] for g in data["groups"]] == ["project"]


def test_audit_human_output_matches_the_report(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "project"])
    assert result.exit_code == 0, all_output(result)
    out = result.output
    assert "CAASI Audit" in out
    assert "PROJECT" in out
    assert "Valid caasi.yaml" in out
    assert "Result:" in out


# -- project scope ------------------------------------------------------------


def test_audit_project_flags_broken_manifest(runner, tmp_path, monkeypatch):
    root = _project(tmp_path)
    (root / "caasi.yaml").write_text("schema: 99\n", encoding="utf-8")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "project", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["result"] == "error"
    assert any(f["severity"] == "error" for f in _findings(data))


# -- dependencies scope -------------------------------------------------------


def test_audit_dependencies_present_is_ok(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"python": ">=3.0"})
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "dependencies", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["errors"] == 0
    assert _findings(data)[0]["severity"] == "ok"
    assert platform.python_version() in _findings(data)[0]["message"]


def test_audit_dependencies_missing_is_error(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    monkeypatch.setattr(check, "detect", lambda config, name: None)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "dependencies", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["result"] == "error"
    assert data["errors"] == 1
    assert _findings(data)[0]["severity"] == "error"


def test_audit_dependencies_none_declared(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "dependencies", "--json"])
    assert result.exit_code == 0
    assert _messages(json.loads(result.output)) == ["No dependencies declared"]


# -- environment scope --------------------------------------------------------


def test_audit_environment_degrades_without_gpu(runner, tmp_path, monkeypatch, no_nvidia_smi):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "environment", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["errors"] == 0
    assert data["result"] == "warning"
    assert data["warnings"] == 3  # no fingerprint, no GPU, no CUDA
    assert "No GPU detected" in _messages(data)


# -- files scope & the §26 safe-fix contract ---------------------------------


def test_audit_files_flags_missing_dir_as_fixable(runner, tmp_path, monkeypatch):
    root = _project(tmp_path)
    shutil.rmtree(root / "artifacts")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "files", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert any(f.get("fix") == "dir:artifacts" for f in _findings(data))


def test_audit_fix_creates_missing_caasi_dir(runner, tmp_path, monkeypatch):
    root = _project(tmp_path)
    shutil.rmtree(root / "artifacts")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "files", "--fix", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert (root / "artifacts").is_dir()
    data = json.loads(result.output)
    assert data["fixed"] == ["artifacts"]
    assert all(f["severity"] == "ok" for f in _findings(data))


def test_audit_fix_never_touches_user_files(runner, tmp_path, monkeypatch, no_nvidia_smi):
    root = _project(tmp_path)
    projects.save_definition(root, "robot", "demo", description="mine")
    user_def = root / "robots" / "demo.yaml"
    notes = root / "notes.txt"
    notes.write_text("keep me", encoding="utf-8")
    before = user_def.read_text(encoding="utf-8")
    shutil.rmtree(root / "logs")  # a CAASI-owned base dir

    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "--fix"])
    assert result.exit_code == 0, all_output(result)
    assert (root / "logs").is_dir()  # recreated
    assert user_def.read_text(encoding="utf-8") == before  # untouched
    assert notes.read_text(encoding="utf-8") == "keep me"  # untouched


def test_audit_fix_is_absent_by_default(runner, tmp_path, monkeypatch):
    root = _project(tmp_path)
    shutil.rmtree(root / "datasets")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "files"])
    assert result.exit_code == 0
    assert not (root / "datasets").exists()  # reported, not fixed


def test_audit_fix_config_key_enables_fix(runner, tmp_path, monkeypatch):
    root = _project(tmp_path)
    shutil.rmtree(root / "datasets")
    cfg_file = tmp_path / "audit.yaml"
    cfg_file.write_text(yaml.safe_dump({"audit": {"fix": True}}), encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    state.reset()
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "files"])
    assert result.exit_code == 0, all_output(result)
    assert (root / "datasets").is_dir()


# -- runs scope ---------------------------------------------------------------


def test_audit_runs_none(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "runs", "--json"])
    assert result.exit_code == 0
    assert _messages(json.loads(result.output)) == ["No runs recorded"]


def test_audit_runs_logs_and_metrics(runner, tmp_path, monkeypatch):
    root = _project(tmp_path)
    _fabricate_run("20260101-000000-demo", stdout="caasi_metric steps_per_sec=100.0\n")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "runs", "--json"])
    assert result.exit_code == 0, all_output(result)
    messages = _messages(json.loads(result.output))
    assert "Logs available" in messages
    assert "Metrics available" in messages


def test_audit_runs_orphaned_directory(runner, tmp_path, monkeypatch):
    root = _project(tmp_path)
    _fabricate_run("20260101-000000-broken", manifest=False)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["audit", "runs", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert any("stale record" in m for m in _messages(data))
    assert data["warnings"] == 1


# -- reproducibility scope (§15 verification) --------------------------------


def test_audit_reproducibility_json(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["audit", "reproducibility", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["scope"] == "reproducibility"
    assert data["errors"] == 0
    messages = _messages(data)
    assert "No environment fingerprint recorded" in messages
    assert any("caasi.lock" in m for m in messages)
