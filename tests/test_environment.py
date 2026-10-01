"""Tests for core/environment.py (collection) and core/fingerprint.py (hashing/storage/compare)."""

from __future__ import annotations

import copy

import yaml

from caasi import state
from caasi.core import environment, fingerprint


# -- collect ----------------------------------------------------------------

def test_collect_shape_and_sections():
    collected = environment.collect(state.cfg(), sections=("system", "python", "git"))
    assert list(collected) == ["system", "python", "git"]  # SECTION_ORDER respected
    assert {"os", "kernel", "arch", "hostname"} <= set(collected["system"])
    assert {"version", "executable", "venv", "packages"} <= set(collected["python"])
    assert {"installed", "version"} <= set(collected["git"])


def test_collect_unknown_section_ignored():
    collected = environment.collect(state.cfg(), sections=("bogus", "system"))
    assert list(collected) == ["system"]


def test_collect_all_sections_degrades_never_raises():
    collected = environment.collect(state.cfg())
    assert list(collected) == list(environment.SECTION_ORDER)
    for section, data in collected.items():
        assert isinstance(data, dict), section


def test_collect_gpu_with_fake_nvidia_smi(fake_nvidia_smi):
    collected = environment.collect(state.cfg(), sections=("gpu", "drivers"))
    device = collected["gpu"]["devices"][0]
    assert device["name"] == "FakeGPU RTX 9090"
    assert device["driver_version"] == "580.99"
    assert collected["drivers"] == {"nvidia": "580.99", "cuda": "13.0"}


def test_collect_gpu_without_nvidia_smi(no_nvidia_smi):
    collected = environment.collect(state.cfg(), sections=("gpu", "drivers"))
    assert collected["gpu"]["devices"] == []
    assert collected["drivers"]["nvidia"] is None


# -- stable_hash --------------------------------------------------------------

def test_stable_hash_deterministic(fake_fingerprint):
    digest = fingerprint.stable_hash(fake_fingerprint)
    assert digest.startswith(fingerprint.HASH_PREFIX)
    assert len(digest) == len(fingerprint.HASH_PREFIX) + 64
    assert digest == fingerprint.stable_hash(copy.deepcopy(fake_fingerprint))


def test_stable_hash_ignores_key_order(fake_fingerprint):
    shuffled = {key: fake_fingerprint[key] for key in reversed(list(fake_fingerprint))}
    assert fingerprint.stable_hash(shuffled) == fingerprint.stable_hash(fake_fingerprint)


def test_stable_hash_excludes_volatile_fields(fake_fingerprint):
    baseline = fingerprint.stable_hash(fake_fingerprint)
    noisy = copy.deepcopy(fake_fingerprint)
    noisy["hardware"]["memory_available_kib"] = 1_000_000
    noisy["collected_at"] = "2026-01-01T00:00:00+00:00"
    noisy["system"]["load_average"] = [0.1, 0.2, 0.3]
    assert fingerprint.stable_hash(noisy) == baseline


def test_stable_hash_normalises_scalars_to_strings(fake_fingerprint):
    numeric = copy.deepcopy(fake_fingerprint)
    numeric["drivers"]["cuda"] = 13.0
    textual = copy.deepcopy(fake_fingerprint)
    textual["drivers"]["cuda"] = "13.0"
    assert fingerprint.stable_hash(numeric) == fingerprint.stable_hash(textual)


def test_stable_hash_sensitive_to_real_changes(fake_fingerprint):
    changed = copy.deepcopy(fake_fingerprint)
    changed["python"]["version"] = "3.11.9"
    assert fingerprint.stable_hash(changed) != fingerprint.stable_hash(fake_fingerprint)


# -- write / load -------------------------------------------------------------

def test_write_load_roundtrip(tmp_path, fake_fingerprint):
    path = fingerprint.write(tmp_path, fake_fingerprint)
    assert path == tmp_path / ".caasi" / "environment" / "fingerprint.json"
    # per-section YAML files
    for section in fake_fingerprint:
        assert (tmp_path / ".caasi" / "environment" / f"{section}.yaml").is_file()
    document = fingerprint.load(tmp_path)
    assert document is not None
    assert document["schema"] == fingerprint.SCHEMA
    assert document["hash"] == fingerprint.stable_hash(fake_fingerprint)
    assert document["environment"] == fake_fingerprint
    assert document["collected_at"]


def test_section_yaml_is_readable(tmp_path, fake_fingerprint):
    fingerprint.write(tmp_path, fake_fingerprint)
    data = yaml.safe_load(
        (tmp_path / ".caasi" / "environment" / "system.yaml").read_text(encoding="utf-8")
    )
    assert data["os"] == "Ubuntu 24.04.3 LTS"


def test_load_missing_returns_none(tmp_path):
    assert fingerprint.load(tmp_path) is None


def test_load_unparsable_returns_none(tmp_path):
    directory = fingerprint.environment_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "fingerprint.json").write_text("{not json", encoding="utf-8")
    assert fingerprint.load(tmp_path) is None


# -- compare ------------------------------------------------------------------

def test_compare_identical(fake_fingerprint):
    assert fingerprint.compare(fake_fingerprint, copy.deepcopy(fake_fingerprint)) == []


def test_compare_reports_leaf_diffs(fake_fingerprint):
    changed = copy.deepcopy(fake_fingerprint)
    changed["python"]["version"] = "3.11.9"
    diffs = fingerprint.compare(fake_fingerprint, changed)
    assert len(diffs) == 1
    assert diffs[0].component == "python"
    assert diffs[0].key == "version"
    assert (diffs[0].left, diffs[0].right) == ("3.12.3", "3.11.9")
    assert diffs[0].to_dict()["component"] == "python"


def test_compare_nested_and_list_paths(fake_fingerprint):
    changed = copy.deepcopy(fake_fingerprint)
    changed["gpu"]["devices"][0]["driver_version"] = "570.00"
    diffs = fingerprint.compare(fake_fingerprint, changed)
    assert [d.key for d in diffs] == ["devices[0].driver_version"]


def test_compare_ignores_volatile_fields(fake_fingerprint):
    noisy = copy.deepcopy(fake_fingerprint)
    noisy["hardware"]["memory_available_kib"] = 1
    noisy["collected_at"] = "later"
    assert fingerprint.compare(fake_fingerprint, noisy) == []


def test_compare_accepts_fingerprint_documents(tmp_path, fake_fingerprint):
    fingerprint.write(tmp_path, fake_fingerprint)
    document = fingerprint.load(tmp_path)
    assert fingerprint.compare(document, fake_fingerprint) == []


def test_compare_missing_section(fake_fingerprint):
    partial = copy.deepcopy(fake_fingerprint)
    del partial["docker"]
    diffs = fingerprint.compare(fake_fingerprint, partial)
    assert diffs
    assert all(d.component == "docker" for d in diffs)
