"""Tests for `caasi slam` — launch a backend, test the running graph, benchmark."""

from __future__ import annotations

import json
import sys

import yaml

from caasi.cli.main import app

from .conftest import all_output
from .test_ros_cmd import configure_runs, no_ros2, wait_for_run

VISUAL_TOPICS = ("/tf", "/map", "/visual_slam/tracking/odometry")


def test_slam_status(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_visual_slam").nodes("/visual_slam_node")
    result = runner.invoke(app, ["slam", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "slam"
    assert data["total"] == 3
    assert data["installed"] == 1
    assert data["ros_distro"] == "fake"
    assert data["running"] == ["visual"]
    states = {item["key"]: item for item in data["capabilities"]}
    assert states["visual"]["nodes"] == ["/visual_slam_node"]
    assert states["toolbox"]["found"] is False


def test_slam_launch_starts_tracked_run(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    fake_ros_world.packages("isaac_ros_visual_slam")
    result = runner.invoke(app, ["slam", "launch"])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "slam"
    assert manifest["backend"] == "ros"
    assert manifest["command"][-2:] == ["isaac_ros_visual_slam", "visual_slam.launch.py"]
    assert manifest["extra"] == {"domain": "slam", "capability": "visual"}
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert stdout.strip() == "launch isaac_ros_visual_slam visual_slam.launch.py"


def test_slam_launch_honours_backend(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    fake_ros_world.packages("isaac_ros_visual_slam", "slam_toolbox")
    result = runner.invoke(app, ["slam", "launch", "--backend", "toolbox", "use_sim_time:=true"])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["command"][-3:] == [
        "slam_toolbox",
        "online_async_launch.py",
        "use_sim_time:=true",
    ]
    assert manifest["name"] == "toolbox"


def test_slam_launch_missing_backend(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_visual_slam")
    result = runner.invoke(app, ["slam", "launch", "--backend", "cartographer"])
    assert result.exit_code == 1
    assert "'cartographer' is not available (cartographer_ros)." in all_output(result)


def test_slam_launch_unknown_backend(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_visual_slam")
    result = runner.invoke(app, ["slam", "launch", "--backend", "nope"])
    assert result.exit_code == 1
    assert "Unknown slam capability 'nope'." in all_output(result)
    assert "visual, toolbox, cartographer" in all_output(result)


def test_slam_launch_nothing_installed(runner, fake_ros_world):
    fake_ros_world.packages()
    result = runner.invoke(app, ["slam", "launch", "--dry-run"])
    assert result.exit_code == 1
    assert "No slam capability is installed." in all_output(result)


def test_slam_test_reports_healthy_graph(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_visual_slam").nodes("/visual_slam_node").topics(
        *VISUAL_TOPICS
    )
    result = runner.invoke(app, ["slam", "test", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "slam"
    assert data["backend"] == "visual"
    assert data["exit_code"] == 0
    checks = {check["name"]: check for check in data["checks"]}
    assert checks["Visual SLAM (Isaac ROS)"]["status"] == "ok"
    assert checks["Visual SLAM (Isaac ROS)"]["detail"] == str(fake_ros_world.prefix)
    assert checks["SLAM node"]["status"] == "ok"
    assert checks["SLAM node"]["detail"] == "/visual_slam_node"
    assert checks["Topic /tf"]["status"] == "ok"
    assert checks["Topic /map"]["status"] == "ok"


def test_slam_test_fails_on_missing_topic(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_visual_slam").nodes("/visual_slam_node").topics("/tf")
    result = runner.invoke(app, ["slam", "test", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["exit_code"] == 1
    checks = {check["name"]: check for check in data["checks"]}
    assert checks["Topic /tf"]["status"] == "ok"
    assert checks["Topic /map"]["status"] == "fail"
    assert checks["Topic /map"]["detail"] == "not published"
    assert "caasi ros graph" in checks["Topic /map"]["hint"]


def test_slam_test_skips_topics_without_node(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_visual_slam").nodes().topics(*VISUAL_TOPICS)
    result = runner.invoke(app, ["slam", "test", "--json"])
    assert result.exit_code == 1
    checks = {check["name"]: check for check in json.loads(result.output)["checks"]}
    assert checks["SLAM node"]["status"] == "fail"
    assert checks["SLAM node"]["hint"] == "Start one with: caasi slam launch"
    assert checks["Topic /tf"]["status"] == "skip"


def test_slam_test_samples_rate(runner, fake_ros_world):
    fake_ros_world.packages("slam_toolbox").nodes("/async_slam_toolbox_node").topics(
        "/tf", "/map", "/scan"
    )
    fake_ros_world.hz("average rate: 20.000")
    result = runner.invoke(app, ["slam", "test", "--hz", "--duration", "1", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["backend"] == "toolbox"
    checks = {check["name"]: check for check in data["checks"]}
    assert checks["Rate /tf"]["status"] == "ok"
    assert checks["Rate /tf"]["detail"] == "20.0 Hz"
    assert checks["Rate /scan"]["status"] == "ok"


def test_slam_test_table_output(runner, fake_ros_world):
    fake_ros_world.packages("slam_toolbox").nodes("/async_slam_toolbox_node").topics(
        "/tf", "/map", "/scan"
    )
    result = runner.invoke(app, ["slam", "test"])
    assert result.exit_code == 0, all_output(result)
    assert "SLAM node" in result.output
    assert "/async_slam_toolbox_node" in result.output
    assert "not published" not in result.output


def test_slam_test_without_ros2(runner, tmp_path, monkeypatch):
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["slam", "test", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["backend"] == ""
    assert data["exit_code"] == 0
    assert data["checks"] == [
        {
            "section": "accelerated",
            "name": "SLAM",
            "status": "skip",
            "detail": "skipped (ROS 2 CLI unavailable)",
            "hint": "Install ROS 2 to enable Nav2 / MoveIt 2 / ros2_control checks.",
        }
    ]


def test_slam_benchmark_samples_topic(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    fake_ros_world.packages("isaac_ros_visual_slam").hz("average rate: 15.000")
    result = runner.invoke(app, ["slam", "benchmark", "--duration", "2"])
    assert result.exit_code == 0, all_output(result)
    assert "caasi benchmark report" in result.output
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "benchmark"
    assert manifest["backend"] == "ros"
    assert manifest["name"] == "slam-hz-tf"
    assert manifest["command"][-4:] == ["hz", "--window", "10", "/tf"]
    assert manifest["extra"] == {"domain": "slam", "topic": "/tf", "duration": 2.0}
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert "average rate: 15.000" in stdout


def test_slam_benchmark_dry_run(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_visual_slam")
    result = runner.invoke(app, ["slam", "benchmark", "--topic", "/map", "--dry-run"])
    assert result.exit_code == 0, all_output(result)
    assert "topic hz --window 10 /map" in result.output


def test_slam_benchmark_script(runner, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    script = tmp_path / "slam_bench.py"
    script.write_text("print('ate 0.42 m')\n", encoding="utf-8")
    result = runner.invoke(app, ["slam", "benchmark", "--script", str(script)])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["backend"] == "script"
    assert manifest["kind"] == "benchmark"
    assert manifest["name"] == "slam_bench"
    assert manifest["command"][:2] == [sys.executable, str(script)]
    assert manifest["extra"] == {"domain": "slam", "script": str(script)}
    assert "ate 0.42 m" in (run_dir / "stdout.log").read_text(encoding="utf-8")


def test_slam_benchmark_missing_script(runner, tmp_path):
    result = runner.invoke(app, ["slam", "benchmark", "--script", str(tmp_path / "nope.py")])
    assert result.exit_code == 1
    assert "Script not found:" in all_output(result)
