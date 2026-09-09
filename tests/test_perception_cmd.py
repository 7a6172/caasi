"""Tests for `caasi perception` — cameras, pose, detection, node inspection."""

from __future__ import annotations

import json
import sys

import yaml

from caasi.cli.main import app

from .conftest import all_output
from .test_ros_cmd import configure_runs, no_ros2, wait_for_run
from .test_sensors_cmd import fake_devices

DETECTION_NODE = "/isaac_ros_object_detection_node"

DETECTION_INFO = """
    /isaac_ros_object_detection_node
      Subscribers:
        /camera/image_raw: sensor_msgs/msg/Image
      Publishers:
        /detections: vision_msgs/msg/Detection2DArray
      Service Servers:
        /detections/get: detection_msgs/srv/GetDetections
"""

IMAGE_QOS = """
    Type: sensor_msgs/msg/Image
    Publisher count: 1
    Node name: v4l2_camera_node
    Node namespace: /
    Endpoint type: PUBLISHER
    Reliability: RELIABLE
    Durability: VOLATILE
    Subscription count: 1
    Node name: isaac_ros_object_detection_node
    Node namespace: /
    Endpoint type: SUBSCRIPTION
    Reliability: RELIABLE
    Durability: VOLATILE
"""


def test_perception_status_lists_capabilities(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_object_detection")
    result = runner.invoke(app, ["perception", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "perception"
    assert data["total"] == 5
    assert data["launcher"] == sys.executable
    states = {item["key"]: item for item in data["capabilities"]}
    assert states["detection"]["found"] is True
    assert states["segmentation"]["found"] is False

    result = runner.invoke(app, ["perception", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "Perception" in result.output
    assert "detection" in result.output
    assert "Launcher" in result.output


def test_perception_camera_lists_devices_and_topics(
    runner, fake_ros_world, tmp_path, monkeypatch
):
    fake_devices(tmp_path, monkeypatch, serial=False)
    fake_ros_world.topic_types(
        "/camera/image_raw [sensor_msgs/msg/Image]",
        "/camera/points [sensor_msgs/msg/PointCloud2]",
        "/odom [nav_msgs/msg/Odometry]",
    )
    result = runner.invoke(app, ["perception", "camera", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["devices"] == [
        {"device": str(tmp_path / "dev" / "video0"), "name": "Fake Cam"}
    ]
    assert data["topics"] == [
        {"topic": "/camera/image_raw", "type": "sensor_msgs/msg/Image"}
    ]

    result = runner.invoke(app, ["perception", "camera"])
    assert result.exit_code == 0, all_output(result)
    assert "Video devices" in result.output
    assert "Fake Cam" in result.output
    assert "Live image topics" in result.output
    assert "/odom" not in result.output


def test_perception_camera_without_devices_or_topics(
    runner, fake_ros_world, tmp_path, monkeypatch
):
    fake_devices(tmp_path, monkeypatch, cameras=False, serial=False)
    fake_ros_world.topic_types()
    result = runner.invoke(app, ["perception", "camera"])
    assert result.exit_code == 0, all_output(result)
    assert "No live image topics" in result.output
    assert "No camera device and no image topic found." in result.output


def test_perception_camera_without_ros2(runner, tmp_path, monkeypatch):
    fake_devices(tmp_path, monkeypatch, serial=False)
    no_ros2(monkeypatch, tmp_path)
    result = runner.invoke(app, ["perception", "camera", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["topics"] == []
    assert len(data["devices"]) == 1


def test_perception_camera_hz_json(runner, fake_ros_world):
    fake_ros_world.hz("average rate: 14.987")
    result = runner.invoke(
        app,
        ["perception", "camera", "--hz", "/camera/image_raw", "--duration", "1", "--json"],
    )
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["topic"] == "/camera/image_raw"
    assert data["rate"] == 14.987
    assert data["detail"] == "14.987 Hz"


def test_perception_camera_hz_passes_through(runner, fake_ros_world):
    fake_ros_world.hz("average rate: 29.970")
    result = runner.invoke(
        app, ["perception", "camera", "--hz", "/camera/image_raw", "--duration", "1"]
    )
    assert result.exit_code == 0, all_output(result)
    assert "average rate: 29.970" in result.output


def test_perception_pose_echoes_catalog_topic(runner, fake_ros_world):
    result = runner.invoke(app, ["perception", "pose"])
    assert result.exit_code == 0, all_output(result)
    assert "echo /apriltag/detections" in result.output

    result = runner.invoke(app, ["perception", "pose", "--topic", "/tf"])
    assert result.exit_code == 0, all_output(result)
    assert "echo /tf" in result.output


def test_perception_pose_json_reports_command(runner, fake_ros_world):
    result = runner.invoke(app, ["perception", "pose", "--json", "--once"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["returncode"] == 0
    assert data["command"][-2:] == ["/apriltag/detections", "--once"]
    assert data["stdout"].strip() == "echo /apriltag/detections --once"


def test_perception_detect_fails_when_unavailable(runner, fake_ros_world):
    fake_ros_world.packages()
    result = runner.invoke(app, ["perception", "detect"])
    assert result.exit_code == 1
    assert "'detection' is not installed." in all_output(result)
    assert "caasi isaac-ros list" in all_output(result)


def test_perception_detect_starts_tracked_run(runner, fake_ros_world, tmp_path, monkeypatch):
    runs_base = configure_runs(tmp_path, monkeypatch)
    fake_ros_world.packages("isaac_ros_object_detection")
    result = runner.invoke(app, ["perception", "detect", "--name", "yolo"])
    assert result.exit_code == 0, all_output(result)
    run_dir = wait_for_run(runs_base)
    manifest = yaml.safe_load((run_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "perception"
    assert manifest["name"] == "yolo"
    assert manifest["command"][-2:] == [
        "isaac_ros_object_detection",
        "object_detection.launch.py",
    ]
    assert manifest["extra"] == {"domain": "isaacros", "capability": "detection"}
    stdout = (run_dir / "stdout.log").read_text(encoding="utf-8")
    assert stdout.strip() == "launch isaac_ros_object_detection object_detection.launch.py"


def test_perception_segment_dry_run_passes_extra_args(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_image_segmentation")
    result = runner.invoke(app, ["perception", "segment", "--dry-run", "model:=unet"])
    assert result.exit_code == 0, all_output(result)
    assert "image_segmentation.launch.py model:=unet" in result.output


def test_perception_inspect_running_node(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_object_detection").nodes(DETECTION_NODE)
    fake_ros_world.node_info(DETECTION_NODE, DETECTION_INFO)
    fake_ros_world.topic_info("/camera/image_raw", IMAGE_QOS)

    result = runner.invoke(app, ["perception", "inspect"])
    assert result.exit_code == 0, all_output(result)
    assert DETECTION_NODE in result.output
    assert "/camera/image_raw" in result.output
    assert "publisher v4l2_camera_node: RELIABLE / VOLATILE" in result.output

    result = runner.invoke(app, ["perception", "inspect", "--no-qos"])
    assert result.exit_code == 0, all_output(result)
    assert "RELIABLE / VOLATILE" not in result.output


def test_perception_inspect_json(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_object_detection").nodes(DETECTION_NODE)
    fake_ros_world.node_info(DETECTION_NODE, DETECTION_INFO)
    fake_ros_world.topic_info("/camera/image_raw", IMAGE_QOS)

    result = runner.invoke(app, ["perception", "inspect", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert [node["node"] for node in data["nodes"]] == [DETECTION_NODE]
    interfaces = data["nodes"][0]["interfaces"]
    assert interfaces["Subscribers"] == [
        {"endpoint": "/camera/image_raw", "type": "sensor_msgs/msg/Image"}
    ]
    assert interfaces["Publishers"] == [
        {"endpoint": "/detections", "type": "vision_msgs/msg/Detection2DArray"}
    ]


def test_perception_inspect_explicit_node(runner, fake_ros_world):
    fake_ros_world.nodes("/v4l2_camera_node")
    fake_ros_world.node_info(
        "/v4l2_camera_node",
        """
        /v4l2_camera_node
          Publishers:
            /camera/image_raw: sensor_msgs/msg/Image
        """,
    )
    result = runner.invoke(app, ["perception", "inspect", "/v4l2_camera_node", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert [node["node"] for node in data["nodes"]] == ["/v4l2_camera_node"]


def test_perception_inspect_without_nodes(runner, fake_ros_world):
    fake_ros_world.nodes()
    result = runner.invoke(app, ["perception", "inspect"])
    assert result.exit_code == 0, all_output(result)
    assert "No perception nodes are running." in result.output

    result = runner.invoke(app, ["perception", "inspect", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.output) == {"nodes": []}
