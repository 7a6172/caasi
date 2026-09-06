"""Viewer orchestration: detect and launch existing visualization tools.

Caasi never implements a viewer itself — it finds the right tool (RViz 2,
Foxglove Studio, Open3D) and launches it against a run or recorded data.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..utils import pydist, shell

VIEWER_NAMES = ("rviz", "foxglove", "open3d")

MESH_EXTS = {".obj", ".stl", ".gltf", ".glb", ".fbx", ".off"}
POINT_EXTS = {".ply", ".pcd", ".pts", ".xyz", ".xyzn"}

OPEN3D_VIEW_SNIPPET = (
    "import sys, open3d as o3d; p = sys.argv[1];"
    " m = ('.obj', '.stl', '.gltf', '.glb', '.fbx', '.off');"
    " g = o3d.io.read_triangle_mesh(p) if p.lower().endswith(m)"
    " else o3d.io.read_point_cloud(p);"
    " o3d.visualization.draw_geometries([g])"
)

# Files every run directory contains (run bookkeeping, not recorded data).
_RUN_FILES = {"manifest.yaml", "run.sh", "stdout.log", "stderr.log", "exit_code"}


def viewer_binary(name: str) -> str | None:
    """Locate the executable for a viewer (None when not installed)."""
    if name == "rviz":
        return shell.which("rviz2")
    if name == "foxglove":
        return shell.which("foxglove") or shell.which("foxglove-studio")
    if name == "open3d":
        if pydist.pip_version("open3d", "open3d-cpu"):
            return sys.executable
        return None
    return None


def find_viewer(name: str | None = None) -> tuple[str | None, str | None]:
    """Return (viewer name, binary) for *name* or the first available viewer."""
    names = (name,) if name else VIEWER_NAMES
    for candidate in names:
        binary = viewer_binary(candidate)
        if binary:
            return candidate, binary
    return None, None


def viewer_command(name: str, binary: str, target: Path | None = None) -> list[str]:
    if name == "rviz":
        return [binary, *(["-d", str(target)] if target else [])]
    if name == "foxglove":
        return [binary]
    return [binary, "-c", OPEN3D_VIEW_SNIPPET, str(target)]


def launch(command: list[str], env: dict[str, str] | None = None) -> int:
    """Launch the viewer detached; returns its PID."""
    proc = subprocess.Popen(
        command,
        env={**os.environ, **(env or {})},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def recorded_artifacts(run_dir: Path) -> list[Path]:
    """Recorded files in the run directory (beyond the standard bookkeeping)."""
    if not run_dir.is_dir():
        return []
    files: list[Path] = []
    for child in sorted(run_dir.iterdir()):
        if child.name in _RUN_FILES:
            continue
        if child.is_file():
            files.append(child)
        else:
            files.extend(sorted(p for p in child.rglob("*") if p.is_file()))
    return files


def find_3d_file(paths: list[Path]) -> Path | None:
    """First 3D data file (mesh or point cloud) below the given paths."""
    for base in paths:
        candidates = base.rglob("*") if base.is_dir() else [base]
        for candidate in sorted(candidates):
            if candidate.is_file() and candidate.suffix.lower() in MESH_EXTS | POINT_EXTS:
                return candidate
    return None
