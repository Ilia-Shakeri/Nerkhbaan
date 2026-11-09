"""Prepare and verify a private, hash-bound relocation kit; never contact a host."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from datetime import UTC, datetime

ROOT = Path(__file__).resolve().parents[1]
DUMP_SHA256 = "923e0e54efe3571798a96b4a202dfce6126fb1dedeb747ca2e0caec5d9bbfc1b"
SELECTED = ("production.dump", "database-roles.private.sql", "tls-certificates.private.tar",
            "configuration/configuration-2.private.env", "configuration/configuration-3.private.env",
            "configuration/paths.private.json", "local-restore-result.json")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def child(root, relative):
    value = PurePosixPath(relative)
    if value.is_absolute() or not value.parts or any(p in {"..", "."} or ":" in p or "\\" in p for p in value.parts):
        raise ValueError("Unsafe bundle path")
    path = root.joinpath(*value.parts)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Bundle link escapes its directory")
    return path


def protect(path):
    if os.name == "nt":
        sid = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True).strip().split(",")[-1].strip('"')
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       check=True, capture_output=True)
    else:
        path.chmod(0o700)


def verified_backup(backup):
    records = json.loads((backup / "manifest.json").read_text(encoding="utf8"))["files"]
    mapping = {r["path"]: r for r in records}
    if len(mapping) != len(records):
        raise ValueError("Duplicate backup manifest entries")
    for name in SELECTED:
        path = child(backup, name)
        record = mapping[name]
        if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
            raise ValueError("Backup file failed integrity: " + name)
    if digest(backup / "production.dump") != DUMP_SHA256:
        raise ValueError("Unexpected October 31 snapshot identity")
    receipt = json.loads((backup / "local-restore-result.json").read_text(encoding="utf8"))
    if not receipt["passed"] or receipt["dump_sha256"] != DUMP_SHA256 or receipt["migrations"] != 10 or receipt["public_tables"] != 55:
        raise ValueError("Snapshot restore receipt is not the reviewed one")
    return mapping


def verify(kit):
    data = json.loads((kit / "KIT_MANIFEST.json").read_text(encoding="utf8"))
    if data.get("kind") != "nerkhbaan-private-host-move-v1" or data.get("live_ready") is not False:
        raise ValueError("Unknown relocation kit")
    names = [row["path"] for row in data["files"]]
    required = {"backup/" + name for name in SELECTED} | {"source.tar", "original-backup-manifest.json"}
    if len(names) != len(set(names)) or set(names) != required:
        raise ValueError("Missing, extra or duplicate relocation entries")
    if not re.fullmatch(r"[0-9a-f]{40}", data.get("source_commit", "")):
        raise ValueError("Missing fixed source revision")
    for row in data["files"]:
        path = child(kit, row["path"])
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("Relocation kit integrity failed: " + row["path"])
    if digest(kit / "backup/production.dump") != DUMP_SHA256:
        raise ValueError("Relocation snapshot changed")
    return data


def prepare(backup, output):
    backup, output = backup.resolve(strict=True), output.resolve()
    if output.is_relative_to(ROOT) or output.is_relative_to(backup) or backup.is_relative_to(output):
        raise ValueError("Private kit must be outside source and original backup")
    verified_backup(backup)
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("Commit reviewed source before packaging it")
    output.mkdir(parents=True, exist_ok=False)
    protect(output)
    for name in SELECTED:
        target = child(output, "backup/" + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(child(backup, name), target)
        if os.name != "nt":
            target.chmod(0o600)
    shutil.copyfile(backup / "manifest.json", output / "original-backup-manifest.json")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subprocess.run(["git", "archive", "--format=tar", "--prefix=source/", "-o", str(output / "source.tar"), commit], cwd=ROOT, check=True)
    files = [{"path": p.relative_to(output).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)}
             for p in sorted(output.rglob("*")) if p.is_file()]
    data = {"kind": "nerkhbaan-private-host-move-v1", "created_at": datetime.now(UTC).isoformat(),
            "source_commit": commit, "live_ready": False, "files": files,
            "scope": "Nerkhbaan only; other rescued projects are excluded",
            "restore_receipt": "backup/local-restore-result.json",
            "minimum_host": {"architecture": "x86_64", "ram_gib": 4, "cpus": 2, "disk_gb": 40}}
    (output / "KIT_MANIFEST.json").write_text(json.dumps(data, indent=2), encoding="utf8")
    verify(output)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pack", "verify"))
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "pack" and args.backup is None:
        parser.error("--backup is required for pack")
    data = prepare(args.backup, args.output) if args.action == "pack" else verify(args.output)
    print(json.dumps({"verified": True, "files": len(data["files"]), "source_commit": data["source_commit"],
                      "live_ready": False, "private_directory": str(args.output)}))


if __name__ == "__main__":
    main()
