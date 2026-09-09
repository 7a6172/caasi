"""Tests for the capability catalog (core/catalog.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from caasi.core import catalog
from caasi.core.config import Config
from caasi.i18n import en

EXPECTED_DOMAINS = {
    "isaacros",
    "perception",
    "slam",
    "mapping",
    "motion",
    "nitros",
    "physics",
    "warp",
    "groot",
    "cosmos",
    "usd",
    "data",
    "teleop",
    "sdg",
}


def make_config(data: dict | None = None) -> Config:
    return Config(data or {}, [])


@pytest.fixture(autouse=True)
def no_real_ros(monkeypatch):
    """Keep catalog probes off the machine's real ROS install by default."""
    monkeypatch.setattr(catalog.ros, "find_ros2_binary", lambda: None)
    catalog.clear_cache()
    yield
    catalog.clear_cache()


# -- table integrity ------------------------------------------------------


def test_builtin_domains_present():
    assert EXPECTED_DOMAINS == set(catalog.DOMAINS)
    assert {d.key for d in catalog.domains()} >= EXPECTED_DOMAINS


def test_every_domain_has_title_kind_and_capabilities():
    for spec in catalog.domains():
        assert spec.title == f"catalog.domain.{spec.key}"
        assert spec.kind in ("ros", "sim", "lab", "python", "mixed")
        assert spec.capabilities, spec.key


def test_domain_titles_exist_in_message_catalog():
    missing = [s.title for s in catalog.domains() if s.title not in en.MESSAGES]
    assert not missing, missing


def test_every_capability_label_exists_in_message_catalog():
    missing = [
        cap.label
        for spec in catalog.domains()
        for cap in spec.capabilities
        if cap.label not in en.MESSAGES
    ]
    assert not missing, missing


def test_capability_labels_follow_the_convention():
    for spec in catalog.domains():
        for cap in spec.capabilities:
            assert cap.label == f"catalog.{spec.key}.{cap.key}"


def test_capabilities_inherit_the_domain_tool_root():
    assert catalog.capability("physics", "newton").tool == "isaacsim"
    assert catalog.capability("sdg", "replicator").tool == "isaacsim"
    assert catalog.capability("slam", "toolbox").tool is None


# -- lookups --------------------------------------------------------------


def test_unknown_domain_returns_none():
    assert catalog.domain("nope") is None
    assert catalog.capability("nope", "x") is None
    assert catalog.capabilities("nope") == ()
    assert catalog.resolve_domain("nope") == ()


def test_unknown_capability_returns_none():
    assert catalog.capability("slam", "nope") is None
    assert catalog.resolve_capability("slam", "nope") is None
    assert catalog.resolve_capability("nope", "toolbox") is None


def test_capability_lookup():
    cap = catalog.capability("slam", "toolbox")
    assert cap is not None
    assert cap.packages == ("slam_toolbox",)
    assert cap.launch == ("slam_toolbox", "online_async_launch.py")
    assert cap.core is True


def test_resolve_domain_keeps_catalog_order():
    resolved = catalog.resolve_domain("slam")
    assert [item.capability.key for item in resolved] == ["visual", "toolbox", "cartographer"]
    assert all(not item.found for item in resolved)


def test_domain_to_dict_shape():
    payload = catalog.domain("nitros").to_dict()
    assert payload["key"] == "nitros"
    assert payload["kind"] == "ros"
    assert [c["key"] for c in payload["capabilities"]] == ["core", "types", "bridge", "disable"]


def test_resolved_to_dict_shape():
    item = catalog.resolve_capability("slam", "toolbox")
    payload = item.to_dict()
    assert payload["key"] == "toolbox"
    assert payload["found"] is False
    assert payload["how"] is None
    assert payload["launch"] == ["slam_toolbox", "online_async_launch.py"]


# -- probe order ----------------------------------------------------------


def test_resolve_package_wins_over_everything(monkeypatch):
    monkeypatch.setattr(catalog.ros, "find_ros2_binary", lambda: "/bin/ros2")
    monkeypatch.setattr(catalog.ros, "pkg_prefix", lambda name: Path("/opt/ros/fake"))
    monkeypatch.setattr(catalog.shell, "which", lambda name: "/usr/bin/other")
    monkeypatch.setattr(catalog.pydist, "pip_version", lambda *names: "9.9.9")

    cap = catalog.Capability(
        key="k", label="l", packages=("p",), binaries=("b",), modules=("m",), env=("E",)
    )
    resolved = catalog.resolve(cap)
    assert resolved.found and resolved.how == "package"
    assert resolved.value == "/opt/ros/fake"


def test_resolve_binary_when_no_package(monkeypatch):
    monkeypatch.setattr(catalog.shell, "which", lambda name: f"/usr/bin/{name}")
    resolved = catalog.resolve(catalog.Capability(key="k", label="l", binaries=("usdcat",)))
    assert resolved.found and resolved.how == "binary"
    assert resolved.value == "/usr/bin/usdcat"


def test_resolve_module_uses_metadata_only(monkeypatch):
    monkeypatch.setattr(catalog.pydist, "pip_version", lambda *names: "1.4.0")
    resolved = catalog.resolve(catalog.Capability(key="k", label="l", modules=("warp",)))
    assert resolved.found and resolved.how == "module"
    assert resolved.value == "1.4.0"


def test_resolve_env(monkeypatch):
    monkeypatch.setenv("CAASI_TEST_MARKER", "yes")
    resolved = catalog.resolve(
        catalog.Capability(key="k", label="l", env=("CAASI_TEST_MARKER",))
    )
    assert resolved.found and resolved.how == "env"
    assert resolved.value == "yes"


def test_resolve_env_ignores_empty_values(monkeypatch):
    monkeypatch.setenv("CAASI_TEST_MARKER", "")
    resolved = catalog.resolve(
        catalog.Capability(key="k", label="l", env=("CAASI_TEST_MARKER",))
    )
    assert not resolved.found


def test_resolve_path_under_tool_root(tmp_path):
    root = tmp_path / "sim"
    (root / "exts" / "omni.replicator.core").mkdir(parents=True)
    cfg = make_config({"tools": {"isaacsim": {"versions": {"1": {"path": str(root)}}}}})
    cap = catalog.Capability(
        key="k",
        label="l",
        paths=("exts/omni.replicator.core",),
        tool="isaacsim",
    )
    resolved = catalog.resolve(cap, cfg)
    assert resolved.found and resolved.how == "path"
    assert resolved.value == str(root / "exts" / "omni.replicator.core")


def test_resolve_home_glob_without_a_tool_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Isaac-GR00T").mkdir()
    resolved = catalog.resolve(
        catalog.Capability(key="repo", label="l", paths=("~/Isaac-GR00T",))
    )
    assert resolved.found and resolved.how == "path"
    assert resolved.value == str(tmp_path / "Isaac-GR00T")


def test_resolve_path_without_a_tool_root_is_not_found(tmp_path):
    cfg = make_config({})
    resolved = catalog.resolve(
        catalog.Capability(key="k", label="l", paths=("exts/nope",), tool="isaacsim"), cfg
    )
    assert not resolved.found and resolved.value is None


def test_resolve_not_found(monkeypatch):
    monkeypatch.setattr(catalog.shell, "which", lambda name: None)
    monkeypatch.setattr(catalog.pydist, "pip_version", lambda *names: None)
    cap = catalog.Capability(
        key="k", label="l", packages=("nope",), binaries=("nope",), modules=("nope",)
    )
    resolved = catalog.resolve(cap)
    assert not resolved.found
    assert resolved.how == "" and resolved.value is None
    assert resolved.to_dict()["how"] is None


def test_resolve_script_is_independent_of_detection(tmp_path):
    root = tmp_path / "groot"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "finetune.py").write_text("", encoding="utf-8")
    cfg = make_config({"tools": {"groot": {"versions": {"1": {"path": str(root)}}}}})
    cap = catalog.Capability(
        key="train", label="l", script="scripts/finetune.py", tool="groot"
    )
    resolved = catalog.resolve(cap, cfg)
    assert not resolved.found
    assert resolved.script == root / "scripts" / "finetune.py"


def test_resolve_script_missing_file_is_none(tmp_path):
    cfg = make_config({"tools": {"groot": {"versions": {"1": {"path": str(tmp_path)}}}}})
    cap = catalog.Capability(key="train", label="l", script="scripts/nope.py", tool="groot")
    assert catalog.resolve(cap, cfg).script is None


def test_pkg_prefix_is_memoised(monkeypatch):
    monkeypatch.setattr(catalog.ros, "find_ros2_binary", lambda: "/bin/ros2")
    calls: list[str] = []

    def fake_prefix(name: str) -> Path | None:
        calls.append(name)
        return Path("/opt/ros/fake")

    monkeypatch.setattr(catalog.ros, "pkg_prefix", fake_prefix)
    cap = catalog.Capability(key="k", label="l", packages=("slam_toolbox",))
    catalog.resolve(cap)
    catalog.resolve(cap)
    assert calls == ["slam_toolbox"]


# -- overrides ------------------------------------------------------------


def test_override_replaces_a_field_wholesale():
    cfg = make_config(
        {"catalog": {"slam": {"visual": {"packages": ["isaac_ros_visual_slam_v4"]}}}}
    )
    cap = catalog.capability("slam", "visual", cfg)
    assert cap.packages == ("isaac_ros_visual_slam_v4",)
    # untouched fields survive the override
    assert cap.launch == ("isaac_ros_visual_slam", "visual_slam.launch.py")
    assert cap.core is True


def test_override_replaces_launch_and_script():
    cfg = make_config(
        {
            "catalog": {
                "slam": {"toolbox": {"launch": ["slam_toolbox", "offline_launch.py"]}},
                "groot": {"train": {"script": "scripts/tune.py"}},
            }
        }
    )
    assert catalog.capability("slam", "toolbox", cfg).launch == (
        "slam_toolbox",
        "offline_launch.py",
    )
    assert catalog.capability("groot", "train", cfg).script == "scripts/tune.py"


def test_override_accepts_a_bare_string_for_list_fields():
    cfg = make_config({"catalog": {"slam": {"toolbox": {"packages": "my_slam"}}}})
    assert catalog.capability("slam", "toolbox", cfg).packages == ("my_slam",)


def test_override_adds_a_capability():
    cfg = make_config(
        {
            "catalog": {
                "slam": {
                    "custom": {
                        "packages": ["my_slam"],
                        "launch": ["my_slam", "bringup.launch.py"],
                    }
                }
            }
        }
    )
    cap = catalog.capability("slam", "custom", cfg)
    assert cap is not None
    assert cap.packages == ("my_slam",)
    assert cap.launch == ("my_slam", "bringup.launch.py")
    assert cap.label == "catalog.slam.custom"


def test_override_adds_a_domain():
    cfg = make_config({"catalog": {"lidar": {"driver": {"packages": ["velodyne"]}}}})
    spec = catalog.domain("lidar", cfg)
    assert spec is not None
    assert spec.kind == "mixed"
    assert spec.capability("driver").packages == ("velodyne",)
    assert spec.title == "catalog.domain.lidar"


def test_builtins_are_not_mutated_by_overrides():
    cfg = make_config({"catalog": {"slam": {"visual": {"packages": ["x"]}}}})
    assert catalog.capability("slam", "visual", cfg).packages == ("x",)
    assert catalog.DOMAINS["slam"].capability("visual").packages == (
        "isaac_ros_visual_slam",
    )
    assert catalog.capability("slam", "visual").packages == ("isaac_ros_visual_slam",)


def test_domain_setting_default():
    cfg = make_config({"catalog": {"slam": {"default": "toolbox"}}})
    assert catalog.domain_setting("slam", "default", cfg) == "toolbox"
    assert catalog.domain_setting("slam", "default") is None
    assert catalog.domain_setting("slam", "default", cfg, default="visual") == "toolbox"
    assert catalog.domain_setting("motion", "default", cfg, default="cumotion") == "cumotion"


def test_domain_setting_is_not_a_capability():
    cfg = make_config({"catalog": {"slam": {"default": "toolbox"}}})
    assert catalog.capability("slam", "default", cfg) is None
    assert [c.key for c in catalog.capabilities("slam", cfg)] == [
        "visual",
        "toolbox",
        "cartographer",
    ]


def test_non_dict_overrides_are_ignored():
    cfg = make_config({"catalog": "nonsense"})
    assert catalog.overrides_from(cfg) == {}
    assert catalog.domain("slam", cfg) is not None

    cfg = make_config({"catalog": {"slam": "nonsense"}})
    assert catalog.domain("slam", cfg).capability("toolbox") is not None


def test_overrides_from_none_config():
    assert catalog.overrides_from(None) == {}


# -- tool roots -----------------------------------------------------------


def test_tool_root_from_registry(tmp_path):
    cfg = make_config({"tools": {"isaacsim": {"versions": {"1": {"path": str(tmp_path)}}}}})
    assert catalog.tool_root(cfg, "isaacsim") == tmp_path


def test_tool_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAACSIM_PATH", str(tmp_path))
    assert catalog.tool_root(None, "isaacsim") == tmp_path
    assert catalog.tool_root(make_config(), "isaacsim") == tmp_path


def test_tool_root_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ISAACSIM_PATH", str(tmp_path / "nope"))
    assert catalog.tool_root(None, "isaacsim") is None
    assert catalog.tool_root(None, None) is None
    assert catalog.tool_root(None, "unknown_tool") is None
