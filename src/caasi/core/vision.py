"""Vision stack diagnostics: OpenCV, Open3D, ONNX Runtime, TensorRT, ...

Version checks use pip metadata (never imports); functional tests run an
``import`` probe in a subprocess, so the CLI process stays lightweight.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..utils import pydist, shell

# name -> ((pip distribution, import module), ...)
COMPONENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "opencv": (
        ("opencv-python", "cv2"),
        ("opencv-python-headless", "cv2"),
        ("opencv-contrib-python", "cv2"),
    ),
    "open3d": (("open3d", "open3d"), ("open3d-cpu", "open3d")),
    "onnxruntime": (("onnxruntime-gpu", "onnxruntime"), ("onnxruntime", "onnxruntime")),
    "tensorrt": (("tensorrt", "tensorrt"),),
    "pytorch": (("torch", "torch"),),
    "pillow": (("pillow", "PIL"),),
}

PROBE_TIMEOUT = 30.0


@dataclass
class VisionComponent:
    name: str
    installed: bool
    version: str | None = None
    module: str | None = None


def component_status() -> list[VisionComponent]:
    components = []
    for name, dists in COMPONENTS.items():
        version = pydist.pip_version(*[dist for dist, _ in dists])
        components.append(
            VisionComponent(name, bool(version), version, module=dists[0][1])
        )
    return components


def find_component(name: str) -> VisionComponent | None:
    for component in component_status():
        if component.name == name:
            return component
    return None


def probe(python: str, module: str) -> shell.ShellResult:
    """Import *module* in a subprocess and print its version."""
    code = f"import {module}\nprint(getattr({module}, '__version__', 'unknown'))"
    return shell.run_cmd([python, "-c", code], timeout=PROBE_TIMEOUT)
