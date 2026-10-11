"""Build a reviewable source delivery, excluding local data and credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DENIED_DIRECTORIES = {".git", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", ".local-keys", "_archives", "dist", "build", "release", "release-unsigned", "coverage", "test-results", "playwright-report", "backups", "data", "delivery"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3", ".dump", ".bak", ".backup", ".log", ".zip", ".7z", ".gz", ".bz2", ".xz", ".tar", ".tgz", ".exe", ".dll", ".so", ".dylib", ".msi", ".whl", ".pyc", ".jsonl", ".har", ".session", ".csv", ".tsv", ".xlsx", ".xls"}
SECRET_PATTERN = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}")
DSN_PATTERN = re.compile(rb"\b(?:postgres(?:ql)?(?:\+[a-z0-9_]+)?|redis)://[^\s/@:]+:([^\s/@]+)@")
DEMO_PASSWORDS = {b"test", b"ci-database-password", b"ci-browser-password", b"nerkhbaan", b"schema", b"password", b"postgres", b"fixture", b"example", b"changeme", b"pw"}
SQL_INIT_FILES = {Path("apps/api/db/init/001_timescale_market_prices.sql"), Path("apps/api/db/init/init.sql")}
SQL_MIGRATION_DIRECTORY = Path("apps/api/db/migrations")


def safe_content(content: bytes) -> bool:
    if SECRET_PATTERN.search(content):
        return False
    return all(match[1] in DEMO_PASSWORDS or re.fullmatch(rb"\$\{[A-Z0-9_]+\}", match[1]) for match in DSN_PATTERN.finditer(content))


def allowed(path: Path) -> bool:
    name = path.name.lower()
    sql_source = path in SQL_INIT_FILES or (path.parent == SQL_MIGRATION_DIRECTORY and re.fullmatch(r"\d{8}_(?:\d{3}_)?[a-z0-9_]+\.sql", path.name))
    return not (set(path.parts) & DENIED_DIRECTORIES or path.suffix.lower() in DENIED_SUFFIXES or (name.startswith(".env") and not name.endswith(".example")) or name in {"operator-gates.evidence.json", "service-account.json", "credentials.json"} or ("session" in name and path.suffix in {".txt", ".json"}) or (path.suffix.lower() == ".sql" and not sql_source))


def build(output: Path) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError("Delivery output already exists; choose a fresh path")
    files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).decode().split("\0")
    records = []
    entries = []
    for name in sorted(set(filter(None, files))):
        relative = Path(name)
        original = ROOT / relative
        source = original.resolve()
        if not allowed(relative) or source == output or not source.is_relative_to(ROOT) or not source.is_file() or original.is_symlink():
            continue
        content = source.read_bytes()
        # Only known demo passwords and literal environment references may remain.
        if not safe_content(content):
            raise ValueError(f"Sensitive content blocked in {relative.as_posix()}")
        record = {"path": relative.as_posix(), "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        records.append(record)
        entries.append((record["path"], content))
    manifest = {"release": (ROOT / "VERSION").read_text().strip(), "kind": "source-delivery", "files": records, "exclusions": sorted(DENIED_DIRECTORIES | DENIED_SUFFIXES), "production_verified": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
        archive.writestr("DELIVERY_MANIFEST.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    with ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Delivery archive failed integrity check")
        for record in records:
            if hashlib.sha256(archive.read(record["path"])).hexdigest() != record["sha256"]:
                raise RuntimeError("Delivery file checksum mismatch")
    return {"release": manifest["release"], "files": len(records), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "output": str(output)}


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("output", type=Path)
    print(json.dumps(build(arguments.parse_args().output), ensure_ascii=False))
