"""Tests for `caasi nitros` and `caasi pipeline` — the running graph as evidence."""

from __future__ import annotations

import json

import pytest

from caasi.cli.main import app

from .conftest import all_output

CAMERA_NODE = "/v4l2_camera_node"
DETECTION_NODE = "/isaac_ros_object_detection_node"
NITROS_CAMERA_NODE = "/isaac_ros_nitros_camera_node"

IMAGE_TOPIC = "/camera/image_raw"

MIXED_QOS = """
    Type: sensor_msgs/msg/Image
    Publisher count: 1
    Node name: v4l2_camera_node
    Node namespace: /
    Endpoint type: PUBLISHER
    Reliability: BEST_EFFORT
    Durability: VOLATILE
    Subscription count: 1
    Node name: isaac_ros_object_detection_node
    Node namespace: /
    Endpoint type: SUBSCRIPTION
    Reliability: RELIABLE
    Durability: VOLATILE
"""


@pytest.fixture(autouse=True)
def no_nitros_env(monkeypatch):
    """``ROS_DISABLE_NITROS`` is a catalog probe target — keep it unset."""
    monkeypatch.delenv("ROS_DISABLE_NITROS", raising=False)


def cpu_gpu_graph(fake_ros):
    """A plain camera node feeding an accelerated node (one GPU/CPU boundary)."""
    fake_ros.nodes(CAMERA_NODE, DETECTION_NODE)
    fake_ros.node_info(
        CAMERA_NODE,
        f"""
        {CAMERA_NODE}
          Publishers:
            {IMAGE_TOPIC}: sensor_msgs/msg/Image
        """,
    )
    fake_ros.node_info(
        DETECTION_NODE,
        f"""
        {DETECTION_NODE}
          Subscribers:
            {IMAGE_TOPIC}: sensor_msgs/msg/Image
          Publishers:
            /detections: vision_msgs/msg/Detection2DArray
        """,
    )
    fake_ros.topic_info(IMAGE_TOPIC, MIXED_QOS)
    return fake_ros


def accelerated_graph(fake_ros):
    """Two NITROS-aware nodes: the payload never leaves the GPU."""
    fake_ros.nodes(NITROS_CAMERA_NODE, DETECTION_NODE)
    fake_ros.node_info(
        NITROS_CAMERA_NODE,
        f"""
        {NITROS_CAMERA_NODE}
          Publishers:
            {IMAGE_TOPIC}: isaac_ros_nitros_interfaces/msg/NitrosImage
        """,
    )
    fake_ros.node_info(
        DETECTION_NODE,
        f"""
        {DETECTION_NODE}
          Subscribers:
            {IMAGE_TOPIC}: isaac_ros_nitros_interfaces/msg/NitrosImage
        """,
    )
    return fake_ros


def test_nitros_status(runner, fake_ros_world, fake_nvidia_smi):
    fake_ros_world.packages("isaac_ros_nitros", "isaac_ros_nitros_type_interfaces")
    result = runner.invoke(app, ["nitros", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["domain"] == "nitros"
    assert data["total"] == 4
    assert data["installed"] == 2
    assert data["cuda"] == "13.0"
    assert "tensorrt" in data
    states = {item["key"]: item for item in data["capabilities"]}
    assert states["core"]["found"] is True
    assert states["disable"]["found"] is False

    result = runner.invoke(app, ["nitros", "status"])
    assert result.exit_code == 0, all_output(result)
    assert "NITROS" in result.output
    assert "2 of 4 capabilities installed." in result.output


def test_nitros_status_reports_disable_env(runner, fake_ros_world, monkeypatch):
    fake_ros_world.packages("isaac_ros_nitros")
    monkeypatch.setenv("ROS_DISABLE_NITROS", "1")
    result = runner.invoke(app, ["nitros", "status", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["installed"] == 2
    states = {item["key"]: item for item in data["capabilities"]}
    assert states["disable"]["found"] is True
    assert states["disable"]["how"] == "env"


def test_nitros_doctor_explains_transport(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_nitros").nodes()
    result = runner.invoke(app, ["nitros", "doctor", "--json"])
    data = json.loads(result.output)
    assert result.exit_code == data["exit_code"] == 1
    assert data["sections"] == ["accelerated", "nvidia", "graphics"]
    checks = {check["name"]: check for check in data["checks"]}
    assert checks["What NITROS does"]["status"] == "skip"
    assert "GPU nodes share buffers" in checks["What NITROS does"]["detail"]
    assert checks["NITROS transport"]["status"] == "ok"
    # No nodes running: nothing to say about the graph.
    assert "Graph mixing" not in checks


def test_nitros_doctor_warns_on_mixed_graph(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_nitros")
    cpu_gpu_graph(fake_ros_world)
    result = runner.invoke(app, ["nitros", "doctor", "--json"])
    data = json.loads(result.output)
    checks = {check["name"]: check for check in data["checks"]}
    mixing = checks["Graph mixing"]
    assert mixing["status"] == "warn"
    assert mixing["detail"] == (
        f"1 topic(s) cross a GPU/CPU boundary, e.g. {IMAGE_TOPIC}"
    )
    assert "NITROS type on both sides" in mixing["hint"]


def test_nitros_doctor_reports_clean_graph(runner, fake_ros_world):
    fake_ros_world.packages("isaac_ros_nitros")
    accelerated_graph(fake_ros_world)
    result = runner.invoke(app, ["nitros", "doctor", "--json"])
    checks = {check["name"]: check for check in json.loads(result.output)["checks"]}
    assert checks["Graph mixing"]["status"] == "ok"
    assert checks["Graph mixing"]["detail"] == (
        "no GPU/CPU boundary in the running graph (2 node(s))"
    )


def test_pipeline_inspect_reports_boundary(runner, fake_ros_world):
    cpu_gpu_graph(fake_ros_world)
    result = runner.invoke(app, ["pipeline", "inspect", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["nodes"] == [CAMERA_NODE, DETECTION_NODE]
    assert data["accelerated"] == [DETECTION_NODE]
    assert data["topics"] == 2
    assert data["plain"] == [
        {
            "topic": IMAGE_TOPIC,
            "type": "sensor_msgs/msg/Image",
            "accelerated_type": "isaac_ros_nitros_interfaces/msg/NitrosImage",
            "nodes": [DETECTION_NODE, CAMERA_NODE],
        }
    ]
    assert data["boundaries"] == [
        {
            "topic": IMAGE_TOPIC,
            "type": "sensor_msgs/msg/Image",
            "accelerated": [DETECTION_NODE],
            "plain": [CAMERA_NODE],
        }
    ]


def test_pipeline_inspect_table(runner, fake_ros_world):
    cpu_gpu_graph(fake_ros_world)
    result = runner.invoke(app, ["pipeline", "inspect"])
    assert result.exit_code == 0, all_output(result)
    assert "2 node(s), 1 accelerated, 2 topic(s) in the graph." in result.output
    assert "Topics that could be accelerated" in result.output
    assert "isaac_ros_nitros_interfaces/msg/NitrosImage" in result.output
    assert f"{IMAGE_TOPIC}: GPU/CPU copy between" in result.output
    assert "Publish the accelerated type" in result.output


def test_pipeline_inspect_reports_qos_mismatch(runner, fake_ros_world):
    cpu_gpu_graph(fake_ros_world)
    result = runner.invoke(app, ["pipeline", "inspect", "--json"])
    data = json.loads(result.output)
    assert data["qos"] == [
        {
            "topic": IMAGE_TOPIC,
            "publisher": "v4l2_camera_node",
            "subscriber": "isaac_ros_object_detection_node",
            "reason": "BEST_EFFORT publisher cannot reach a RELIABLE subscriber",
        }
    ]

    result = runner.invoke(app, ["pipeline", "inspect"])
    assert "BEST_EFFORT publisher cannot reach a RELIABLE subscriber" in result.output

    result = runner.invoke(app, ["pipeline", "inspect", "--no-qos", "--json"])
    assert json.loads(result.output)["qos"] == []


def test_pipeline_inspect_clean_graph(runner, fake_ros_world):
    accelerated_graph(fake_ros_world)
    result = runner.invoke(app, ["pipeline", "inspect", "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["accelerated"] == [NITROS_CAMERA_NODE, DETECTION_NODE]
    assert data["topics"] == 1
    assert data["plain"] == []
    assert data["boundaries"] == []
    assert data["qos"] == []

    result = runner.invoke(app, ["pipeline", "inspect"])
    assert result.exit_code == 0, all_output(result)
    assert "No acceleration boundary found in the running graph." in result.output


def test_pipeline_inspect_single_node(runner, fake_ros_world):
    cpu_gpu_graph(fake_ros_world)
    result = runner.invoke(app, ["pipeline", "inspect", DETECTION_NODE, "--json"])
    assert result.exit_code == 0, all_output(result)
    data = json.loads(result.output)
    assert data["nodes"] == [DETECTION_NODE]
    assert data["accelerated"] == [DETECTION_NODE]
    # One accelerated endpoint alone is not a boundary.
    assert data["plain"][0]["nodes"] == [DETECTION_NODE]
    assert data["boundaries"] == []


def test_pipeline_inspect_without_nodes(runner, fake_ros_world):
    fake_ros_world.nodes()
    result = runner.invoke(app, ["pipeline", "inspect"])
    assert result.exit_code == 0, all_output(result)
    assert "No nodes are running." in result.output
    assert "Start your graph first" in result.output

    result = runner.invoke(app, ["pipeline", "inspect", "--json"])
    assert result.exit_code == 0, all_output(result)
    assert json.loads(result.output) == {
        "nodes": [],
        "plain": [],
        "boundaries": [],
        "qos": [],
    }
