"""Container image discovery (Docker/Podman delegation, never the SDKs).

caasi only detects a container tool, lists images and builds ``docker run``
commands — execution stays with the container runtime.
"""

from __future__ import annotations

from ..utils import shell

DEFAULT_TIMEOUT = 20.0

# Well-known Isaac ecosystem images (repository references, tags not pinned).
KNOWN_IMAGES: tuple[dict[str, str], ...] = (
    {"image": "nvcr.io/nvidia/isaac-sim", "description": "NVIDIA Isaac Sim (NGC)"},
    {"image": "nvcr.io/nvidia/isaac-lab", "description": "NVIDIA Isaac Lab (NGC)"},
)

LOCAL_FILTER = ("isaac", "isaacsim", "isaaclab")


def find_container_tool() -> str | None:
    """Locate a container runtime (docker first, then podman)."""
    return shell.which("docker") or shell.which("podman")


def daemon_ok(tool: str) -> bool:
    """True when the container daemon answers ``info`` successfully."""
    return shell.run_cmd([tool, "info"], timeout=DEFAULT_TIMEOUT).ok


def nvidia_runtime(tool: str) -> bool:
    """True when the daemon reports an NVIDIA runtime (nvidia-container-toolkit)."""
    result = shell.run_cmd([tool, "info"], timeout=DEFAULT_TIMEOUT)
    if not result.ok:
        return False
    return "nvidia" in result.stdout.lower()


def local_images(tool: str) -> list[str]:
    """List locally available Isaac-related images (``<repo>:<tag>``)."""
    result = shell.run_cmd(
        [tool, "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        timeout=DEFAULT_TIMEOUT,
    )
    if not result.ok:
        return []
    images = []
    for line in result.stdout.splitlines():
        image = line.strip()
        if not image or "<none>" in image:
            continue
        lowered = image.lower()
        if any(key in lowered for key in LOCAL_FILTER):
            images.append(image)
    return images
