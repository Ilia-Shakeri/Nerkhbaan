"""Restore the pinned rescue snapshot into a fresh, disconnected local test database."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from prepare_host_move import ROOT, digest, protect, verify

IMAGE = "sha256:61f891691050da6032023c01ea885730eeeba06b7c17b403e7d0b9c49c37dfe9"
LABEL = "nerkhbaan.host-move-rehearsal"


def run(kit, output, cli):
    verify(kit)
    output = output.resolve()
    if output.is_relative_to(ROOT) or output.is_relative_to(kit.resolve()) or kit.resolve().is_relative_to(output):
        raise ValueError("Use a fresh private evidence directory outside source and kit")
    output.mkdir(parents=True, exist_ok=False)
    protect(output)
    token = uuid.uuid4().hex
    name = "nerkhbaan-move-drill-" + token
    volume = name + "-data"
    commands = 0

    def docker(*args, stdin=None, timeout=120):
        nonlocal commands
        commands += 1
        result = subprocess.run([*cli, *args], stdin=stdin, capture_output=True, timeout=timeout)
        if result.returncode:
            (output / f"failure-{commands}.private.log").write_bytes(result.stdout + result.stderr)
            raise RuntimeError("Restore command failed; private failure log retained")
        return result.stdout.decode("utf8").strip()

    def owned():
        info = json.loads(docker("inspect", name))[0]
        if (info["Image"] != IMAGE or info["Config"]["Labels"].get(LABEL) != token
                or info["HostConfig"]["NetworkMode"] != "none" or info["HostConfig"]["PortBindings"]
                or info["HostConfig"]["Memory"] != 768 * 1024 * 1024
                or not any(m.get("Name") == volume and m["Destination"] == "/var/lib/postgresql/data"
                           for m in info["Mounts"])):
            raise ValueError("Owned restore identity or isolation changed")
        return info

    def sql(query):
        owned()
        return docker("exec", name, "psql", "-X", "-U", "postgres", "-d", "restore_drill", "-At",
                      "-v", "ON_ERROR_STOP=1", "-c", query)

    started = datetime.now(UTC).isoformat()
    try:
        if json.loads(docker("image", "inspect", IMAGE))[0]["Id"] != IMAGE:
            raise ValueError("Reviewed restore image is absent")
        docker("volume", "create", "--label", LABEL + "=" + token, volume)
        docker("run", "-d", "--name", name, "--label", LABEL + "=" + token,
               "--network", "none", "--memory", "768m", "--cpus", "0.75", "--shm-size", "128m",
               "--security-opt", "no-new-privileges:true", "--mount", "type=volume,src=" + volume + ",dst=/var/lib/postgresql/data",
               "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=restore_drill",
               "-e", "NO_TS_TUNE=true", "-e", "TIMESCALEDB_TELEMETRY=off", IMAGE,
               "postgres", "-c", "shared_buffers=128MB", "-c", "maintenance_work_mem=32MB",
               "-c", "work_mem=2MB", "-c", "max_connections=40")
        (output / "owned-target.json").write_text(json.dumps({"container": name, "volume": volume,
            "label": token, "image": IMAGE, "network": "none", "memory_mib": 768}), encoding="utf8")
        for _ in range(60):
            owned()
            ready = subprocess.run([*cli, "exec", name, "pg_isready", "-U", "postgres"],
                                   capture_output=True, timeout=10)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Restore database did not become ready")
        roles = (kit / "backup/database-roles.private.sql").read_text(encoding="utf8")
        for role in re.findall(r'^CREATE ROLE ("(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*);$', roles, re.M):
            if role not in {"postgres", '"postgres"'}:
                sql("CREATE ROLE " + role + " NOLOGIN NOSUPERUSER;")
        with (kit / "backup/production.dump").open("rb") as stream:
            docker("exec", "-i", name, "sh", "-c", "umask 077; cat > /tmp/restore.dump", stdin=stream)
        if docker("exec", name, "sha256sum", "/tmp/restore.dump").split()[0] != digest(kit / "backup/production.dump"):
            raise ValueError("Temporary restore copy changed")
        sql("CREATE EXTENSION IF NOT EXISTS timescaledb; SELECT timescaledb_pre_restore();")
        docker("exec", name, "pg_restore", "--exit-on-error", "--no-owner", "--no-acl", "-U", "postgres",
               "-d", "restore_drill", "/tmp/restore.dump", timeout=600)
        sql("SELECT alter_job(job_id, scheduled => false) FROM timescaledb_information.jobs WHERE job_id>=1000;")
        sql("SELECT timescaledb_post_restore();")
        counts = {table: int(sql("SELECT count(*) FROM public." + table))
                  for table in ("canonical_quotes", "provider_quotes", "market_prices", "users", "alerts")}
        tables = int(sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"))
        migrations = int(sql("SELECT count(*) FROM schema_migrations"))
        scheduled = int(sql("SELECT count(*) FROM timescaledb_information.jobs WHERE job_id>=1000 AND scheduled"))
        expected = json.loads((kit / "backup/local-restore-result.json").read_text(encoding="utf8"))
        passed = counts == expected["row_counts"] and tables == 55 and migrations == 10 and scheduled == 0
        info = owned()
        receipt = {"passed": passed, "started_at": started, "finished_at": datetime.now(UTC).isoformat(),
                   "memory_mib": 768, "public_tables": tables, "migrations": migrations, "row_counts": counts,
                   "scheduled_retention_disabled": scheduled == 0, "network": "none", "ports": [],
                   "source_commit": verify(kit)["source_commit"], "live_ready": False,
                   "production_modified": False, "dump_sha256": digest(kit / "backup/production.dump")}
        (output / "restore-result.json").write_text(json.dumps(receipt, indent=2), encoding="utf8")
        if not passed:
            raise ValueError("Restored snapshot differs from reviewed counts")
        docker("rm", "-f", info["Id"])
        volume_info = json.loads(docker("volume", "inspect", volume))[0]
        if volume_info["Labels"].get(LABEL) != token:
            raise ValueError("Restore volume ownership changed; cleanup stopped")
        docker("volume", "rm", volume)
        receipt["owned_test_target_removed"] = True
        (output / "restore-result.json").write_text(json.dumps(receipt, indent=2), encoding="utf8")
        return receipt
    except Exception as exc:
        (output / "failure.json").write_text(json.dumps({"passed": False, "error_type": type(exc).__name__,
            "container": name, "volume": volume, "automatic_retry": False, "production_modified": False}), encoding="utf8")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wsl", action="store_true", help="Use the local WSL Docker engine")
    args = parser.parse_args()
    print(json.dumps(run(args.kit, args.output, ["wsl", "-e", "docker"] if args.wsl else ["docker"])))
