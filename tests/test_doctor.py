"""Tests for `caasi doctor`."""

from __future__ import annotations

import json

from caasi.checks import SECTION_KEYS, CheckResult
from caasi.cli import doctor as doctor_cmd
from caasi.cli.main import app
from caasi.i18n.en import MESSAGES

from .conftest import all_output


def test_doctor_runs(runner):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code in (0, 1)
    assert "Environment Diagnostics" in all_output(result)


def test_doctor_component_system(runner):
    result = runner.invoke(app, ["doctor", "--component", "system"])
    assert result.exit_code == 0
    assert "Kernel" in all_output(result)


def test_doctor_component_nvidia_with_fake(runner, fake_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--component", "nvidia", "--verbose"])
    assert result.exit_code == 0
    output = all_output(result)
    assert "FakeGPU RTX 9090" in output
    assert "CUDA" in output


def test_doctor_component_nvidia_without_gpu(runner, no_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--component", "nvidia"])
    assert result.exit_code == 1
    assert "nvidia-smi" in all_output(result)


def test_doctor_json(runner):
    result = runner.invoke(app, ["doctor", "--component", "system", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["checks"], "expected at least one check"
    assert data["exit_code"] == 0
    assert all(check["section"] == "system" for check in data["checks"])


def test_doctor_quiet(runner):
    result = runner.invoke(app, ["doctor", "--component", "system", "--quiet"])
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_doctor_unknown_component(runner):
    result = runner.invoke(app, ["doctor", "--component", "bogus"])
    assert result.exit_code == 1
    assert "Unknown component" in all_output(result)


def test_section_keys_cover_registry():
    """Every registered section must have a stable key for --component."""
    assert "nvidia" in SECTION_KEYS
    assert len(SECTION_KEYS) == len(set(SECTION_KEYS))


def test_section_keys_include_the_ecosystem_sections():
    for key in ("accelerated", "physics", "assets", "data", "platform"):
        assert key in SECTION_KEYS
    assert len(SECTION_KEYS) == 19


def test_section_keys_include_project():
    assert "project" in SECTION_KEYS
    # inserted right after `robotics`
    assert SECTION_KEYS.index("project") == SECTION_KEYS.index("robotics") + 1


def test_doctor_project_section_skips_outside_project(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor", "--component", "project", "--json"])
    assert result.exit_code == 0
    checks = json.loads(result.output)["checks"]
    assert checks and checks[0]["status"] == "skip"


def test_doctor_project_section_reports_manifest(runner, tmp_path, monkeypatch):
    target = tmp_path / "proj"
    runner.invoke(app, ["init", str(target), "--name", "demo"])
    monkeypatch.chdir(target)
    result = runner.invoke(app, ["doctor", "--component", "project", "--json"])
    assert result.exit_code == 0
    statuses = {c["name"]: c["status"] for c in json.loads(result.output)["checks"]}
    assert statuses["Manifest schema"] == "ok"
    assert statuses["Project name"] == "ok"



def test_doctor_ros_reports_a_sourced_environment(runner, fake_ros_sourced):
    result = runner.invoke(app, ["doctor", "--component", "ros", "--json"])
    assert result.exit_code == 0, result.output
    statuses = {c["name"]: c["status"] for c in json.loads(result.output)["checks"]}
    assert statuses["Environment sourced"] == "ok"


def test_doctor_ros_warns_when_the_environment_is_unsourced(
    runner, fake_ros_sourced, monkeypatch
):
    monkeypatch.delenv("AMENT_PREFIX_PATH", raising=False)
    result = runner.invoke(app, ["doctor", "--component", "ros", "--json"])
    checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
    assert checks["Environment sourced"]["status"] == "warn"
    assert "source " in checks["Environment sourced"]["hint"]


def test_doctor_robotics_probes_slam_toolbox(
    runner, fake_ros_sourced, tmp_path, monkeypatch
):
    from .conftest import write_lines

    write_lines(tmp_path / "pkgs.txt", ["nav2_bringup", "slam_toolbox"])
    monkeypatch.setenv("CAASI_FAKE_ROS_PACKAGES", str(tmp_path / "pkgs.txt"))

    result = runner.invoke(app, ["doctor", "--component", "robotics", "--json"])
    assert result.exit_code == 1
    statuses = {c["name"]: c["status"] for c in json.loads(result.output)["checks"]}
    assert statuses == {
        "Nav2": "ok",
        "MoveIt 2": "fail",
        "ros2_control": "fail",
        "SLAM Toolbox": "ok",
    }


# -- --details (§19) -----------------------------------------------------------

EXPLAIN_LABELS = ("Problem", "Cause", "Evidence", "Impact", "Suggested action")
EXPLAIN_FIELDS = ("problem", "cause", "evidence", "impact", "action")


def test_explanation_uses_detail_and_hint():
    block = doctor_cmd.explanation(
        CheckResult("nvidia", "nvidia-smi", "fail", "nvidia-smi not found on PATH", "Install it.")
    )
    assert set(block) == {"problem", "cause", "evidence", "impact", "action"}
    assert block["problem"] == "'nvidia-smi' is not available."
    assert block["evidence"] == "nvidia-smi not found on PATH"
    assert block["action"] == "Install it."
    assert "GPU simulation" in block["impact"]


def test_explanation_falls_back_when_a_probe_recorded_nothing():
    block = doctor_cmd.explanation(CheckResult("nvidia", "GPU", "fail"))
    assert block["evidence"] == "no evidence recorded for this check"
    assert "--details nvidia" in block["action"]


def test_explanation_warn_wording():
    block = doctor_cmd.explanation(CheckResult("ros", "Environment sourced", "warn", "not sourced"))
    assert block["problem"] == (
        "'Environment sourced' is available, but not in the state Caasi expects."
    )
    assert "outside what Caasi has tested" in block["cause"]


def test_explained_keeps_only_failures_and_warnings():
    results = [
        CheckResult("system", "a", "ok"),
        CheckResult("system", "b", "warn"),
        CheckResult("system", "c", "skip"),
        CheckResult("system", "d", "fail"),
    ]
    assert [r.name for r in doctor_cmd.explained(results)] == ["b", "d"]


def test_every_section_has_an_impact_explanation():
    """§19 coverage: --details must never fall back to a raw i18n key."""
    missing = [s for s in SECTION_KEYS if f"doctor.explain.impact.{s}" not in MESSAGES]
    assert missing == []


def test_doctor_details_renders_the_block(runner, no_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--details", "nvidia"])
    assert result.exit_code == 1
    out = all_output(result)
    assert "Explanation — NVIDIA" in out
    for label in EXPLAIN_LABELS:
        assert label in out
    assert "nvidia-smi not found on PATH" in out  # evidence comes from the probe
    assert "GPU simulation" in out  # impact comes from i18n


def test_doctor_details_warns_without_failing(runner, fake_ros_sourced, monkeypatch):
    monkeypatch.delenv("AMENT_PREFIX_PATH", raising=False)
    result = runner.invoke(app, ["doctor", "--details", "ros"])
    assert result.exit_code == 0
    out = all_output(result)
    assert "Explanation — ROS 2" in out
    assert "Environment sourced" in out
    assert "caasi shell --ros" in out  # the probe's hint is the suggested action


def test_doctor_details_without_problems(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor", "--details", "project"])
    assert result.exit_code == 0
    out = all_output(result)
    assert "Explanation — Project" in out
    assert "Nothing to explain in Project" in out


def test_doctor_details_runs_only_that_section(runner):
    result = runner.invoke(app, ["doctor", "--details", "system", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["checks"]
    assert all(c["section"] == "system" for c in data["checks"])


def test_doctor_details_json(runner, no_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--details", "nvidia", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["explanations"]
    for entry in data["explanations"]:
        assert entry["section"] == "nvidia"
        assert entry["status"] in ("fail", "warn")
        assert set(entry) == {"section", "name", "status", *EXPLAIN_FIELDS}
    assert data["explanations"][0]["evidence"] == "nvidia-smi not found on PATH"


def test_doctor_json_without_details_has_no_explanations(runner):
    data = json.loads(runner.invoke(app, ["doctor", "--component", "system", "--json"]).output)
    assert "explanations" not in data


def test_doctor_details_unknown_section(runner):
    result = runner.invoke(app, ["doctor", "--details", "bogus"])
    assert result.exit_code == 1
    assert "Unknown component 'bogus'" in all_output(result)


def test_doctor_details_wins_over_component(runner):
    result = runner.invoke(app, ["doctor", "--component", "nvidia", "--details", "system", "--json"])
    assert result.exit_code == 0
    assert all(c["section"] == "system" for c in json.loads(result.output)["checks"])


def test_doctor_details_still_prints_the_report(runner, no_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--details", "nvidia"])
    out = all_output(result)
    assert "Environment Diagnostics" in out
    assert "issue(s) found" in out


def test_doctor_details_respects_quiet(runner, no_nvidia_smi):
    result = runner.invoke(app, ["doctor", "--details", "nvidia", "--quiet"])
    assert result.exit_code == 1
    assert result.output.strip() == ""


def test_doctor_help_documents_details(runner):
    result = runner.invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--details" in result.output
