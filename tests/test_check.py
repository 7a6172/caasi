"""Tests for the Check Contract (§4.5): `core/check.py` and root `caasi check`."""

from __future__ import annotations

import json
import platform
import types

import pytest
import yaml

import caasi.checks
from caasi import state
from caasi.checks import CheckResult
from caasi.cli.main import app
from caasi.core import check, fingerprint
from caasi.core import containers as containers_core
from caasi.core import manifest as manifests, runs
from caasi.core.config import Config

from .conftest import all_output

# -- helpers ------------------------------------------------------------------


def _project(tmp_path, *, requires=None, tested=None, components=None, name="demo"):
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    manifests.write(
        root,
        manifests.Manifest(
            name=name,
            version="0.1.0",
            components=dict(components or {}),
            requires=dict(requires or {}),
            tested=list(tested or []),
        ),
    )
    return root


def _ctx(**kwargs):
    kwargs.setdefault("config", Config.load())
    return check.CheckContext(**kwargs)


def _patch_detect(monkeypatch, versions):
    """Replace the detector table with a fixed name → version mapping."""
    monkeypatch.setattr(check, "detect", lambda config, name: versions.get(name))


def _report(scope, items, strict=False):
    return check.build_report(scope, items, strict)


# -- the ladder ---------------------------------------------------------------


def test_summarize_maps_compatibility_onto_result():
    assert check.summarize([]) == "ready"
    assert check.summarize([check.CheckItem("a", None, "1", "compatible")]) == "ready"
    assert check.summarize([check.CheckItem("a", None, "1", "untested")]) == "warning"
    assert check.summarize([check.CheckItem("a", None, None, "missing")]) == "incompatible"
    assert check.summarize([check.CheckItem("a", None, None, "incompatible")]) == "incompatible"


def test_summarize_strict_escalates_untested_only():
    compatible = check.CheckItem("a", None, "1", "compatible")
    untested = check.CheckItem("b", ">=2.0", "1.0", "untested")
    assert check.summarize([compatible, untested]) == "warning"
    assert check.summarize([compatible, untested], strict=True) == "incompatible"


def test_build_report_collects_missing_and_warnings():
    items = [
        check.CheckItem("ok", ">=1.0", "1.2", "compatible"),
        check.CheckItem("warn", ">=2.0", "1.0", "untested"),
        check.CheckItem("gone", ">=1.0", None, "missing"),
        check.CheckItem("bad", None, None, "incompatible"),
    ]
    report = _report("project", items)
    assert report.scope == "project"
    assert report.items == items
    assert report.missing == ["gone"]
    assert report.warnings == ["warn", "bad"]
    assert report.result == "incompatible"


def test_report_to_dict_is_the_json_contract():
    report = _report("sim", [check.CheckItem("x", ">=1", "1", "compatible", "note", True)])
    data = report.to_dict()
    assert set(data) == {"scope", "items", "missing", "warnings", "result"}
    assert set(data["items"][0]) == {
        "name",
        "required",
        "detected",
        "compatibility",
        "note",
        "verified",
    }
    assert data["items"][0]["verified"] is True


def test_worst_picks_the_highest_result():
    ready = _report("a", [check.CheckItem("x", None, "1", "compatible")])
    warning = _report("b", [check.CheckItem("x", None, "1", "untested")])
    bad = _report("c", [check.CheckItem("x", None, None, "missing")])
    assert check.worst([]) == "ready"
    assert check.worst([ready, warning]) == "warning"
    assert check.worst([warning, bad, ready]) == "incompatible"


def test_default_checker_scopes():
    assert [cls.scope for cls in check.DEFAULT_CHECKERS] == [
        "environment",
        "project",
        "sim",
        "container",
        "control",
        "run",
    ]


# -- engine -------------------------------------------------------------------


class _Optional:
    scope = "optional"

    def relevant(self, ctx):
        return bool(ctx.extra.get("optional"))

    def run(self, ctx):
        return [check.CheckItem("thing", ">=1.0", "2.0", "compatible")]


class _Unverified:
    scope = "unverified"

    def relevant(self, ctx):
        return True

    def run(self, ctx):
        return [check.CheckItem("thing", ">=9.0", "1.0", "untested")]


def test_engine_orchestrate_skips_irrelevant_checkers():
    engine = check.CheckEngine((_Optional, _Unverified))
    assert [r.scope for r in engine.orchestrate(_ctx())] == ["unverified"]
    assert [r.scope for r in engine.orchestrate(_ctx(extra={"optional": True}))] == [
        "optional",
        "unverified",
    ]


def test_engine_orchestrate_filters_by_scope():
    engine = check.CheckEngine((_Optional, _Unverified))
    reports = engine.orchestrate(_ctx(extra={"optional": True}), scopes=["optional"])
    assert [r.scope for r in reports] == ["optional"]


def test_engine_orchestrate_applies_strict():
    engine = check.CheckEngine((_Unverified,))
    assert engine.orchestrate(_ctx())[0].result == "warning"
    assert engine.orchestrate(_ctx(strict=True))[0].result == "incompatible"


def test_engine_one_ignores_relevance_and_strict():
    engine = check.CheckEngine((_Optional, _Unverified))
    assert engine.one("optional", _ctx()).result == "ready"
    assert engine.one("unverified", _ctx(strict=True)).result == "warning"


def test_engine_one_rejects_unknown_scope():
    with pytest.raises(check.CheckError):
        check.CheckEngine((_Optional,)).one("nope", _ctx())


# -- detection ----------------------------------------------------------------


def test_detect_python_uses_the_running_interpreter():
    assert check.detect(Config.load(), "python") == platform.python_version()


def test_detect_unknown_name_reports_presence(monkeypatch):
    monkeypatch.setattr(check.shell, "which", lambda name: "/usr/bin/thing")
    assert check.detect(Config.load(), "totally_unknown_tool") == "present"


def test_detect_absent_name_is_none(monkeypatch):
    monkeypatch.setattr(check.shell, "which", lambda name: None)
    assert check.detect(Config.load(), "totally_unknown_tool") is None


def test_detect_normalizes_name_separators(monkeypatch):
    seen = []

    def detector(config):
        seen.append("isaac_sim")
        return "6.0.1"

    monkeypatch.setitem(check._DETECTORS, "isaac_sim", detector)
    assert check.detect(Config.load(), "isaac-sim") == "6.0.1"
    assert seen == ["isaac_sim"]


def test_detect_swallows_detector_failures(monkeypatch):
    def boom(config):
        raise RuntimeError("nope")

    monkeypatch.setitem(check._DETECTORS, "gcc", boom)
    assert check.detect(Config.load(), "gcc") is None


# -- EnvironmentChecker -------------------------------------------------------


def test_environment_checker_without_fingerprint(tmp_path):
    items = check.EnvironmentChecker().run(_ctx(project_root=tmp_path))
    assert items[0].name == "fingerprint"
    assert items[0].compatibility == "untested"
    assert "no stored fingerprint" in items[0].note


def test_environment_checker_with_fingerprint(tmp_path):
    fingerprint.write(tmp_path, {"system": {"os": "Ubuntu 24.04"}})
    items = check.EnvironmentChecker().run(_ctx(project_root=tmp_path))
    assert items[0].compatibility == "compatible"
    assert items[0].detected


# -- ProjectRequirementsChecker ----------------------------------------------


def test_project_checker_satisfied_requirement_is_ready(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    _patch_detect(monkeypatch, {"isaac_sim": "6.0.1"})
    report = _report("project", check.ProjectRequirementsChecker().run(_ctx(project_root=root)))
    item = report.items[0]
    assert (item.name, item.required, item.detected) == ("isaac_sim", ">=5.0", "6.0.1")
    assert item.compatibility == "compatible"
    assert report.result == "ready"


def test_project_checker_accepts_mapping_form_requires(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": {"version": ">=5.0"}})
    _patch_detect(monkeypatch, {"isaac_sim": "6.0.1"})
    items = check.ProjectRequirementsChecker().run(_ctx(project_root=root))
    assert items[0].required == ">=5.0"
    assert items[0].compatibility == "compatible"


def test_project_checker_out_of_range_warns_with_a_note(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    _patch_detect(monkeypatch, {"isaac_sim": "4.5"})
    report = _report("project", check.ProjectRequirementsChecker().run(_ctx(project_root=root)))
    item = report.items[0]
    assert item.compatibility == "untested"
    assert "outside required '>=5.0'" in item.note
    assert report.result == "warning"
    assert report.warnings == ["isaac_sim"]


def test_project_checker_undetectable_requirement_is_missing(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    _patch_detect(monkeypatch, {})
    report = _report("project", check.ProjectRequirementsChecker().run(_ctx(project_root=root)))
    assert report.items[0].compatibility == "missing"
    assert report.missing == ["isaac_sim"]
    assert report.result == "incompatible"


def test_project_checker_uncomparable_version_warns(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"ros2": ">=1.0"})
    _patch_detect(monkeypatch, {"ros2": "jazzy"})
    item = check.ProjectRequirementsChecker().run(_ctx(project_root=root))[0]
    assert item.compatibility == "untested"
    assert "cannot compare" in item.note


def test_project_checker_without_specifier_is_untested(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"docker": None})
    _patch_detect(monkeypatch, {"docker": "27.1.1"})
    item = check.ProjectRequirementsChecker().run(_ctx(project_root=root))[0]
    assert item.required is None
    assert item.compatibility == "untested"
    assert "no version requirement" in item.note


def test_project_checker_marks_verified_entries(tmp_path, monkeypatch):
    root = _project(
        tmp_path,
        requires={"isaac_sim": ">=5.0"},
        tested=[{"component": "isaac_sim", "version": "6.0.1", "status": "verified"}],
    )
    _patch_detect(monkeypatch, {"isaac_sim": "6.0.1"})
    item = check.ProjectRequirementsChecker().run(_ctx(project_root=root))[0]
    assert item.verified is True
    assert item.compatibility == "compatible"
    assert "tested and verified" in item.note


def test_project_checker_verified_needs_matching_version(tmp_path, monkeypatch):
    root = _project(
        tmp_path,
        requires={"isaac_sim": ">=5.0"},
        tested=[{"component": "isaac_sim", "version": "5.0.0", "status": "verified"}],
    )
    _patch_detect(monkeypatch, {"isaac_sim": "6.0.1"})
    assert check.ProjectRequirementsChecker().run(_ctx(project_root=root))[0].verified is False


def test_project_checker_lists_registered_components(tmp_path, monkeypatch):
    root = _project(tmp_path, components={"nav2": True})
    _patch_detect(monkeypatch, {"nav2": "/opt/ros/jazzy"})
    report = _report("project", check.ProjectRequirementsChecker().run(_ctx(project_root=root)))
    assert [i.name for i in report.items] == ["nav2"]
    assert report.items[0].compatibility == "untested"
    assert "no requirements recorded" in report.items[0].note


def test_project_checker_irrelevant_without_a_root():
    assert check.ProjectRequirementsChecker().relevant(_ctx()) is False
    assert check.ProjectRequirementsChecker().relevant(_ctx(project_root=None)) is False


# -- SimChecker ---------------------------------------------------------------


def test_sim_checker_irrelevant_without_isaac(tmp_path):
    checker = check.SimChecker()
    assert checker.relevant(_ctx()) is False
    assert checker.relevant(_ctx(project_root=_project(tmp_path, components={"nav2": True}))) is False
    assert (
        checker.relevant(_ctx(project_root=_project(tmp_path, components={"isaac_lab": True})))
        is True
    )


def test_sim_checker_delegates_to_doctor_sections(tmp_path, monkeypatch):
    root = _project(tmp_path, components={"isaac_sim": True})
    seen = {}

    def fake_run_checks(sections, config):
        seen["sections"] = sections
        return [
            CheckResult("isaac", "Isaac Sim", "ok", "/opt/isaacsim"),
            CheckResult("storage", "Disk", "warn", "10 GiB free", "free more space"),
            CheckResult("nvidia", "Driver", "fail", "", "install an NVIDIA driver"),
        ]

    monkeypatch.setattr(caasi.checks, "run_checks", fake_run_checks)
    items = check.SimChecker().run(_ctx(project_root=root))
    assert seen["sections"] == ["isaac", "nvidia", "hardware", "storage"]
    assert [i.name for i in items] == ["Isaac Sim", "Disk", "Driver"]
    assert [i.compatibility for i in items] == ["compatible", "untested", "incompatible"]
    assert items[1].note == "free more space"
    assert items[1].detected == "10 GiB free"
    assert _report("sim", items).result == "incompatible"


def test_sim_checker_unknown_status_degrades_to_untested(tmp_path, monkeypatch):
    root = _project(tmp_path, components={"isaac_sim": True})
    monkeypatch.setattr(
        caasi.checks, "run_checks", lambda sections, config: [CheckResult("isaac", "X", "skip")]
    )
    items = check.SimChecker().run(_ctx(project_root=root))
    assert items[0].compatibility == "untested"
    assert items[0].detected is None


# -- ContainerChecker ---------------------------------------------------------


def _fake_containers(monkeypatch, tool="/usr/bin/docker", daemon=True, gpu=True):
    calls = []
    monkeypatch.setattr(containers_core, "find_container_tool", lambda: tool)
    monkeypatch.setattr(
        containers_core, "daemon_ok", lambda name: calls.append("daemon") or daemon
    )
    monkeypatch.setattr(
        containers_core, "nvidia_runtime", lambda name: calls.append("gpu") or gpu
    )
    return calls


def test_container_checker_relevant_only_when_asked():
    checker = check.ContainerChecker()
    assert checker.relevant(_ctx()) is False
    assert checker.relevant(_ctx(extra={"containers": True})) is True


def test_container_checker_all_green(monkeypatch):
    _fake_containers(monkeypatch)
    items = check.ContainerChecker().run(_ctx(extra={"containers": True}))
    assert [i.name for i in items] == ["tool", "daemon", "nvidia-runtime"]
    assert [i.compatibility for i in items] == ["compatible"] * 3
    assert items[0].detected == "docker"
    assert _report("container", items).result == "ready"


def test_container_checker_without_tool(monkeypatch):
    calls = _fake_containers(monkeypatch, tool=None)
    items = check.ContainerChecker().run(_ctx(extra={"containers": True}))
    assert [i.compatibility for i in items] == ["missing"] * 3
    assert calls == []  # never probes a tool that is not there
    assert _report("container", items).result == "incompatible"


def test_container_checker_daemon_down(monkeypatch):
    calls = _fake_containers(monkeypatch, daemon=False)
    items = check.ContainerChecker().run(_ctx(extra={"containers": True}))
    assert [i.compatibility for i in items] == ["compatible", "incompatible", "missing"]
    assert calls == ["daemon"]  # GPU probe skipped once the daemon is down
    assert _report("container", items).result == "incompatible"


def test_container_checker_without_gpu_runtime(monkeypatch):
    _fake_containers(monkeypatch, gpu=False)
    items = check.ContainerChecker().run(_ctx(extra={"containers": True}))
    assert [i.compatibility for i in items] == ["compatible", "compatible", "incompatible"]
    assert _report("container", items).result == "incompatible"


# -- ControlChecker -----------------------------------------------------------

GOOD_PARAMS = {
    "controller_manager": {
        "ros__parameters": {
            "update_rate": 100,
            "diff_drive_controller": {"type": "diff_drive_controller/DiffDriveController"},
        }
    }
}


def test_control_checker_relevant_only_with_params():
    checker = check.ControlChecker()
    assert checker.relevant(_ctx()) is False
    assert checker.relevant(_ctx(extra={"params": {}})) is True


def test_control_checker_accepts_good_params():
    items = check.ControlChecker().run(_ctx(extra={"params": GOOD_PARAMS}))
    assert [i.name for i in items] == ["controller_manager", "diff_drive_controller"]
    assert [i.compatibility for i in items] == ["compatible"] * 2
    assert items[0].detected == "update_rate=100"
    assert items[1].detected == "diff_drive_controller/DiffDriveController"


def test_control_checker_rejects_non_mapping():
    items = check.ControlChecker().run(_ctx(extra={"params": ["nope"]}))
    assert len(items) == 1
    assert items[0].compatibility == "incompatible"


def test_control_checker_requires_controller_manager():
    items = check.ControlChecker().run(_ctx(extra={"params": {"other": {}}}))
    assert [i.name for i in items] == ["controller_manager"]
    assert items[0].compatibility == "incompatible"


def test_control_checker_flags_missing_update_rate_and_type():
    params = {"controller_manager": {"ros__parameters": {"broken": {"nope": 1}}}}
    items = check.ControlChecker().run(_ctx(extra={"params": params}))
    assert [i.compatibility for i in items] == ["incompatible", "incompatible"]
    assert "update_rate" in items[0].note
    assert "broken" in items[1].note


# -- RunChecker ---------------------------------------------------------------


def _script(tmp_path, name="demo.sh"):
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _run(command, cwd, extra=None):
    return types.SimpleNamespace(command=command, cwd=cwd, extra=extra or {})


def test_run_checker_relevant_only_with_a_run():
    checker = check.RunChecker()
    assert checker.relevant(_ctx()) is False
    assert checker.relevant(_ctx(run=_run([], ""))) is True


def test_run_checker_happy_path(tmp_path):
    script = _script(tmp_path)
    items = check.RunChecker().run(_ctx(run=_run([str(script)], str(tmp_path))))
    assert [i.name for i in items] == ["command", "cwd"]
    assert [i.compatibility for i in items] == ["compatible"] * 2
    assert items[0].detected == str(script)


def test_run_checker_without_command(tmp_path):
    items = check.RunChecker().run(_ctx(run=_run([], str(tmp_path))))
    assert items[0].name == "command"
    assert items[0].compatibility == "missing"
    assert "no recorded command" in items[0].note


def test_run_checker_reports_absent_command_and_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(check.shell, "which", lambda name: None)
    items = check.RunChecker().run(_ctx(run=_run(["nope"], str(tmp_path / "gone"))))
    assert [i.compatibility for i in items] == ["missing", "missing"]
    assert _report("run", items).result == "incompatible"


def test_run_checker_checks_experiment_file(tmp_path):
    script = _script(tmp_path)
    experiment = tmp_path / "experiment.yaml"
    experiment.write_text("kind: task\n", encoding="utf-8")
    ctx = _ctx(run=_run([str(script)], str(tmp_path), {"experiment": str(experiment)}))
    items = check.RunChecker().run(ctx)
    assert [i.name for i in items] == ["command", "cwd", "experiment"]
    assert items[2].compatibility == "compatible"

    missing = _ctx(run=_run([str(script)], str(tmp_path), {"experiment": str(tmp_path / "x")}))
    assert check.RunChecker().run(missing)[2].compatibility == "missing"


# -- CLI: caasi check ---------------------------------------------------------


def test_check_is_registered_at_the_root(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.output


def test_check_outside_a_project_fails(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "Not inside a Caasi project" in all_output(result)


def test_check_rejects_unknown_scope(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["check", "sim"])
    assert result.exit_code == 1
    out = all_output(result)
    assert "Unknown check scope 'sim'" in out
    assert "project, run" in out


def test_check_project_json(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    _patch_detect(monkeypatch, {"isaac_sim": "6.0.1"})
    fingerprint.write(root, {"system": {"os": "Ubuntu 24.04"}})
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["check", "project", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["scope"] == "project"
    assert data["result"] == "ready"
    assert data["missing"] == []
    assert data["warnings"] == []
    assert [r["scope"] for r in data["reports"]] == ["environment", "project"]
    assert data["reports"][1]["items"][0]["detected"] == "6.0.1"


def test_check_default_scope_is_project(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"python": ">=3.0"})
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["check", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["scope"] == "project"
    assert [r["scope"] for r in data["reports"]] == ["environment", "project"]
    item = data["reports"][1]["items"][0]
    assert item["name"] == "python"
    assert item["detected"] == platform.python_version()
    assert item["compatibility"] == "compatible"


def test_check_human_output_uses_ladder_labels(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"python": ">=3.0"})
    fingerprint.write(root, {"system": {"os": "Ubuntu 24.04"}})
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["check", "project"])
    assert result.exit_code == 0
    out = result.output
    assert "Compatibility Check" in out
    assert "COMPATIBLE" in out
    assert "Result: READY" in out


def test_check_warning_exit_code_is_zero(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    _patch_detect(monkeypatch, {"isaac_sim": "4.5"})
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["check", "project"])
    assert result.exit_code == 0
    assert "UNVERIFIED" in result.output
    assert "outside required '>=5.0'" in result.output
    assert "Result: WARNING" in result.output


def test_check_missing_component_exits_3(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"totally_absent_tool": ">=1.0"})
    _patch_detect(monkeypatch, {})
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["check", "--json"])
    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["result"] == "incompatible"
    assert data["missing"] == ["totally_absent_tool"]
    # "missing" is its own bucket; the only warning is the absent fingerprint
    assert data["warnings"] == ["fingerprint"]


def test_check_strict_escalates_warnings(runner, tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    _patch_detect(monkeypatch, {"isaac_sim": "4.5"})
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["check", "project", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["result"] == "warning"

    cfg_file = tmp_path / "strict.yaml"
    cfg_file.write_text(yaml.safe_dump({"check": {"strict": True}}), encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    state.reset()

    result = runner.invoke(app, ["check", "project", "--json"])
    assert result.exit_code == 3
    assert json.loads(result.output)["result"] == "incompatible"


def test_check_run_preflights_a_stored_run(runner, tmp_path, monkeypatch):
    cfg_file = tmp_path / "caasi-runs.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"paths": {"runs": str(tmp_path / "runs")}}), encoding="utf-8"
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    state.reset()

    script = _script(tmp_path)
    runs.start_run(state.cfg(), name="demo", command=[str(script)], cwd=str(tmp_path))

    result = runner.invoke(app, ["check", "run", "demo", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["scope"] == "run"
    assert [r["scope"] for r in data["reports"]] == ["run"]
    assert [i["name"] for i in data["reports"][0]["items"]] == ["command", "cwd"]
    assert data["result"] == "ready"


def test_check_run_defaults_to_latest(runner, tmp_path, monkeypatch):
    cfg_file = tmp_path / "caasi-runs.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"paths": {"runs": str(tmp_path / "runs")}}), encoding="utf-8"
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    state.reset()
    runs.start_run(state.cfg(), name="demo", command=[str(_script(tmp_path))], cwd=str(tmp_path))

    result = runner.invoke(app, ["check", "run", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.output)["scope"] == "run"


def test_check_run_unknown_id_fails(runner):
    result = runner.invoke(app, ["check", "run", "nope"])
    assert result.exit_code == 1
    assert "No run found for 'nope'" in all_output(result)


def test_check_run_exits_3_for_a_broken_run(runner, tmp_path, monkeypatch):
    cfg_file = tmp_path / "caasi-runs.yaml"
    cfg_file.write_text(
        yaml.safe_dump({"paths": {"runs": str(tmp_path / "runs")}}), encoding="utf-8"
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    state.reset()

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    record = runs.start_run(
        state.cfg(), name="broken", command=["no-such-binary"], cwd=str(workdir)
    )
    workdir.rmdir()  # both the command and its cwd are gone now

    result = runner.invoke(app, ["check", "run", record.run_id, "--json"])
    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["result"] == "incompatible"
    assert sorted(data["missing"]) == ["command", "cwd"]
