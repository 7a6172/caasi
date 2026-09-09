"""Shared fixtures: isolated HOME/config environment and a fake nvidia-smi."""

from __future__ import annotations

import os
import stat
import textwrap

import pytest
import yaml
from typer.testing import CliRunner

from caasi.core import catalog, rosenv

CLEAN_ENV_VARS = (
    "CAASI_CONFIG",
    "CAASI_LANG",
    "CAASI_LAYOUT",
    "CAASI_HELP_ORDER",
    "ISAACSIM_PATH",
    "ISAACLAB_PATH",
    "ROS_DISTRO",
    "RMW_IMPLEMENTATION",
    "CONDA_DEFAULT_ENV",
    "AMENT_PREFIX_PATH",
    "COLCON_PREFIX_PATH",
    "ROS_LOCALHOST_ONLY",
    "ROS_DOMAIN_ID",
    "ISAAC_ROS_WS",
    "GR00T_PATH",
    "CAASI_PHYSICS_ENGINE",
    "HF_HOME",
    "CAASI_FAKE_ROS_PACKAGES",
    "CAASI_FAKE_ROS_PREFIX",
    "CAASI_FAKE_ROS_NODES",
    "CAASI_FAKE_ROS_TOPICS",
    "CAASI_FAKE_ROS_TOPIC_TYPES",
    "CAASI_FAKE_ROS_HZ",
    "CAASI_FAKE_ROS_NODE_INFO",
    "CAASI_FAKE_ROS_TOPIC_INFO",
    "CAASI_FAKE_ROS_ACTIONS",
    "CAASI_FAKE_ROS_SERVICES",
    "CAASI_FAKE_ISAAC_PYTHON",
)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Point HOME/XDG at temp dirs and clear tool-detection env vars."""
    home = tmp_path / "home"
    xdg = tmp_path / "xdg"
    home.mkdir()
    xdg.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # Wide terminal so Rich tables are never truncated in tests.
    monkeypatch.setenv("COLUMNS", "200")
    for var in CLEAN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    from caasi import state

    catalog.clear_cache()
    rosenv.clear_cache()
    state.reset()
    yield tmp_path
    catalog.clear_cache()
    rosenv.clear_cache()
    state.reset()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def all_output(result) -> str:
    """Combined stdout/stderr across click versions."""
    out = result.output
    try:
        out += result.stderr
    except (ValueError, AttributeError):
        pass
    return out


FAKE_NVIDIA_SMI = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    # Fake nvidia-smi used by the test-suite.
    for arg in "$@"; do
      case "$arg" in
        --query-gpu=*)
          fields="${arg#--query-gpu=}"
          case "$fields" in
            name)
              echo "FakeGPU RTX 9090" ;;
            index,name)
              echo "0, FakeGPU RTX 9090" ;;
            index,name,memory.total,driver_version)
              echo "0, FakeGPU RTX 9090, 24576, 580.99" ;;
            index,name,driver_version,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw)
              echo "0, FakeGPU RTX 9090, 580.99, 24576, 4096, 20480, 42, 55, 120.50" ;;
            index,name,uuid,serial,pci.bus_id,compute_cap,ecc.mode.current,driver_version)
              echo "0, FakeGPU RTX 9090, GPU-1234, 0123456789, 00000000:01:00.0, 8.6, Disabled, 580.99" ;;
            *)
              echo "0, FakeGPU RTX 9090" ;;
          esac
          exit 0 ;;
        --query-compute-apps=*)
          echo "GPU-1234, 4242, python, 1024"
          exit 0 ;;
      esac
    done
    echo "+-----------------------------------------+"
    echo "| NVIDIA-SMI 580.99    CUDA Version: 13.0 |"
    echo "+-----------------------------------------+"
    exit 0
    """
)


@pytest.fixture
def fake_nvidia_smi(tmp_path, monkeypatch):
    """Put a fake nvidia-smi first on PATH."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "nvidia-smi"
    script.write_text(FAKE_NVIDIA_SMI)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return bin_dir


@pytest.fixture
def no_nvidia_smi(tmp_path, monkeypatch):
    """PATH without nvidia-smi (keeps other binaries reachable)."""
    empty = tmp_path / "emptybin"
    empty.mkdir(exist_ok=True)
    keep = [
        entry
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry and not os.path.exists(os.path.join(entry, "nvidia-smi"))
    ]
    monkeypatch.setenv("PATH", os.pathsep.join([str(empty), *keep]))


# -- fake ROS 2 (sourced) -------------------------------------------------

FAKE_ROS2 = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    # Fake ros2 CLI for the caasi test-suite. Behaviour is driven by env vars
    # pointing at plain text files, so each test declares only what it needs.
    cmd="$1"; shift || true
    pkgs="$CAASI_FAKE_ROS_PACKAGES"
    prefix="${CAASI_FAKE_ROS_PREFIX:-/opt/ros/fake}"

    have_pkg() { [ -n "$pkgs" ] && [ -f "$pkgs" ] && grep -qx -- "$1" "$pkgs"; }
    dump() { [ -n "$1" ] && [ -f "$1" ] && cat "$1"; }

    case "$cmd" in
      pkg)
        sub="$1"; shift || true
        case "$sub" in
          prefix)
            if have_pkg "$1"; then echo "$prefix"; else echo "Package not found" >&2; exit 1; fi;;
          list) dump "$pkgs";;
          *) exit 1;;
        esac;;
      node)
        sub="$1"; shift || true
        case "$sub" in
          list) dump "$CAASI_FAKE_ROS_NODES";;
          info)
            dir="$CAASI_FAKE_ROS_NODE_INFO"
            file="$dir/$(echo "$1" | tr '/' '_').txt"
            if [ -n "$dir" ] && [ -f "$file" ]; then cat "$file"; else echo "Unable to find node" >&2; exit 1; fi;;
          *) exit 1;;
        esac;;
      topic)
        sub="$1"; shift || true
        case "$sub" in
          list)
            if [ "$1" = "-t" ]; then dump "$CAASI_FAKE_ROS_TOPIC_TYPES"; else dump "$CAASI_FAKE_ROS_TOPICS"; fi;;
          info)
            dir="$CAASI_FAKE_ROS_TOPIC_INFO"
            while [ "${1#-}" != "$1" ]; do shift || break; done
            file="$dir/$(echo "$1" | tr '/' '_').txt"
            if [ -n "$dir" ] && [ -f "$file" ]; then cat "$file"; else echo "Unknown topic" >&2; exit 1; fi;;
          hz)
            if [ -n "$CAASI_FAKE_ROS_HZ" ]; then echo "$CAASI_FAKE_ROS_HZ"; else echo "average rate: 30.000"; fi;;
          echo) echo "echo $*";;
          *) exit 1;;
        esac;;
      service)
        sub="$1"; shift || true
        case "$sub" in
          list) dump "$CAASI_FAKE_ROS_SERVICES";;
          *) echo "service $*";;
        esac;;
      action)
        sub="$1"; shift || true
        case "$sub" in
          list) dump "$CAASI_FAKE_ROS_ACTIONS";;
          *) echo "action $sub $*";;
        esac;;
      launch) echo "launch $*";;
      run) echo "run $*";;
      bag) echo "bag $*";;
      *) echo "unknown command" >&2; exit 1;;
    esac
    """
)


@pytest.fixture
def fake_ros_sourced(tmp_path, monkeypatch):
    """A fake ROS distro that *is* sourced (AMENT_PREFIX_PATH points at it).

    Set ``CAASI_FAKE_ROS_PACKAGES`` / ``..._NODES`` / ``..._TOPICS`` to a file
    of lines to control what the fake CLI reports.
    """
    from caasi.core import ros as ros_core

    root = tmp_path / "ros-root"
    distro = root / "fake"
    (distro / "bin").mkdir(parents=True)
    (distro / "setup.bash").write_text(
        f'export AMENT_PREFIX_PATH="{distro}"\n'
        'export ROS_DISTRO="fake"\n'
        'export CAASI_FAKE_SOURCED="1"\n',
        encoding="utf-8",
    )

    script = distro / "bin" / "ros2"
    script.write_text(FAKE_ROS2, encoding="utf-8")
    script.chmod(0o755)

    monkeypatch.setattr(ros_core, "ROS_ROOT", root)
    monkeypatch.setenv("ROS_DISTRO", "fake")
    monkeypatch.setenv("AMENT_PREFIX_PATH", str(distro))

    catalog.clear_cache()
    rosenv.clear_cache()
    yield {
        "root": root,
        "distro": distro,
        "binary": str(script),
        "setup": distro / "setup.bash",
    }
    catalog.clear_cache()
    rosenv.clear_cache()


def write_lines(path, lines):
    """Helper: write a newline-delimited file for the fake ros2 env vars."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


class FakeRos:
    """State for the fake ros2 CLI: each setter writes a file and exports its env var."""

    def __init__(self, tmp_path, monkeypatch):
        self.base = tmp_path / "fake-ros"
        self.node_info_dir = self.base / "node-info"
        self.topic_info_dir = self.base / "topic-info"
        self.node_info_dir.mkdir(parents=True, exist_ok=True)
        self.topic_info_dir.mkdir(parents=True, exist_ok=True)
        self._env = monkeypatch
        prefix = tmp_path / "ros-prefix"
        prefix.mkdir(exist_ok=True)
        self.prefix = prefix
        monkeypatch.setenv("CAASI_FAKE_ROS_PREFIX", str(prefix))
        monkeypatch.setenv("CAASI_FAKE_ROS_NODE_INFO", str(self.node_info_dir))
        monkeypatch.setenv("CAASI_FAKE_ROS_TOPIC_INFO", str(self.topic_info_dir))

    def _set(self, var: str, lines) -> None:
        write_lines(self.base / f"{var.lower()}.txt", list(lines))
        self._env.setenv(var, str(self.base / f"{var.lower()}.txt"))

    def packages(self, *names) -> "FakeRos":
        self._set("CAASI_FAKE_ROS_PACKAGES", names)
        return self

    def nodes(self, *names) -> "FakeRos":
        self._set("CAASI_FAKE_ROS_NODES", names)
        return self

    def topics(self, *names) -> "FakeRos":
        self._set("CAASI_FAKE_ROS_TOPICS", names)
        return self

    def topic_types(self, *lines) -> "FakeRos":
        self._set("CAASI_FAKE_ROS_TOPIC_TYPES", lines)
        return self

    def actions(self, *names) -> "FakeRos":
        self._set("CAASI_FAKE_ROS_ACTIONS", names)
        return self

    def services(self, *names) -> "FakeRos":
        self._set("CAASI_FAKE_ROS_SERVICES", names)
        return self

    def hz(self, text: str) -> "FakeRos":
        self._env.setenv("CAASI_FAKE_ROS_HZ", text)
        return self

    def node_info(self, node: str, text: str) -> "FakeRos":
        (self.node_info_dir / f"{node.replace('/', '_')}.txt").write_text(
            textwrap.dedent(text), encoding="utf-8"
        )
        return self

    def topic_info(self, topic: str, text: str) -> "FakeRos":
        (self.topic_info_dir / f"{topic.replace('/', '_')}.txt").write_text(
            textwrap.dedent(text), encoding="utf-8"
        )
        return self


@pytest.fixture
def fake_ros_world(fake_ros_sourced, tmp_path, monkeypatch):
    """A sourced fake ROS distro plus a :class:`FakeRos` state builder."""
    return FakeRos(tmp_path, monkeypatch)


# -- fake Isaac Sim tree --------------------------------------------------


@pytest.fixture
def fake_isaac_tree(tmp_path, monkeypatch):
    """A tmp dir mimicking an Isaac Sim install, registered in the tool registry."""
    root = tmp_path / "isaacsim"
    (root / "exts" / "omni.replicator.core" / "config").mkdir(parents=True)
    (root / "exts" / "omni.importer.urdf" / "config").mkdir(parents=True)
    (root / "extsPhysics" / "omni.physx" / "config").mkdir(parents=True)
    (root / "extsUser").mkdir(parents=True)
    (root / "extscache").mkdir(parents=True)

    for ext in (
        "exts/omni.replicator.core",
        "exts/omni.importer.urdf",
        "extsPhysics/omni.physx",
    ):
        name = ext.rsplit("/", 1)[-1]
        (root / ext / "config" / "extension.toml").write_text(
            f'[package]\nname = "{name}"\n', encoding="utf-8"
        )

    python_sh = root / "python.sh"
    python_sh.write_text(
        '#!/usr/bin/env bash\nexec "${CAASI_FAKE_ISAAC_PYTHON:-python3}" "$@"\n',
        encoding="utf-8",
    )
    python_sh.chmod(0o755)
    for name in ("isaac-sim.sh", "isaac-sim.newton.sh", "isaac-sim.xr.vr.sh"):
        script = root / name
        script.write_text(f'#!/usr/bin/env bash\necho "{name} $*"\n', encoding="utf-8")
        script.chmod(0o755)

    cfg_file = tmp_path / "caasi-isaac.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {
                "tools": {
                    "isaacsim": {
                        "default": "5.1",
                        "versions": {"5.1": {"path": str(root), "python": str(python_sh)}},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAASI_CONFIG", str(cfg_file))
    catalog.clear_cache()
    state_reset()
    yield root
    catalog.clear_cache()


def state_reset():
    from caasi import state

    state.reset()


# -- fake USD tooling -----------------------------------------------------


@pytest.fixture
def fake_usd_tools(tmp_path, monkeypatch):
    """Put fake usdcat / usdchecker / check_urdf first on PATH."""
    bin_dir = tmp_path / "usdbin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("usdcat", "usdchecker", "usdview", "usdrecord", "check_urdf", "xacro"):
        script = bin_dir / name
        script.write_text(f'#!/usr/bin/env bash\necho "{name} $*"\n', encoding="utf-8")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    catalog.clear_cache()
    yield bin_dir
    catalog.clear_cache()
