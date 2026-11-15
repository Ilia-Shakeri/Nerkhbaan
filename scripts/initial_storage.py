"""Mount existing, ownership-marked initial-deployment filesystems. Never format."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess


def command(args: list[str]) -> str:
    return subprocess.check_output(args, text=True, timeout=30).strip()


def regular(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0:
        raise ValueError("Storage file identity rejected")


def validate(root: Path, manifest: dict, owner: str) -> list[dict]:
    if root != Path("/opt/nerkhbaan") or root.is_symlink() or not re.fullmatch(r"[a-f0-9]{32}", owner):
        raise ValueError("Unknown initial deployment root or owner")
    if manifest.get("owner") != owner:
        raise ValueError("Storage ownership changed")
    records = manifest["filesystems"]
    if len(records) != 2 or {r["name"] for r in records} != {"data", "backup"}:
        raise ValueError("Unexpected filesystems")
    for row in records:
        image, mount = Path(row["image"]), Path(row["mount"])
        if image != root / "storage" / (row["name"] + ".ext4") or mount != root / "storage" / row["name"]:
            raise ValueError("Storage path changed")
        regular(image)
        if image.stat().st_size != row["bytes"] or row["bytes"] != {"data": 3 * 1024**3, "backup": 1024**3}[row["name"]]:
            raise ValueError("Storage size changed")
        if mount.is_symlink() or not mount.is_dir():
            raise ValueError("Storage mount path changed")
        if command(["blkid", "-s", "UUID", "-o", "value", str(image)]) != row["uuid"]:
            raise ValueError("Storage filesystem identity changed")
    return records


def start(root: Path) -> None:
    if os.geteuid() != 0:
        raise ValueError("Root storage operator required")
    regular(root / ".owner")
    regular(root / "storage-manifest.private.json")
    owner = (root / ".owner").read_text().strip()
    rows = validate(root, json.loads((root / "storage-manifest.private.json").read_text()), owner)
    for row in rows:
        image, mount = Path(row["image"]), Path(row["mount"])
        if os.path.ismount(mount):
            device = command(["findmnt", "-n", "-o", "SOURCE", "--target", str(mount)])
        else:
            if list(mount.iterdir()):
                raise ValueError("Unmounted storage path is not empty")
            devices = json.loads(command(["losetup", "--json", "--list", "--output", "NAME,BACK-FILE,DIO"]))["loopdevices"] or []
            matching = [d for d in devices if d.get("back-file") == str(image)]
            if len(matching) > 1:
                raise ValueError("Duplicate storage attachment")
            device = matching[0]["name"] if matching else command(["losetup", "--find", "--show", "--direct-io=on", str(image)])
        if not re.fullmatch(r"/dev/loop[0-9]+", device):
            raise ValueError("Unexpected storage device")
        meta = json.loads(command(["losetup", "--json", "--output", "NAME,BACK-FILE,DIO", device]))["loopdevices"][0]
        if meta["back-file"] != str(image) or meta["dio"] != 1:
            raise ValueError("Storage attachment identity or direct I/O changed")
        if not os.path.ismount(mount):
            command(["mount", "-o", "nodev,nosuid,noexec", device, str(mount)])
        flags = set(command(["findmnt", "-n", "-o", "OPTIONS", "--target", str(mount)]).split(","))
        if not {"nodev", "nosuid", "noexec"}.issubset(flags):
            raise ValueError("Storage mount protection changed")
        regular(mount / ".nerkhbaan-owner")
        if (mount / ".nerkhbaan-owner").read_text().strip() != owner:
            raise ValueError("Mounted filesystem ownership changed")
    print(json.dumps({"mounted": len(rows), "owner_verified": True, "formatted": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    start(parser.parse_args().root)
