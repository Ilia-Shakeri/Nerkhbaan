"""Portable local access to the existing release tools and pinned target."""
from __future__ import annotations

import importlib.util
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGET = "deploy@87.248.130.63"
PORT = "9011"
LEGACY_CONTROL_SHA256 = "c948fa889c567563e7b1d6a8f21cedd364b4743d9f1117a22bcd8d0e36498e43"


class OperatorCommandFailed(RuntimeError):
    def __init__(self, result: subprocess.CompletedProcess):
        super().__init__("Target command failed; no automatic retry")
        self.result = result


def workspace_paths(root: Path = ROOT) -> dict[str, Path]:
    root = root.resolve(strict=True)
    package = json.loads((root / "package.json").read_text(encoding="utf8"))
    if package.get("name") != "nerkhbaan-monorepo":
        raise ValueError("Unexpected repository identity")
    layout = root.parent
    paths = {"repo": root, "delivery": layout / "delivery", "delivery_desktop": layout / "delivery-desktop"}
    if not all(path.is_dir() for path in paths.values()):
        raise ValueError("Expected migrated workspace layout; do not guess another checkout")
    return paths


def source_address(preferred: str = "192.168.0.62") -> str:
    """Choose an address already present; never change an interface or route."""
    address = ipaddress.ip_address(preferred)
    if address.version != 4 or address.is_unspecified or address.is_loopback:
        raise ValueError("An explicit local IPv4 address is required")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((str(address), 0))
    return str(address)


def ssh_arguments(source_ip: str = "192.168.0.62") -> list[str]:
    address = source_address(source_ip)
    return ["ssh", "-p", PORT, "-b", address, "-o", "IPQoS=none",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=20",
            "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3", TARGET]


def ssh_python(code: str, *, timeout: int = 120, source_ip: str = "192.168.0.62") -> str:
    compile(code, "reviewed-target-inspection", "exec")
    result = subprocess.run([*ssh_arguments(source_ip), "python3 -"], input=code,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Error output may contain private configuration; callers retain it privately.
        raise OperatorCommandFailed(result)
    return result.stdout


def release_control():
    """Load the historical helper unchanged, rebinding only workstation paths."""
    paths = workspace_paths()
    helper = paths["delivery_desktop"] / "release-2.8.13-20261021" / "release_control.py"
    if not helper.is_file():
        raise ValueError("Reviewed release helper is missing")
    if hashlib.sha256(helper.read_bytes()).hexdigest() != LEGACY_CONTROL_SHA256:
        raise ValueError("Reviewed release helper hash changed")
    spec = importlib.util.spec_from_file_location("existing_release_control", helper)
    if spec is None or spec.loader is None:
        raise ValueError("Release helper cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = paths["repo"]
    module.ssh_python = ssh_python
    return module


if __name__ == "__main__":
    print(json.dumps({name: str(path) for name, path in workspace_paths().items()}))
