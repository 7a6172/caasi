"""Tests for the adapter layer (core/adapters.py)."""

from __future__ import annotations

import sys

import pytest

from caasi import state
from caasi.checks import SECTION_KEYS
from caasi.core import adapters, catalog
from caasi.core.config import Config

from .conftest import write_lines


def make_config(data: dict | None = None) -> Config:
    return Config(data or {}, [])


@pytest.fixture(autouse=True)
def clean_registry():
    adapters.clear_registry()
    yield
    adapters.clear_registry()


@pytest.fixture
def fake_packages(tmp_path, monkeypatch):
    """Declare which ROS packages the fake ros2 CLI reports as installed."""
    prefix = tmp_path / "ros-prefix"
    prefix.mkdir()
    monkeypatch.setenv("CAASI_FAKE_ROS_PREFIX", str(prefix))

    def _set(names):
        path = write_lines(tmp_path / "pkgs.txt", list(names))
        monkeypatch.setenv("CAASI_FAKE_ROS_PACKAGES", str(path))
        catalog.clear_cache()
        return path

    return _set


# -- protocol & registry --------------------------------------------------


def test_both_adapters_satisfy_the_protocol():
    assert isinstance(adapters.RosAdapter("slam"), adapters.Adapter)
    assert isinstance(adapters.SimAdapter("physics"), adapters.Adapter)


def test_registry_round_trip():
    adapter = adapters.register(adapters.RosAdapter("slam"))
    assert adapters.get("slam") is adapter
    assert adapter in adapters.adapters()
    adapters.clear_registry()
    assert adapters.get("slam") is None
    assert adapters.adapters() == ()


def test_adapter_for_builds_on_demand():
    adapter = adapters.adapter_for("slam")
    assert isinstance(adapter, adapters.RosAdapter)
    assert adapters.get("slam") is adapter
    assert adapters.adapter_for("slam") is adapter


def test_adapter_for_a_sim_domain():
    assert isinstance(adapters.adapter_for("physics"), adapters.SimAdapter)
    assert isinstance(adapters.adapter_for("groot"), adapters.SimAdapter)


def test_adapter_for_an_unknown_domain():
    with pytest.raises(adapters.AdapterError):
        adapters.adapter_for("nope")


def test_build_adapters_covers_every_domain():
    built = adapters.build_adapters()
    assert {a.domain for a in built} == set(catalog.DOMAINS)
    for spec in catalog.domains():
        expected = adapters.adapter_class_for(spec.kind)
        assert isinstance(adapters.get(spec.key), expected)


def test_adapter_class_for_unknown_kind():
    assert adapters.adapter_class_for("nonsense") is None


def test_section_mapping_covers_every_domain():
    for key in catalog.DOMAINS:
        assert adapters.SECTION_FOR_DOMAIN[key] in SECTION_KEYS


def test_spec_raises_for_an_unknown_domain():
    with pytest.raises(adapters.AdapterError):
        adapters.RosAdapter("nope").spec(make_config())


# -- detect / status ------------------------------------------------------


def test_detect_returns_one_result_per_capability(fake_ros_sourced, fake_packages):
    fake_packages(["slam_toolbox"])
    resolved = adapters.RosAdapter("slam").detect(make_config())
    assert [item.capability.key for item in resolved] == ["visual", "toolbox", "cartographer"]
    assert [item.found for item in resolved] == [False, True, False]


def test_status_payload_shape(fake_ros_sourced, fake_packages):
    fake_packages(["slam_toolbox"])
    payload = adapters.RosAdapter("slam").status(make_config())
    assert payload["domain"] == "slam"
    assert payload["kind"] == "ros"
    assert payload["total"] == 3
    assert payload["installed"] == 1
    assert payload["ros_distro"] == "fake"
    assert payload["ros_sourced"] is True
    toolbox = next(c for c in payload["capabilities"] if c["key"] == "toolbox")
    assert toolbox["found"] is True and toolbox["how"] == "package"


def test_sim_status_reports_launcher_and_root(fake_isaac_tree):
    payload = adapters.SimAdapter("physics").status(state.cfg())
    assert payload["root"] == str(fake_isaac_tree)
    assert payload["launcher"] == str(fake_isaac_tree / "python.sh")
    assert payload["installed"] >= 2  # physx + newton exist in the fake tree


# -- RosAdapter.command ---------------------------------------------------


def test_ros_command_builds_a_launch_line(fake_ros_sourced, fake_packages):
    fake_packages(["slam_toolbox"])
    argv, env = adapters.RosAdapter("slam").command(make_config(), "toolbox", ["--ros-args"])
    assert argv == [
        fake_ros_sourced["binary"],
        "launch",
        "slam_toolbox",
        "online_async_launch.py",
        "--ros-args",
    ]
    assert env == {}  # already sourced: nothing to inject


def test_ros_command_supplies_a_sourced_env_when_needed(
    fake_ros_sourced, fake_packages, monkeypatch
):
    fake_packages(["slam_toolbox"])
    monkeypatch.delenv("AMENT_PREFIX_PATH", raising=False)
    argv, env = adapters.RosAdapter("slam").command(make_config(), "toolbox", [])
    assert argv[1] == "launch"
    assert env.get("CAASI_FAKE_SOURCED") == "1"


def test_ros_command_honours_a_catalog_override(fake_ros_sourced, fake_packages):
    fake_packages(["isaac_ros_visual_slam_v4"])
    cfg = make_config(
        {
            "catalog": {
                "slam": {
                    "visual": {
                        "packages": ["isaac_ros_visual_slam_v4"],
                        "launch": ["isaac_ros_visual_slam_v4", "visual_slam.launch.py"],
                    }
                }
            }
        }
    )
    argv, _ = adapters.RosAdapter("slam").command(cfg, "visual", [])
    assert argv[-2:] == ["isaac_ros_visual_slam_v4", "visual_slam.launch.py"]


def test_ros_command_missing_capability(fake_ros_sourced, fake_packages):
    fake_packages([])
    with pytest.raises(adapters.AdapterError):
        adapters.RosAdapter("slam").command(make_config(), "visual", [])


def test_ros_command_unknown_capability(fake_ros_sourced, fake_packages):
    fake_packages([])
    with pytest.raises(adapters.AdapterError):
        adapters.RosAdapter("slam").command(make_config(), "nope", [])


def test_ros_command_without_a_launch_file(fake_ros_sourced, fake_packages):
    fake_packages(["isaac_ros_nitros"])
    with pytest.raises(adapters.AdapterError):
        adapters.RosAdapter("nitros").command(make_config(), "core", [])


# -- SimAdapter.command ---------------------------------------------------


def test_sim_launcher_from_the_tool_registry(fake_isaac_tree):
    adapter = adapters.SimAdapter("physics")
    assert adapter.launcher(state.cfg()) == str(fake_isaac_tree / "python.sh")


def test_sim_launcher_falls_back_to_the_current_interpreter():
    assert adapters.SimAdapter("warp").launcher(make_config()) == sys.executable


def test_sim_launcher_is_none_without_a_tool(fake_isaac_tree, monkeypatch):
    monkeypatch.delenv("CAASI_CONFIG", raising=False)
    state.reset()
    assert adapters.SimAdapter("physics").launcher(state.cfg()) is None


def test_sim_command_uses_the_resolved_script(fake_isaac_tree):
    cfg = state.cfg()
    cfg.set("catalog.physics.newton.script", "isaac-sim.newton.sh")
    argv, env = adapters.SimAdapter("physics").command(cfg, "newton", ["scene.usd"])
    assert argv == [
        str(fake_isaac_tree / "python.sh"),
        str(fake_isaac_tree / "isaac-sim.newton.sh"),
        "scene.usd",
    ]
    assert env == {}


def test_sim_command_uses_a_resolved_binary(fake_usd_tools):
    argv, env = adapters.SimAdapter("usd").command(state.cfg(), "usdcat", ["a.usd"])
    assert argv[0] == str(fake_usd_tools / "usdcat")
    assert argv[1:] == ["a.usd"]
    assert env == {}


def test_sim_command_missing_capability(fake_isaac_tree):
    with pytest.raises(adapters.AdapterError):
        adapters.SimAdapter("physics").command(state.cfg(), "mujoco", [])


def test_sim_command_unknown_capability(fake_isaac_tree):
    with pytest.raises(adapters.AdapterError):
        adapters.SimAdapter("physics").command(state.cfg(), "nope", [])


def test_sim_command_without_a_launcher(monkeypatch, tmp_path):
    monkeypatch.delenv("CAASI_CONFIG", raising=False)
    state.reset()
    cfg = state.cfg()
    cfg.set("catalog.physics.physx.paths", [str(tmp_path)])
    cfg.set("catalog.physics.physx.script", "nope.py")
    with pytest.raises(adapters.AdapterError):
        adapters.SimAdapter("physics").command(cfg, "physx", [])


def test_sim_command_without_a_script(tmp_path):
    cfg = make_config(
        {"catalog": {"warp": {"warp": {"modules": [], "paths": [str(tmp_path)]}}}}
    )
    with pytest.raises(adapters.AdapterError):
        adapters.SimAdapter("warp").command(cfg, "warp", [])


# -- doctor results -------------------------------------------------------


def test_check_returns_one_result_per_capability(fake_ros_sourced, fake_packages):
    fake_packages(["slam_toolbox"])
    results = adapters.RosAdapter("slam").check(make_config())
    assert len(results) == 3
    assert all(r.section == "accelerated" for r in results)
    by_label = {r.name: r for r in results}
    assert by_label["SLAM Toolbox"].status == "ok"
    assert by_label["Visual SLAM (Isaac ROS)"].status == "fail"  # core capability
    assert by_label["Cartographer"].status == "skip"  # optional capability


def test_check_detail_names_the_upstream_targets(fake_ros_sourced, fake_packages):
    fake_packages([])
    results = adapters.RosAdapter("slam").check(make_config())
    cartographer = next(r for r in results if r.name == "Cartographer")
    assert "cartographer_ros" in cartographer.detail


def test_check_hint_points_at_the_catalog_override(fake_ros_sourced, fake_packages):
    fake_packages([])
    results = adapters.RosAdapter("slam").check(make_config())
    visual = next(r for r in results if r.name == "Visual SLAM (Isaac ROS)")
    assert "catalog.slam.visual.packages" in visual.hint


def test_check_is_a_single_skip_without_the_ros_cli(monkeypatch):
    monkeypatch.setattr(catalog.ros, "find_ros2_binary", lambda: None)
    results = adapters.RosAdapter("slam").check(make_config())
    assert len(results) == 1
    assert results[0].status == "skip"
    assert results[0].section == "accelerated"


def test_check_for_a_sim_domain(fake_isaac_tree):
    results = adapters.SimAdapter("physics").check(state.cfg())
    assert all(r.section == "physics" for r in results)
    by_label = {r.name: r for r in results}
    assert by_label["PhysX"].status == "ok"
    assert by_label["Newton"].status == "ok"
    assert by_label["MuJoCo"].status == "skip"


def test_check_for_the_assets_domain(fake_usd_tools):
    results = adapters.SimAdapter("usd").check(state.cfg())
    assert all(r.section == "assets" for r in results)
    by_label = {r.name: r for r in results}
    assert by_label["usdcat"].status == "ok"
    assert by_label["usdview"].status == "ok"
