"""Tests for `caasi.lock`: resolved environment evidence (§56-57, §7.2)."""

from __future__ import annotations

from caasi.core import check, lock
from caasi.core import manifest as manifests
from caasi.core.config import Config


def _project(tmp_path, *, requires=None, tested=None, name="demo", version="0.1.0"):
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    manifests.write(
        root,
        manifests.Manifest(
            name=name,
            version=version,
            requires=dict(requires or {}),
            tested=list(tested or []),
        ),
    )
    return root


# -- write / read -------------------------------------------------------------


def test_write_then_read_roundtrip(tmp_path):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    path = lock.write(root, {"isaac_sim": "6.0.1", "python": "3.12.3"})
    assert path == root / "caasi.lock"
    assert path.is_file()
    document = lock.read(root)
    assert document["resolved"] == {"isaac_sim": "6.0.1", "python": "3.12.3"}


def test_document_shape(tmp_path):
    root = _project(
        tmp_path,
        requires={"isaac_sim": ">=5.0"},
        tested=[{"component": "isaac_sim", "version": "6.0.1", "status": "verified"}],
    )
    lock.write(root, {"isaac_sim": "6.0.1"})
    document = lock.read(root)
    assert document["schema"] == lock.SCHEMA == 1
    assert document["project"] == {"name": "demo", "version": "0.1.0"}
    assert document["required"] == {"isaac_sim": ">=5.0"}
    assert document["resolved"] == {"isaac_sim": "6.0.1"}
    assert document["verified"] == [
        {"component": "isaac_sim", "version": "6.0.1", "status": "verified"}
    ]
    assert document["collected_at"].endswith("+00:00")


def test_read_returns_none_when_absent(tmp_path):
    assert lock.read(tmp_path) is None


def test_read_returns_none_when_malformed(tmp_path):
    (tmp_path / lock.LOCK_FILE).write_text("not: valid: yaml", encoding="utf-8")
    assert lock.read(tmp_path) is None

    (tmp_path / lock.LOCK_FILE).write_text("- just\n- a list\n", encoding="utf-8")
    assert lock.read(tmp_path) is None


def test_write_overwrites_a_previous_lock(tmp_path):
    root = _project(tmp_path)
    lock.write(root, {"python": "3.11.0"})
    lock.write(root, {"python": "3.12.3"})
    assert lock.read(root)["resolved"] == {"python": "3.12.3"}


# -- resolve ------------------------------------------------------------------


def test_resolve_covers_baseline_and_requires(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"torch": ">=2.0", "isaac_sim": ">=5.0"})
    seen = []

    def fake_detect(config, name):
        seen.append(name)
        return f"v-{name}"

    monkeypatch.setattr(check, "detect", fake_detect)
    resolved = lock.resolve(Config.load(), root)

    # every baseline component plus every requirement, without duplicates
    assert seen == list(dict.fromkeys([*lock.BASELINE, "isaac_sim", "torch"]))
    for name in lock.BASELINE:
        assert resolved[name] == f"v-{name}"
    assert resolved["torch"] == "v-torch"


def test_resolve_skips_undetected_components(tmp_path, monkeypatch):
    root = _project(tmp_path, requires={"isaac_sim": ">=5.0"})
    monkeypatch.setattr(check, "detect", lambda config, name: "3.12.3" if name == "python" else None)
    assert lock.resolve(Config.load(), root) == {"python": "3.12.3"}


def test_resolve_honours_explicit_names(tmp_path, monkeypatch):
    root = _project(tmp_path)
    seen = []
    monkeypatch.setattr(check, "detect", lambda config, name: seen.append(name) or "1.0")
    resolved = lock.resolve(Config.load(), root, names=["docker"])
    assert seen[0] == "docker"
    assert resolved["docker"] == "1.0"


def test_resolve_without_a_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "detect", lambda config, name: None)
    assert lock.resolve(Config.load(), tmp_path) == {}
    document = lock.build_document(tmp_path, {})
    assert document["project"] == {"name": "", "version": "0.0.0"}
    assert document["required"] == {}
