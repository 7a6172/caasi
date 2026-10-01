"""Tests for the flat project manifest (core/manifest.py)."""

from __future__ import annotations

import yaml

from caasi.core import manifest as manifests
from caasi.core.config import DEFAULTS


def _write(root, data):
    (root / "caasi.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_round_trip(tmp_path):
    manifest = manifests.Manifest(
        name="warehouse", version="0.1.0", components={"ros2": True}, schema=1
    )
    manifests.write(tmp_path, manifest)
    loaded = manifests.read(tmp_path)
    assert loaded.name == "warehouse"
    assert loaded.version == "0.1.0"
    assert loaded.components == {"ros2": True}
    assert loaded.schema == 1


def test_migrate_legacy_version_int():
    legacy = {"kind": "project", "name": "old", "version": 1}
    migrated = manifests.migrate(legacy)
    assert migrated["schema"] == 1
    assert migrated["version"] == "0.0.0"
    assert migrated["name"] == "old"
    assert "kind" not in migrated
    assert migrated["components"] == {}


def test_migrate_preserves_string_version_and_schema():
    data = {"schema": 1, "name": "x", "version": "1.2.3", "components": {"nav2": True}}
    migrated = manifests.migrate(data)
    assert migrated["version"] == "1.2.3"
    assert migrated["components"] == {"nav2": True}


def test_read_bridges_legacy_without_rewriting(tmp_path):
    _write(tmp_path, {"kind": "project", "name": "legacy", "version": 1})
    loaded = manifests.read(tmp_path)
    assert loaded.schema == 1
    assert loaded.version == "0.0.0"
    assert loaded.name == "legacy"
    # read must not have rewritten the file
    on_disk = yaml.safe_load((tmp_path / "caasi.yaml").read_text())
    assert on_disk["kind"] == "project"
    assert on_disk["version"] == 1


def test_add_component_sets_flag_and_merges_requires(tmp_path):
    manifests.write(tmp_path, manifests.Manifest(name="demo"))
    manifest = manifests.add_component(tmp_path, "isaac_lab")
    assert manifest.components["isaac_lab"] is True
    assert manifest.requires["isaac_lab"] == {"version": ">=2.0"}
    # persisted
    reloaded = manifests.read(tmp_path)
    assert reloaded.registered() == ["isaac_lab"]


def test_add_component_does_not_clobber_existing_requires(tmp_path):
    manifests.write(
        tmp_path,
        manifests.Manifest(name="demo", requires={"isaac_lab": {"version": ">=9.9"}}),
    )
    manifest = manifests.add_component(tmp_path, "isaac_lab")
    # user value preserved
    assert manifest.requires["isaac_lab"]["version"] == ">=9.9"


def test_remove_component(tmp_path):
    manifests.write(tmp_path, manifests.Manifest(name="demo", components={"nav2": True}))
    manifest = manifests.remove_component(tmp_path, "nav2")
    assert "nav2" not in manifest.components
    assert manifests.read(tmp_path).registered() == []


def test_manifest_keys_disjoint_from_config_keys():
    config_keys = set(DEFAULTS)
    manifest_keys = set(manifests.FIELD_ORDER)
    assert config_keys.isdisjoint(manifest_keys)


def test_write_preserves_extra_config_layer_keys(tmp_path):
    _write(tmp_path, {"schema": 1, "name": "demo", "version": "0.0.0", "layout": "plain"})
    manifest = manifests.read(tmp_path)
    manifest.components["ros2"] = True
    manifests.write(tmp_path, manifest)
    on_disk = yaml.safe_load((tmp_path / "caasi.yaml").read_text())
    assert on_disk["layout"] == "plain"  # config-layer key survived
    assert on_disk["components"]["ros2"] is True
