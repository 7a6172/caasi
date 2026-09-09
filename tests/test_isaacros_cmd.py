"""Tests for `caasi isaac-ros` — the catalog-driven status/doctor/list/launch group."""

from __future__ import annotations

import json

import yaml

from caasi.cli.main import app

from .conftest import all_output
from .test_ros_cmd import configure_runs, no_ros2, wait_for_run

INSTALLED = (
    "isaac_ros_nitros",
    "isaac_ros_nitros_type_interfaces",
    "isaac_ros_visual_slam",
    "isaac_ros_nvblox",
    "isaac_ros_cumotion",
)


def test_isaac_ros_status_json(runner, fake_ros_world):
    fake_ros_world.packages(*INSTALLED).nodes("/visual_slam_node")
    result = runner.invoke(app, ["isaac-ros", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "isaacros"
    assert data["ros_distro"] == "fake"
    assert data["ros_sourced"] is True
    assert data["installed"] == 4
    assert data["running"] == ["slam"]
    states = {item["key"]: item for item in data["capabilities"]}
    assert states["slam"]["found"] is True
    assert states["slam"]["nodes"] == ["/visual_slam_node"]
    assert states["detection"]["found"] is False


def test_isaac_ros_status_table(runner, fake_ros_world):
    fake_ros_world.packages(*INSTALLED)
    result = runner.invoke(app, ["isaac-ros", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "Isaac ROS" in result.output
    assert "4 of 10 capabilities installed." in result.output
    assert "nitros" in result.output


def test_isaac_ros_workspace_from_env(runner, fake_ros_world, tmp_path, monkeypatch):
    workspace = tmp_path / "isaac-ws"
    workspace.mkdir()
    monkeypatch.setenv("ISAAC_ROS_WS", str(workspace))
    fake_ros_world.packages()
    result = runner.invoke(app, ["isaac-ros", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.output)["workspace"] == str(workspace)


def test_isaac_ros_workspace_common_path(runner, fake_ros_world, tmp_path, monkeypatch):
    common = tmp_path / "home" / "workspaces" / "isaac_ros"
    common.mkdir(parents=True)
    fake_ros_world.packages()
    result = runner.invoke(app, ["isaac-ros", "status", "--json"])
    assert json.loads(result.output)["workspace"] == str(common)


def test_isaac_ros_list_maps_capabilities_to_groups(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_nitros")
    result = runner.invoke(app, ["isaac-ros", "list", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    rows = {row["capability"]: row for row in data["capabilities"]}
    assert rows["nitros"]["installed"] is True
    assert rows["nitros"]["prefix"] == str(fake_ros_world.prefix)
    assert rows["slam"]["group"] == "slam"
    assert rows["mapping"]["group"] == "mapping"
    assert rows["detection"]["group"] == "perception"
    assert rows["motion"]["group"] == "motion"

    result = runner.invoke(app, ["isaac-ros", "list"])
    assert result.exit_code == 0, all_output(result)
    assert "perception" in result.output


def test_isaac_ros_launch_starts_tracked_run(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    fake_ros_world.packages(*INSTALLED)
    result = runner.invoke(
        app, ["isaac-ros", "launch", "isaac_ros_visual_slam", "visual_slam.launch.py"]
    )
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "isaacros"
    assert manifest["backend"] == "ros"
    assert manifest["command"][-2:] == ["isaac_ros_visual_slam", "visual_slam.launch.py"]
    assert manifest["extra"]["package"] == "isaac_ros_visual_slam"
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert stdout.strip() == "launch isaac_ros_visual_slam visual_slam.launch.py"


def test_isaac_ros_launch_passes_extra_args(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    fake_ros_world.packages(*INSTALLED)
    result = runner.invoke(
        app,
        [
            "isaac-ros",
            "launch",
            "isaac_ros_nvblox",
            "nvblox.launch.py",
            "--name",
            "mapper",
            "use_composition:=true",
        ],
    )
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "mapper"
    assert manifest["command"][-1] == "use_composition:=true"


def test_isaac_ros_launch_dry_run(runner, fake_ros_world):
    fake_ros_world.packages(*INSTALLED)
    result = runner.invoke(
        app, ["isaac-ros", "launch", "isaac_ros_nitros", "nitros.launch.py", "--dry-run"]
    )
    assert result.exit_code == 0, all_output(result)
    assert "launch isaac_ros_nitros nitros.launch.py" in result.output


def test_isaac_ros_doctor_reports_capabilities(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_nitros")
    result = runner.invoke(app, ["isaac-ros", "doctor", "--json"])
    data = json.loads(result.output)
    assert result.exit_code == data["exit_code"] == 1
    checks = {check["name"]: check for check in data["checks"]}
    assert checks["NITROS transport"]["status"] == "ok"
    assert checks["cuMotion"]["status"] == "fail"
    assert checks["TensorRT inference"]["status"] == "skip"
    assert "accelerated" in data["sections"]
    assert checks["RMW_IMPLEMENTATION"]["status"] == "skip"


def test_isaac_ros_doctor_cuda_and_tensorrt(runner, fake_ros_world, fake_nvidia_smi, monkeypatch):
    fake_ros_world.packages(*INSTALLED)
    result = runner.invoke(app, ["isaac-ros", "doctor", "--json"])
    data = json.loads(result.output)
    checks = {check["name"]: check for check in data["checks"]}
    assert checks["CUDA (driver)"]["status"] == "ok"
    assert checks["CUDA (driver)"]["detail"] == "13.0"
    assert checks["ROS_DOMAIN_ID"]["status"] == "skip"

    monkeypatch.setenv("ROS_DOMAIN_ID", "7")
    result = runner.invoke(app, ["isaac-ros", "doctor", "--json"])
    checks = {check["name"]: check for check in json.loads(result.output)["checks"]}
    assert checks["ROS_DOMAIN_ID"]["status"] == "ok"
    assert checks["ROS_DOMAIN_ID"]["detail"] == "7"


def test_isaac_ros_doctor_dedupes_shared_packages(runner, fake_ros_world):
    fake_ros_world.packages(*INSTALLED)
    result = runner.invoke(app, ["isaac-ros", "doctor", "--json"])
    data = json.loads(result.output)
    details = [check["detail"] for check in data["checks"] if check["status"] == "ok"]
    assert details.count(str(fake_ros_world.prefix)) == len(INSTALLED)


def test_isaac_ros_status_without_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["isaac-ros", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["installed"] == 0
    assert data["running"] == []


def test_isaac_ros_launch_without_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["isaac-ros", "launch", "pkg", "file.launch.py"])
    assert result.exit_code == 1
    assert "ros2 CLI not found" in all_output(result)
