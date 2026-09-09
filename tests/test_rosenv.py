"""Tests for sourced-ROS execution (core/rosenv.py)."""

from __future__ import annotations

from caasi.core import ros as ros_core
from caasi.core import rosenv
from caasi.utils import shell


def _unsourced(monkeypatch) -> None:
    for var in rosenv.SOURCE_MARKERS:
        monkeypatch.delenv(var, raising=False)


# -- setup file discovery -------------------------------------------------


def test_setup_file_from_the_fake_distro(fake_ros_sourced):
    assert rosenv.setup_file() == fake_ros_sourced["setup"]
    assert rosenv.setup_file("fake") == fake_ros_sourced["setup"]


def test_setup_file_for_an_unknown_distro(fake_ros_sourced, tmp_path):
    assert rosenv.setup_file("nope") is None


def test_setup_file_without_ros(monkeypatch, tmp_path):
    monkeypatch.setattr(ros_core, "ROS_ROOT", tmp_path / "nothing")
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    assert rosenv.setup_file() is None
    assert rosenv.ros_root() is None


# -- is_sourced -----------------------------------------------------------


def test_is_sourced_true(fake_ros_sourced):
    assert rosenv.is_sourced() is True


def test_is_sourced_false_when_the_environment_is_stripped(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    assert rosenv.is_sourced() is False


def test_is_sourced_false_without_ros(monkeypatch, tmp_path):
    monkeypatch.setattr(ros_core, "ROS_ROOT", tmp_path / "nothing")
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    assert rosenv.is_sourced() is False


def test_is_sourced_honours_colcon_prefix_path(fake_ros_sourced, monkeypatch):
    monkeypatch.delenv("AMENT_PREFIX_PATH", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("COLCON_PREFIX_PATH", str(fake_ros_sourced["distro"]))
    assert rosenv.is_sourced() is True


# -- wrap -----------------------------------------------------------------


def test_wrap_is_a_noop_when_already_sourced(fake_ros_sourced):
    assert rosenv.wrap(["ros2", "pkg", "list"]) == ["ros2", "pkg", "list"]


def test_wrap_sources_when_unsourced(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    wrapped = rosenv.wrap(["/bin/ros2", "node", "list"])
    assert wrapped[:2] == ["bash", "-c"]
    assert str(fake_ros_sourced["setup"]) in wrapped[2]
    assert wrapped[3] == "--"
    assert wrapped[4:] == ["/bin/ros2", "node", "list"]


def test_wrap_without_a_setup_file_is_a_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(ros_core, "ROS_ROOT", tmp_path / "nothing")
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    _unsourced(monkeypatch)
    assert rosenv.wrap(["ros2"]) == ["ros2"]


def test_wrap_does_not_mutate_the_input(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    command = ["ros2", "pkg", "list"]
    rosenv.wrap(command)
    assert command == ["ros2", "pkg", "list"]


def test_run_ros2_uses_the_wrapper(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    seen: list[list[str]] = []

    def fake_run(args, timeout=None, env=None):
        seen.append(args)
        return shell.ShellResult(0, "", "")

    monkeypatch.setattr(shell, "run_cmd", fake_run)
    ros_core.run_ros2(["pkg", "list"])
    assert seen[0][0] == "bash"
    assert seen[0][-2:] == ["pkg", "list"]


def test_run_ros2_is_unwrapped_when_sourced(fake_ros_sourced, monkeypatch):
    seen: list[list[str]] = []

    def fake_run(args, timeout=None, env=None):
        seen.append(args)
        return shell.ShellResult(0, "", "")

    monkeypatch.setattr(shell, "run_cmd", fake_run)
    ros_core.run_ros2(["pkg", "list"])
    assert seen[0] == [fake_ros_sourced["binary"], "pkg", "list"]


# -- sourced_env ----------------------------------------------------------


def test_sourced_env_reads_the_setup_file(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    env = rosenv.sourced_env()
    assert env.get("CAASI_FAKE_SOURCED") == "1"
    assert env.get("ROS_DISTRO") == "fake"
    assert env.get("AMENT_PREFIX_PATH") == str(fake_ros_sourced["distro"])


def test_sourced_env_overlays_the_current_environment(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    monkeypatch.setenv("CAASI_FAKE_SOURCED", "tampered")
    assert rosenv.sourced_env()["CAASI_FAKE_SOURCED"] == "1"


def test_sourced_env_is_cached(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    calls: list[list[str]] = []
    real_run = shell.run_cmd

    def counting_run(args, timeout=None, env=None):
        calls.append(args)
        return real_run(args, timeout=timeout, env=env)

    monkeypatch.setattr(shell, "run_cmd", counting_run)
    rosenv.sourced_env()
    rosenv.sourced_env()
    assert len(calls) == 1


def test_sourced_env_without_ros_is_the_current_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(ros_core, "ROS_ROOT", tmp_path / "nothing")
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    monkeypatch.setenv("CAASI_MARKER", "here")
    assert rosenv.sourced_env()["CAASI_MARKER"] == "here"


def test_sourced_env_survives_a_broken_setup_file(fake_ros_sourced, monkeypatch):
    _unsourced(monkeypatch)
    fake_ros_sourced["setup"].write_text("exit 3\n", encoding="utf-8")
    rosenv.clear_cache()
    env = rosenv.sourced_env()
    assert env.get("CAASI_FAKE_SOURCED") is None
    assert "PATH" in env


# -- hint -----------------------------------------------------------------


def test_source_hint(fake_ros_sourced):
    assert rosenv.source_hint() == f"source {fake_ros_sourced['setup']}"


def test_source_hint_without_ros(monkeypatch, tmp_path):
    monkeypatch.setattr(ros_core, "ROS_ROOT", tmp_path / "nothing")
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    assert rosenv.source_hint() == ""
