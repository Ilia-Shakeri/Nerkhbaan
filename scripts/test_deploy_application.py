"""Run the deployment entry point against owned files and fake local CLIs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
NEW_HASH = "b" * 64
OLD_HASH = "c" * 64
REFERENCE_MIGRATION = "20261017_001_iranian_reference_records.sql"
GUARD_COMMIT = "d" * 40
CANDIDATE_ID = "e" * 64


def ready_payload(*, old=False, migrated=True, communications=False):
    addition = "20261021_001_communications.sql" if communications else REFERENCE_MIGRATION
    previous = REFERENCE_MIGRATION if communications else "20261011_002_notification_sending_state.sql"
    return {"ready": not (old and migrated), "status": "degraded" if old and migrated else "ok",
            "database": "connected", "redis": "connected", "migration_current": not (old and migrated),
            "migration_version": addition if migrated else previous,
            "release_version": ("2.8.12" if old else "2.8.13") if communications else ("2.8.1" if old else "2.8.8")}


def forward_fixture():
    state = fixture() | {"forward_migration": True}
    migrations = {path.name: hashlib.sha256(path.read_text(encoding="utf-8").replace(
        "\r\n", "\n").replace("\r", "\n").encode()).hexdigest()
        for path in (ROOT / "apps/api/db/migrations").glob("*.sql") if path.name <= REFERENCE_MIGRATION}
    state["desired_migrations"] = migrations
    state["current_migrations"] = {key: value for key, value in migrations.items() if key != REFERENCE_MIGRATION}
    state["applied_migrations"] = dict(state["current_migrations"])
    state["config"]["services"]["migrate"]["command"] = ["python", "-m", "app.migrations.runner"]
    return state


def resume_fixture():
    state = forward_fixture() | {"resume": True, "guard_commit": GUARD_COMMIT, "migrated": True}
    state["original_containers"] = copy.deepcopy(state["containers"])
    state["applied_migrations"] = copy.deepcopy(state["desired_migrations"])
    for item in state["containers"]:
        if item["Config"]["Labels"]["com.docker.compose.service"] == "backend":
            item["State"]["Health"]["Status"] = "unhealthy"
    candidate = container("backend", "recorded-candidate", image=state["manifest"]["images"]["backend"], config_hash=NEW_HASH)
    candidate["Id"] = CANDIDATE_ID
    state["containers"].append(candidate)
    return state


def prepare_resume_evidence(root, state, selected, plan_path, proof_path, transcript):
    from deploy_application import RESUME_KIND, SEMANTIC_CHECKS, fingerprint
    def write(name, value):
        path = root / name
        path.write_text(json.dumps(value) if not isinstance(value, str) else value)
        path.chmod(0o600)
        return path
    def reference(path):
        path.chmod(0o600)
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    baseline = state["original_containers"]
    roles = lambda rows: {item["Id"]: {"project": item["Config"]["Labels"]["com.docker.compose.project"],
                                     "service": item["Config"]["Labels"]["com.docker.compose.service"]} for item in rows}
    migration = json.loads(plan_path.read_text())
    original_fingerprints = {item["Id"]: fingerprint(item) for item in baseline}
    log = write("original-failed.log", "Migration service completed; verifying pinned addition " + REFERENCE_MIGRATION +
                ", exact ledger and old migration-only readiness.\nDeploy stopped: Unexpected backend appeared.\n")
    stamp = datetime.now(timezone.utc).isoformat()
    attempt = write("original-attempt.json", {"mode": "deploy", "commit": COMMIT, "started_at": stamp,
                    "private_log": str(log), "baseline_container_fingerprints": original_fingerprints,
                    "baseline_container_roles": roles(baseline)})
    failed = write("original-failed.json", {"mode": "deploy", "commit": COMMIT, "started_at": stamp,
                   "checked_at": stamp, "passed": False, "returncode": 1, "wrapper_success_marker": False,
                   "private_log": str(log), "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
    ci = {"schema_version": 1, "guard_commit": GUARD_COMMIT, "run_id": 12345,
          "run_url": "https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/12345",
          "status": "completed", "conclusion": "success", "jobs": [
              {"name": "owned-hosted-job-" + str(index), "status": "completed", "conclusion": "success"}
              for index in range(15)]}
    binding = {"application_commit": COMMIT, "guard_commit": GUARD_COMMIT, "application_version": "2.8.8",
               "project": "nerkhbaan", "readiness_url": "https://fixture.invalid/api/health/ready",
               "images": state["manifest"]["images"], "baseline_backends": migration["baseline_backends"],
               "added_backend": {"id": CANDIDATE_ID, "image": state["manifest"]["images"]["backend"], "config_hash": NEW_HASH},
               "target_migrations": state["desired_migrations"]}
    probes = []
    for item in state["containers"]:
        if item["Config"]["Labels"]["com.docker.compose.service"] != "backend":
            continue
        old = item["Id"] != CANDIDATE_ID
        probes.append({"id": item["Id"], "image": item["Image"], "status": 503 if old else 200,
                       "payload": ready_payload(old=old), "expected": state["current_migrations"] if old else state["desired_migrations"],
                       "applied": state["desired_migrations"], "migration_state": {
                           "current": not old, "version": REFERENCE_MIGRATION, "applied_count": 9,
                           "expected_count": 8 if old else 9, "missing": [], "changed": [],
                           "unknown": [REFERENCE_MIGRATION] if old else []}})
    observation = {"schema_version": 1, "kind": RESUME_KIND, "source": "actual_target_read_only", "checked_at": stamp,
                   "binding": copy.deepcopy(binding), "baseline_container_fingerprints": original_fingerprints,
                   "current_container_fingerprints": {item["Id"]: fingerprint(item) for item in state["containers"]},
                   "current_container_roles": roles(state["containers"]), "semantic_checks": {name: True for name in SEMANTIC_CHECKS},
                   "resolved_config_sha256": hashlib.sha256(json.dumps(state["config"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                   "service_hashes": {name: NEW_HASH for name in ("backend", "frontend", "admin-frontend", "price-feed-pull")},
                   "probes": probes}
    fault = state.get("resume_fault")
    if fault == "ci_object_shape": ci = []
    elif fault == "observation_object_shape": observation = []
    elif fault == "ci_commit": ci["guard_commit"] = "f" * 40
    elif fault == "ci_failed": ci["jobs"][0]["conclusion"] = "failure"
    elif fault == "ci_missing_job": ci["jobs"].pop()
    elif fault == "ci_duplicate_job": ci["jobs"][-1]["name"] = ci["jobs"][0]["name"]
    elif fault == "old_probe_failure": observation["probes"][0]["payload"]["redis"] = "disconnected"
    elif fault == "extra_unknown_migration": observation["probes"][0]["migration_state"]["unknown"].append("unknown.sql")
    elif fault == "new_probe_failure": observation["probes"][-1]["status"] = 503
    elif fault == "semantic_false": observation["semantic_checks"]["environment"] = False
    elif fault == "semantic_integer": observation["semantic_checks"]["environment"] = 1
    elif fault == "semantic_missing": observation["semantic_checks"].pop("mounts")
    elif fault == "resolved_model": observation["resolved_config_sha256"] = "f" * 64
    elif fault == "service_hash": observation["service_hashes"]["backend"] = "f" * 64
    elif fault == "stale": observation["checked_at"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    elif fault == "future": observation["checked_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    elif fault == "naive_clock": observation["checked_at"] = "2026-10-18T10:00:00"
    elif fault == "binding": observation["binding"]["application_commit"] = "f" * 40
    elif fault == "candidate_id": binding["added_backend"]["id"] = "f" * 64
    elif fault == "candidate_hash": binding["added_backend"]["config_hash"] = "f" * 64
    elif fault == "old_identity": state["containers"][0]["State"]["StartedAt"] = "changed"
    elif fault == "protected_identity": state["containers"][2]["Mounts"][0]["Source"] = "/changed"
    elif fault == "candidate_unhealthy": state["containers"][-1]["State"]["Health"]["Status"] = "unhealthy"
    elif fault == "unknown_candidate": state["containers"].append(container("backend", "unknown-added"))
    elif fault == "wrong_ledger": state["applied_migrations"][REFERENCE_MIGRATION] = "f" * 64
    ci_path = write("guard-ci.json", ci)
    fresh_path = write("fresh-observation.json", observation)
    files = {"failed_attempt": attempt, "failed_proof": failed, "failed_log": log,
             "migration_plan": plan_path, "image_manifest": selected["image_manifest"],
             "restore_report": proof_path, "restore_transcript": transcript, "guard_ci": ci_path,
             "fresh_observation": fresh_path, **{name: selected[name] for name in (
                 "operator_evidence", "compose_override", "private_environment")}}
    resume = {"schema_version": 1, "kind": RESUME_KIND, **binding,
              "files": {name: reference(path) for name, path in files.items()}}
    if fault == "file_hash": resume["files"]["failed_log"]["sha256"] = "f" * 64
    if fault == "missing_file": fresh_path.unlink()
    if fault == "private_mode": fresh_path.chmod(0o644)
    return write("resume-plan.json", resume)


def container(name, suffix="1", *, image=None, owner="nerkhbaan", config_hash=OLD_HASH):
    return {
        "Id": f"{owner}-{name}-{suffix}", "Image": image or f"sha256:old-{name}",
        "Created": "2026-10-01T00:00:00Z",
        "Config": {"Labels": {
            "com.docker.compose.project": owner, "com.docker.compose.service": name,
            "com.docker.compose.config-hash": config_hash,
        }},
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
        "Mounts": [{"Source": f"/private/{name}", "Destination": "/data"}],
        "NetworkSettings": {"Networks": {f"{owner}-network": {
            "NetworkID": "stable-network", "EndpointID": f"endpoint-{suffix}", "IPAddress": "172.28.0.5",
        }}},
        "State": {"Running": True, "StartedAt": "2026-10-01T00:00:01Z", "Health": {"Status": "healthy"}},
    }


def multiple_mounts():
    return [
        {"Type": "bind", "Source": "/fixture/logs", "Destination": "/var/log/nginx",
         "Mode": "rw", "RW": True, "Propagation": "rprivate"},
        {"Type": "bind", "Source": "/fixture/nginx.conf", "Destination": "/etc/nginx/nginx.conf",
         "Mode": "ro", "RW": False, "Propagation": "rprivate"},
        {"Type": "tmpfs", "Source": "", "Destination": "/tmp",
         "Mode": "", "RW": True, "Propagation": ""},
        {"Type": "volume", "Name": "fixture-cache", "Source": "/fixture/volumes/cache/_data",
         "Destination": "/var/cache/nginx", "Driver": "local", "Mode": "rw", "RW": True,
         "Propagation": "", "Options": {"retained": "fixture"}},
        {"Type": "bind", "Source": "/fixture/certificates", "Destination": "/etc/letsencrypt",
         "Mode": "ro", "RW": False, "Propagation": "rprivate"},
        {"Type": "volume", "Name": "fixture-edge", "Source": "/fixture/volumes/edge/_data",
         "Destination": "/run/edge", "Driver": "local", "Mode": "rw", "RW": True, "Propagation": ""},
        {"Type": "bind", "Source": "/fixture/conf.d", "Destination": "/etc/nginx/conf.d",
         "Mode": "ro", "RW": False, "Propagation": "rprivate"},
    ]


def fixture():
    names = ("backend", "migrate", "frontend", "admin-frontend", "price-feed-pull")
    images = {name: "sha256:" + hashlib.sha256(name.encode()).hexdigest() for name in names}
    images["migrate"] = images["backend"]
    services = {
        name: {"image": f"nerkhbaan-{name}:{COMMIT}", "healthcheck": {"test": ["CMD", "true"]},
               "networks": {"app": {}}}
        for name in names
    }
    current = [container("backend", str(index)) for index in (1, 2)]
    current += [container(name) for name in (
        "postgres", "redis", "db-backup", "frontend", "admin-frontend", "price-feed-pull",
        "prometheus", "alertmanager", "grafana", "redis-exporter", "telegram-worker",
    )]
    current += [container("edge", owner="shared-edge"), container("store", owner="other-project")]
    stopped_migration = container("migrate", "previous-oneoff")
    stopped_migration["State"]["Running"] = False
    current.append(stopped_migration)
    return {
        "commit": COMMIT, "config": {"name": "nerkhbaan", "services": services,
                                     "networks": {"app": {"name": "nerkhbaan-network"}}},
        "images": {services[name]["image"]: images[name] for name in names},
        "manifest": {"commit": COMMIT, "images": images},
        "desired_migrations": {"001_initial.sql": hashlib.sha256(b"SELECT 1;\n").hexdigest()},
        "current_migrations": {"001_initial.sql": hashlib.sha256(b"SELECT 1;\n").hexdigest()},
        "applied_migrations": {"001_initial.sql": hashlib.sha256(b"SELECT 1;\n").hexdigest()},
        "containers": current, "commands": [], "readiness_checks": 0, "scale_runs": 0,
    }


def fake_cli(kind: str, args: list[str], input_text: str | None = None) -> int:
    path = Path(os.environ["FAKE_DEPLOY_STATE"])
    state = json.loads(path.read_text())
    state["commands"].append([kind, *args])
    code, output = 0, ""
    if kind == "git":
        guard = args[:1] == ["-C"]
        if guard:
            args = args[2:]
        if args[0] == "status":
            output = " M tracked.txt" if state.get("guard_dirty" if guard else "dirty") else ""
        elif args == ["rev-parse", "HEAD"]:
            output = state.get("guard_commit", state["commit"]) if guard else state["commit"]
        elif args[:2] == ["diff", "--name-only"]:
            output = "apps/api/app/changed.py" if state.get("guard_api_changed") else ""
        else:
            code = 98
    elif args[:2] == ["ps", "-aq"]:
        output = "\n".join(item["Id"] for item in state["containers"])
    elif args[0] == "inspect":
        current = {item["Id"]: item for item in state["containers"]}
        if any(value not in current for value in args[1:]):
            code = 1
        else:
            inspected = copy.deepcopy([current[value] for value in args[1:]])
            if state.get("reorder_inspected_mounts"):
                state["inspect_reads"] = state.get("inspect_reads", 0) + 1
                for item in inspected:
                    mounts = item["Mounts"]
                    if mounts:
                        offset = state["inspect_reads"] % len(mounts)
                        item["Mounts"] = mounts[offset:] + mounts[:offset]
            output = json.dumps(inspected)
    elif args[:2] == ["image", "inspect"]:
        images = [state["images"].get(name) for name in args[2:]]
        if not images or any(image is None for image in images):
            code = 1
        else:
            output = json.dumps([{"Id": image} for image in images])
    elif args[0] == "run":
        assert "--read-only" in args and "--network" in args and args[args.index("--network") + 1] == "none"
        assert "--rm" in args and "--pull" in args and args[args.index("--pull") + 1] == "never"
        output = json.dumps(state["desired_migrations"])
    elif args[0] == "exec":
        if "urlopen" in args[-1]:
            item = next(item for item in state["containers"] if item["Id"] == args[1])
            old = item["Image"] != state["manifest"]["images"]["backend"]
            migrated = state.get("migrated", False)
            communications = state.get("communications", False)
            addition = "20261021_001_communications.sql" if communications else REFERENCE_MIGRATION
            payload = ready_payload(old=old, migrated=migrated, communications=communications)
            expected = state["current_migrations"] if old else state["desired_migrations"]
            migration_state = {"current": not (old and migrated), "version": payload["migration_version"],
                               "applied_count": len(state["applied_migrations"]), "expected_count": len(expected),
                               "missing": [], "changed": [], "unknown": [addition] if old and migrated else []}
            status = 503 if old and migrated else 200
            if old and migrated and state.get("old_ready_failure"):
                payload["database"] = "disconnected"
            if old and migrated and state.get("old_other_migration_failure"):
                migration_state["changed"] = ["20260718_001_core_pricing.sql"]
            if old and not migrated and state.get("baseline_probe_failure"):
                payload["redis"] = "disconnected"
            if not old and state.get("new_ready_failure"):
                status, payload["ready"] = 503, False
            if not old and state.get("new_expected_migrations_failure"):
                expected = state["current_migrations"]
            output = json.dumps({"status": status, "payload": payload, "expected": expected,
                                 "applied": state["applied_migrations"], "migration_state": migration_state})
        else:
            output = json.dumps({"expected": state["current_migrations"], "applied": state["applied_migrations"]})
    elif args[0] in {"stop", "rm"}:
        container_id = args[-1]
        item = next(item for item in state["containers"] if item["Id"] == container_id)
        if args[0] == "stop":
            item["State"]["Running"] = False
            for details in item["NetworkSettings"]["Networks"].values():
                details["EndpointID"] = ""
                details["IPAddress"] = ""
            if state.get("resume_file_drift_after_stop"):
                resume = json.loads(Path(os.environ["DEPLOY_RESUME_PLAN"]).read_text())
                ci_path = Path(resume["files"]["guard_ci"]["path"])
                ci_path.write_bytes(ci_path.read_bytes() + b"\n")
            if state.get("resume_candidate_drift_after_stop"):
                candidate = next(item for item in state["containers"] if item["Id"] == CANDIDATE_ID)
                candidate["HostConfig"]["RestartPolicy"]["Name"] = "always"
        else:
            state["containers"].remove(item)
    elif args[0] == "compose":
        index = next(index for index, value in enumerate(args) if value in {"config", "ps", "run", "up"})
        command = args[index:]
        if command[0] == "config" and "--format" in command:
            output = json.dumps(state["config"])
        elif command[:2] == ["config", "--hash"]:
            if "-f" in args and args[args.index("-f") + 1] == "-":
                model = json.loads(input_text if input_text is not None else sys.stdin.read())
                assert model == state["config"], "Hash input must be the reviewed resolved configuration"
                state["resolved_hash_reads"] = state.get("resolved_hash_reads", 0) + 1
                output = f"{command[-1]} {NEW_HASH}"
            else:
                state["raw_hash_reads"] = state.get("raw_hash_reads", 0) + 1
                output = f"{command[-1]} {state.get('raw_config_hash', NEW_HASH)}"
        elif command[0] == "ps":
            output = "\n".join(item["Id"] for item in state["containers"] if
                               item["Config"]["Labels"]["com.docker.compose.project"] == "nerkhbaan" and
                               item["Config"]["Labels"]["com.docker.compose.service"] == "backend")
        elif command[0] == "run":
            if state.get("migration_failure"):
                code = 1
            if state.get("migration_changes_readiness"):
                for item in state["containers"]:
                    if item["Config"]["Labels"]["com.docker.compose.service"] == "backend":
                        item["State"]["Health"]["Status"] = "unhealthy"
            if state.get("forward_migration") and not state.get("migration_failure"):
                state["migrated"] = True
                state["applied_migrations"] = dict(state["desired_migrations"])
                for item in state["containers"]:
                    if item["Config"]["Labels"]["com.docker.compose.service"] == "backend":
                        item["State"]["Health"]["Status"] = "unhealthy"
                if state.get("post_migration_unknown"):
                    state["applied_migrations"]["unknown.sql"] = "d" * 64
                if state.get("post_migration_checksum_change"):
                    state["applied_migrations"]["20260718_001_core_pricing.sql"] = "d" * 64
                if state.get("proof_drift_after_migrate"):
                    plan = json.loads(Path(os.environ["DEPLOY_MIGRATION_PLAN"]).read_text())
                    proof_path = Path(plan["evidence"]["path"])
                    proof_path.write_bytes(proof_path.read_bytes() + b"\n")
        elif command[0] == "up" and "--scale" in command:
            state["scale_runs"] += 1
            image_ref = state["config"]["services"]["backend"]["image"]
            new = container("backend", f"new-{state['scale_runs']}", image=state["images"][image_ref],
                            config_hash=NEW_HASH)
            state["containers"].append(new)
            if state.get("fail_scale") == state["scale_runs"]:
                new["State"]["Health"]["Status"] = "unhealthy"
                code = 1
            if state.get("wrong_new_image"):
                new["Image"] = "sha256:unexpected"
            if state.get("wrong_new_hash"):
                new["Config"]["Labels"]["com.docker.compose.config-hash"] = OLD_HASH
            if state.get("wrong_new_network"):
                new["NetworkSettings"]["Networks"]["nerkhbaan-network"]["NetworkID"] = "other-network"
            if state.get("old_identity_drift"):
                old = next(item for item in state["containers"] if item["Config"]["Labels"].get("com.docker.compose.service") == "backend"
                           and item["Image"] != state["manifest"]["images"]["backend"])
                old["Mounts"][0]["Source"] = "/changed"
            if state.get("protected_drift"):
                data = next(item for item in state["containers"] if item["Id"] == "nerkhbaan-redis-1")
                data["Mounts"][0]["Source"] = "/changed"
            if state.get("tag_drift"):
                state["images"][image_ref] = "sha256:changed-tag"
            if state.get("config_drift"):
                state["config"]["services"]["frontend"]["environment"] = {"CHANGED": "true"}
            if state.get("proof_drift_after_scale"):
                plan_path = Path(os.environ["DEPLOY_MIGRATION_PLAN"])
                plan_path.write_bytes(plan_path.read_bytes() + b"\n")
            if state.get("new_stays_starting"):
                new["State"]["Health"]["Status"] = "starting"
        elif command[0] == "up":
            if state.get("client_failure"):
                code = 1
            else:
                for name in ("frontend", "admin-frontend", "price-feed-pull"):
                    if name not in command:
                        continue
                    state["containers"] = [item for item in state["containers"] if not (
                        item["Config"]["Labels"]["com.docker.compose.project"] == "nerkhbaan" and
                        item["Config"]["Labels"]["com.docker.compose.service"] == name)]
                    image = state["images"][state["config"]["services"][name]["image"]]
                    state["containers"].append(container(name, "new", image=image, config_hash=NEW_HASH))
                if state.get("client_config_drift"):
                    state["config"]["services"]["frontend"]["environment"] = {"CHANGED": "true"}
                if state.get("client_wrong_hash"):
                    state["containers"][-1]["Config"]["Labels"]["com.docker.compose.config-hash"] = OLD_HASH
        else:
            code = 98
    else:
        code = 98
    path.write_text(json.dumps(state))
    if output:
        print(output)
    return code


class ResolvedServiceHashTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from deploy_application import ApplicationDeploy, DeployStopped
        self.patch, self.stopped = patch, DeployStopped
        self.deploy = object.__new__(ApplicationDeploy)
        self.deploy.root, self.deploy.project_name = ROOT, "nerkhbaan"
        self.deploy.env_file = ROOT / "private-fixture.env"
        self.deploy.wait, self.deploy.startup_deadline = 30, None
        self.secret = "owned-fixture-$private-value"
        self.deploy.config = {"name": "nerkhbaan", "services": {
            "backend": {"environment": {"FIXTURE_SECRET": self.secret}},
        }}

    def test_resolved_model_stays_in_stdin_and_keeps_project_path_context(self):
        before = copy.deepcopy(self.deploy.config)
        with self.patch("deploy_application.command", return_value=f"backend {NEW_HASH}") as run:
            self.assertEqual(self.deploy.resolved_service_hash("backend"), NEW_HASH)
        args, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(args[args.index("-f") + 1], "-")
        self.assertEqual(args[args.index("--project-directory") + 1], str(ROOT))
        self.assertEqual(args[args.index("--env-file") + 1], str(self.deploy.env_file))
        self.assertEqual(json.loads(kwargs["input_text"]), before)
        self.assertNotIn(self.secret, " ".join(args))
        self.assertEqual(self.deploy.config, before)

    def test_malformed_or_wrong_service_hash_fails_closed(self):
        for output in ("", f"frontend {NEW_HASH}", "backend invalid", f"backend {NEW_HASH}\nbackend {NEW_HASH}"):
            with self.subTest(output=output), self.patch("deploy_application.command", return_value=output):
                with self.assertRaises(self.stopped) as caught:
                    self.deploy.resolved_service_hash("backend")
                self.assertNotIn(self.secret, str(caught.exception))

    def test_failed_hash_child_does_not_expose_private_input_or_output(self):
        from deploy_application import command
        failed = subprocess.CompletedProcess(["docker"], 1, self.secret, self.secret)
        with self.patch("deploy_application.subprocess.run", return_value=failed) as run:
            with self.assertRaises(self.stopped) as caught:
                command(["docker", "compose"], cwd=ROOT, input_text=self.secret)
        self.assertNotIn(self.secret, str(caught.exception))
        self.assertEqual(run.call_args.kwargs["input"], self.secret)
        self.assertNotIn(self.secret, " ".join(run.call_args.args[0]))


class MountIdentityTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from deploy_application import ApplicationDeploy, DeployStopped, identity

        self.patch = patch
        self.deploy_class = ApplicationDeploy
        self.deploy_stopped = DeployStopped
        self.identity = identity
        self.baseline = container("edge", owner="shared-edge")
        self.baseline["Mounts"] = multiple_mounts()

    def test_reordered_mounts_preserve_identity_all_fields_and_original_payloads(self):
        changed = copy.deepcopy(self.baseline)
        changed["Mounts"] = list(reversed(changed["Mounts"]))
        before, changed_before = copy.deepcopy(self.baseline), copy.deepcopy(changed)
        actual = self.identity(self.baseline)
        self.assertEqual(actual, self.identity(changed))
        by_destination = {mount["Destination"]: mount for mount in before["Mounts"]}
        self.assertEqual(actual["Mounts"], [by_destination[destination] for destination in (
            "/etc/letsencrypt", "/etc/nginx/conf.d", "/etc/nginx/nginx.conf", "/run/edge",
            "/tmp", "/var/cache/nginx", "/var/log/nginx",
        )])
        self.assertIsNot(actual["Mounts"], self.baseline["Mounts"])
        self.assertEqual(self.baseline, before)
        self.assertEqual(changed, changed_before)

    def test_protected_guard_rejects_changed_mount_fields_after_reordering(self):
        for field, value in (("Source", "/changed"), ("Destination", "/elsewhere"),
                             ("RW", False), ("Propagation", "rshared"), ("Type", "volume"),
                             ("Mode", "ro"), ("ExtraField", {"new": True})):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.baseline)
                changed["Mounts"][0][field] = value
                changed["Mounts"].reverse()
                deploy = object.__new__(self.deploy_class)
                deploy.project_name, deploy.targets = "nerkhbaan", []
                deploy.protected = {self.baseline["Id"]: self.baseline}
                with self.patch.object(deploy, "containers", return_value=[changed]):
                    with self.assertRaisesRegex(self.deploy_stopped, "Protected container identity"):
                        deploy.check_protected()

    def test_missing_mounts_do_not_become_an_empty_array(self):
        missing = copy.deepcopy(self.baseline)
        del missing["Mounts"]
        empty = copy.deepcopy(missing)
        empty["Mounts"] = []
        self.assertIsNone(self.identity(missing)["Mounts"])
        self.assertEqual(self.identity(empty)["Mounts"], [])
        self.assertNotEqual(self.identity(missing), self.identity(empty))

    def test_restart_and_config_changes_still_reject_after_mount_reordering(self):
        for field in ("StartedAt", "Config"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.baseline)
                changed["Mounts"].reverse()
                if field == "StartedAt":
                    changed["State"]["StartedAt"] = "2026-10-17T00:00:00Z"
                else:
                    changed["Config"]["Labels"]["changed"] = "fixture"
                deploy = object.__new__(self.deploy_class)
                deploy.project_name, deploy.targets = "nerkhbaan", []
                deploy.protected = {self.baseline["Id"]: self.baseline}
                with self.patch.object(deploy, "containers", return_value=[changed]):
                    with self.assertRaisesRegex(self.deploy_stopped, "Protected container identity"):
                        deploy.check_protected()

    def test_old_backend_guard_accepts_only_reordering_and_rejects_mount_drift(self):
        baseline = container("backend")
        baseline["Mounts"] = multiple_mounts()
        changed = copy.deepcopy(baseline)
        changed["Mounts"].reverse()
        deploy = object.__new__(self.deploy_class)
        deploy.project_name = "nerkhbaan"
        with self.patch.object(deploy, "inspect", return_value=[changed]):
            deploy.guard_old(baseline, running=True)
            changed["Mounts"][0]["Source"] = "/changed"
            with self.assertRaisesRegex(self.deploy_stopped, "Recorded backend identity"):
                deploy.guard_old(baseline, running=True)

    def test_resume_rejects_an_unrecorded_migrator_while_default_probe_scope_stays_valid(self):
        deploy = object.__new__(self.deploy_class)
        deploy.project_name, deploy.targets = "nerkhbaan", ["frontend", "price-feed-pull"]
        deploy.protected = {self.baseline["Id"]: self.baseline}
        deploy.resume_plan = {"kind": "reviewed-resume"}
        with self.patch.object(deploy, "containers", return_value=[self.baseline, container("migrate", "unexpected")]):
            with self.assertRaisesRegex(self.deploy_stopped, "Unexpected protected container"):
                deploy.check_protected()
            deploy.resume_plan = None
            deploy.check_protected()


class MigrationReadinessPolicyTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from deploy_application import ApplicationDeploy, DeployStopped
        self.patch, self.stopped = patch, DeployStopped
        self.deploy = object.__new__(ApplicationDeploy)
        self.deploy.readiness_url = "https://fixture.invalid/api/health/ready"
        self.deploy.migrated = True
        self.deploy.startup_deadline = None
        self.deploy.plan = {"baseline_backends": [{"release_version": "2.8.1"}],
                            "baseline_migrations": {"20261011_002_notification_sending_state.sql": "fixture"}}

    def http_response(self, payload, status=503):
        from io import BytesIO
        from urllib.error import HTTPError
        return HTTPError(self.deploy.readiness_url, status, "fixture", {}, BytesIO(json.dumps(payload).encode()))

    def test_normal_resume_is_exclusive_with_both_transition_inputs(self):
        from deploy_application import ApplicationDeploy
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {name: root / name for name in ["environment", "override", "operator", "manifest", "normal"]}
            for path in files.values():
                path.write_text("{}")
            env = {"RELEASE_DIR": str(root), "COMPOSE_PROJECT_NAME": "nerkhbaan",
                   "COMPOSE_ENV_FILE": str(files["environment"]), "COMPOSE_OVERRIDE_FILE": str(files["override"]),
                   "OPERATOR_EVIDENCE_PATH": str(files["operator"]), "DEPLOY_IMAGE_MANIFEST": str(files["manifest"]),
                   "DEPLOY_READINESS_URL": "https://fixture.invalid/api/health/ready",
                   "DEPLOY_NORMAL_RESUME_PLAN": str(files["normal"])}
            selected = ApplicationDeploy(env)
            self.assertEqual(selected.normal_resume_path, files["normal"])
            self.assertIsNone(selected.plan)
            self.assertIsNone(selected.resume_plan)
            for key in ["DEPLOY_MIGRATION_PLAN", "DEPLOY_RESUME_PLAN"]:
                with self.subTest(key=key), self.assertRaisesRegex(self.stopped, "cannot select"):
                    ApplicationDeploy(env | {key: str(files["normal"])})

    def test_real_http_error_body_is_accepted_only_for_exact_known_old_transition(self):
        with self.patch("deploy_application.build_opener") as opener:
            opener.return_value.open.side_effect = self.http_response(ready_payload(old=True))
            self.deploy.readiness(allow_old=True)
        for field, value in (("database", "disconnected"), ("redis", "disconnected"),
                             ("ready", True), ("migration_current", True),
                             ("migration_version", "unexpected.sql"), ("release_version", "2.8.0")):
            with self.subTest(field=field), self.patch("deploy_application.build_opener") as opener:
                opener.return_value.open.side_effect = self.http_response(ready_payload(old=True) | {field: value})
                with self.assertRaises(self.stopped):
                    self.deploy.readiness(allow_old=True)

    def test_default_and_final_new_only_gate_reject_known_old_503(self):
        for default in (False, True):
            with self.subTest(default=default), self.patch("deploy_application.build_opener") as opener:
                if default:
                    self.deploy.plan = None
                opener.return_value.open.side_effect = self.http_response(ready_payload(old=True))
                with self.assertRaises(self.stopped):
                    self.deploy.readiness(allow_old=False)

    def test_utc_proof_age_has_bounded_past_and_future_and_needs_timezone(self):
        for value in ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
                      (datetime.now(timezone.utc) + timedelta(minutes=6)).isoformat(),
                      "2026-10-17T00:00:00", "no-date", None):
            with self.subTest(value=value), self.assertRaises(self.stopped):
                self.deploy.check_proof_time(value)
        self.deploy.check_proof_time(datetime.now(timezone.utc).isoformat())

    def test_startup_deadline_limits_each_child_command_and_clears_after_failure(self):
        self.deploy.root = ROOT
        self.deploy.startup_deadline = 15.0
        with self.patch("deploy_application.time.monotonic", return_value=10.0), self.patch(
            "deploy_application.command", return_value="fixture"
        ) as command:
            self.assertEqual(self.deploy.run(["docker", "inspect"], timeout=30), "fixture")
            self.assertEqual(command.call_args.kwargs["timeout"], 5.0)
        with self.patch("deploy_application.time.monotonic", return_value=16.0), self.patch(
            "deploy_application.command"
        ) as command:
            with self.assertRaises(self.stopped):
                self.deploy.run(["docker", "inspect"])
            command.assert_not_called()
        self.deploy.wait = 1
        with self.patch.object(self.deploy, "poll_added_backend", side_effect=self.stopped("fixture")):
            with self.assertRaises(self.stopped):
                self.deploy.wait_added_backend(3, 1)
        self.assertIsNone(self.deploy.startup_deadline)

    def test_https_readiness_shares_startup_deadline_and_rejects_late_success(self):
        self.deploy.startup_deadline = 15.0
        with self.patch("deploy_application.time.monotonic", return_value=10.0), self.patch(
            "deploy_application.build_opener"
        ) as opener:
            opener.return_value.open.return_value = self.http_response(ready_payload(), status=200)
            self.deploy.readiness()
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 5.0)
        with self.patch("deploy_application.time.monotonic", side_effect=[10.0, 16.0]), self.patch(
            "deploy_application.build_opener"
        ) as opener:
            opener.return_value.open.return_value = self.http_response(ready_payload(), status=200)
            with self.assertRaisesRegex(self.stopped, "timed out"):
                self.deploy.readiness()
        with self.patch("deploy_application.time.monotonic", return_value=16.0), self.patch(
            "deploy_application.build_opener"
        ) as opener:
            with self.assertRaisesRegex(self.stopped, "timed out"):
                self.deploy.readiness()
            opener.return_value.open.assert_not_called()

    def test_changed_private_evidence_is_rejected_before_more_mutations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "owned-proof.json"
            path.write_text("owned proof")
            path.chmod(0o600)
            self.deploy.plan = None
            self.deploy.plan_files = {path: hashlib.sha256(path.read_bytes()).hexdigest()}
            self.deploy.check_plan_files()
            path.write_text("changed proof")
            with self.assertRaises(self.stopped):
                self.deploy.check_plan_files()

    def test_retirement_deadline_bounds_guard_children_and_restores_prior_budget(self):
        from deploy_application import TransientReadiness
        self.deploy.root = ROOT
        for previous, expected in ((None, 40.0), (25.0, 25.0)):
            self.deploy.startup_deadline = previous
            def guard():
                self.assertEqual(self.deploy.startup_deadline, expected)
                self.deploy.run(["docker", "inspect"], timeout=300)
                raise self.stopped("fixture guard failure")
            with self.subTest(previous=previous), self.patch("deploy_application.time.monotonic", return_value=10.0), self.patch.object(
                self.deploy, "readiness_once", side_effect=TransientReadiness("transport_timeout")
            ), self.patch.object(self.deploy, "check_images", side_effect=guard), self.patch("deploy_application.command") as command:
                with self.assertRaisesRegex(self.stopped, "stage=retirement type=validation operation=retry_images"):
                    self.deploy.readiness(retirement=True)
                self.assertEqual(command.call_args.kwargs["timeout"], expected - 10.0)
            self.assertEqual(self.deploy.startup_deadline, previous)

    def test_successful_public_readiness_cannot_remove_after_postcheck_deadline(self):
        self.deploy.root = ROOT
        self.deploy.replicas = 2
        self.deploy.baseline_backends = {}
        self.deploy.normal_stopped = {"Id": "recorded-stopped"}
        self.deploy.normal_resume_observation = {"current_container_fingerprints": {}}
        for phase in ("normal", "already_stopped"):
            for previous in (None, 100.0):
                clock = [0.0]
                checks = [0]
                self.deploy.startup_deadline = previous
                def postcheck():
                    checks[0] += 1
                    if checks[0] == 2:
                        clock[0] = 31.0
                running = [{"Id": name, "State": {"Running": True}} for name in ("survivor", "candidate")]
                with self.subTest(phase=phase, previous=previous), self.patch("deploy_application.time.monotonic", side_effect=lambda: clock[0]), self.patch(
                    "deploy_application.command", return_value=""
                ) as command, self.patch.object(self.deploy, "check_images", side_effect=postcheck), self.patch.object(
                    self.deploy, "backend_health"
                ), self.patch.object(self.deploy, "check_plan_files"), self.patch.object(self.deploy, "check_protected"), self.patch.object(
                    self.deploy, "guard_old"
                ), self.patch.object(self.deploy, "backends", return_value=running), self.patch.object(
                    self.deploy, "backend_healthy", return_value=True
                ), self.patch.object(self.deploy, "readiness_once"), self.patch.object(
                    self.deploy, "check_retirement_pair"
                ), self.patch.object(self.deploy, "containers", return_value=[]):
                    with self.assertRaisesRegex(self.stopped, "stage=retirement"):
                        if phase == "normal":
                            self.deploy.retire_backend({"Id": "old-first"}, 1)
                        else:
                            self.deploy.finish_stopped_normal_retirement()
                    self.assertFalse(any(call.args[0][:2] == ["docker", "rm"] for call in command.call_args_list))
                self.assertEqual(self.deploy.startup_deadline, previous)


class GuardBatchAndParallelTests(unittest.TestCase):
    def setUp(self):
        import deploy_application as guard
        from unittest.mock import patch
        self.guard, self.patch = guard, patch
        self.deploy = object.__new__(guard.ApplicationDeploy)
        self.deploy.root, self.deploy.commit = ROOT, COMMIT
        self.deploy.startup_deadline = None
        self.deploy.plan, self.deploy.resume_plan, self.deploy.normal_resume_plan = None, None, None
        self.deploy.config = {"owned": "fixture"}
        self.deploy.images = {"backend": ("api:fixed", "sha256:api"), "migrate": ("api:fixed", "sha256:api"),
                              "frontend": ("web:fixed", "sha256:web"), "admin-frontend": ("admin:fixed", "sha256:admin"),
                              "price-feed-pull": ("feed:fixed", "sha256:feed")}

    def batch(self, rows):
        def run(args, **_kwargs):
            return json.dumps(rows) if args[:3] == ["docker", "image", "inspect"] else COMMIT if args[-1] == "HEAD" else ""
        with self.patch.object(self.deploy, "run", side_effect=run) as child, self.patch.object(
            self.deploy, "check_plan_files"
        ) as plans, self.patch.object(self.deploy, "check_env_binding") as environment, self.patch.object(
            self.deploy, "compose_run", return_value=json.dumps(self.deploy.config)
        ) as compose:
            self.deploy.check_images()
            plans.assert_called_once();environment.assert_called_once();compose.assert_called_once()
            return child.call_args_list

    def test_batch_inspects_every_unique_tag_and_keeps_all_other_guards(self):
        calls = self.batch([{"Id": "sha256:" + value} for value in ["api", "web", "admin", "feed"]])
        images = [call.args[0] for call in calls if call.args[0][:3] == ["docker", "image", "inspect"]]
        self.assertEqual(images, [["docker", "image", "inspect", "api:fixed", "web:fixed", "admin:fixed", "feed:fixed"]])
        self.assertEqual(len(calls), 3)

    def test_batch_rejects_missing_extra_reordered_wrong_identity_or_conflicting_tag(self):
        valid = [{"Id": "sha256:" + value} for value in ["api", "web", "admin", "feed"]]
        for rows in [valid[:-1], valid + valid[:1], list(reversed(valid)), valid[:1] * 4, {}, [None] * 4]:
            with self.subTest(rows=rows), self.assertRaises(self.guard.DeployStopped):self.batch(rows)
        self.deploy.images["migrate"] = ("api:fixed", "sha256:tampered")
        with self.patch.object(self.deploy, "check_plan_files"), self.patch.object(self.deploy, "run") as child:
            with self.assertRaises(self.guard.DeployStopped):self.deploy.check_images()
            child.assert_not_called()

    def test_two_strict_normal_probes_overlap_keep_child_budget_and_join_on_mismatch(self):
        import threading
        for mismatch in (False, True):
            barrier, lock = threading.Barrier(2), threading.Lock()
            active, peak, budgets, completed = [0], [0], [], []
            ledger = {"migration" + str(index): "a" * 64 for index in range(9)}
            self.deploy.normal_resume_plan = {"target_migrations": ledger}
            self.deploy.baseline_backends = {"old": {}}
            self.deploy.startup_deadline = 15.0
            items = [{"Id": name, "State": {"Running": True, "Health": {"Status": "healthy"}}} for name in ["old", "new"]]
            def child(args, **kwargs):
                name = args[2]
                with lock:
                    active[0] += 1;peak[0] = max(peak[0], active[0]);budgets.append(kwargs["timeout"])
                try:
                    barrier.wait(timeout=2)
                    return json.dumps({"status": 200, "payload": {"ready": True, "status": "ok", "database": "connected", "redis": "connected",
                        "migration_current": True, "migration_version": max(ledger), "release_version": "2.8.8" if name == "old" else "2.8.11"},
                        "expected": ledger, "applied": {} if mismatch and name == "new" else ledger,
                        "migration_state": {"current": True, "version": max(ledger), "applied_count": 9, "expected_count": 9,
                                            "missing": [], "changed": [], "unknown": []}})
                finally:
                    with lock:active[0] -= 1;completed.append(name)
            with self.subTest(mismatch=mismatch), self.patch("deploy_application.time.monotonic", return_value=10.0), self.patch("deploy_application.command", side_effect=child):
                if mismatch:
                    with self.assertRaisesRegex(self.guard.DeployStopped, "nine-migration ledger"):self.deploy.normal_pair_healthy(items)
                else:self.assertTrue(self.deploy.normal_pair_healthy(items))
            self.assertEqual(peak[0], 2);self.assertEqual(active[0], 0);self.assertCountEqual(completed, ["old", "new"])
            self.assertEqual(budgets, [5.0, 5.0]);self.assertEqual(self.deploy.startup_deadline, 15.0)

    def test_retirement_diagnostics_keep_safe_phase_command_and_timeout_reason(self):
        self.deploy.startup_deadline = None
        for cause, expected in [(subprocess.TimeoutExpired("private-not-for-output", 1), "command_timeout"), (None, "deadline_before_command")]:
            clock = [0.0]
            with self.subTest(expected=expected), self.patch("deploy_application.time.monotonic", side_effect=lambda: clock[0]), self.patch(
                "deploy_application.subprocess.run", side_effect=cause
            ) as child:
                with self.assertRaises(self.guard.DeployStopped) as caught:
                    with self.deploy.retirement_budget():
                        with self.deploy.retirement_step("pair_after_public"):
                            if cause is None:clock[0] = 31.0
                            self.deploy.run(["docker", "exec", "private-not-for-output", "python"], timeout=300)
                message = str(caught.exception)
                self.assertIn("type=" + expected, message);self.assertIn("operation=pair_after_public command=backend_probe", message)
                self.assertNotIn("private-not-for-output", message)
                self.assertIsNone(self.deploy.startup_deadline)
                if cause is None:child.assert_not_called()


class ApplicationDeployTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = (Path(r"C:\Program Files\Git\bin\bash.exe") if os.name == "nt"
                    else Path(shutil.which("bash") or "/missing"))
        if not cls.bash.is_file():
            raise RuntimeError("A local Bash is required for the deployment entry-point checks")

    def run_deploy(self, state=None, *, omit=None, missing_python=False):
        initial = fixture() if state is None else state
        with tempfile.TemporaryDirectory(prefix="nerkhbaan-deploy-test-") as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("deploy-nerkhbaan-prod.sh", "deploy_application.py", "verify_operator_gates.py"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            (root / "docker-compose.prod.yaml").write_text("services: {}\n")
            migration_dir = root / "apps/api/db/migrations"
            migration_dir.mkdir(parents=True)
            if initial.get("forward_migration"):
                for migration in (ROOT / "apps/api/db/migrations").glob("*.sql"):
                    if migration.name in initial["desired_migrations"]:
                        shutil.copyfile(migration, migration_dir / migration.name)
                if initial.get("communications"):
                    (root / "VERSION").write_text(initial.get("source_version", "2.8.13") + "\n")
                if initial.get("plan_fault") == "sql_changed":
                    changed = "20261021_001_communications.sql" if initial.get("communications") else REFERENCE_MIGRATION
                    (migration_dir / changed).write_text("DROP TABLE public.prices;\n")
                    initial["desired_migrations"][changed] = hashlib.sha256(
                        b"DROP TABLE public.prices;\n").hexdigest()
            else:
                (migration_dir / "001_initial.sql").write_text("SELECT 1;\n")
            if initial.get("new_migration_in_checkout"):
                (migration_dir / "002_new.sql").write_text("SELECT 2;\n")
            bin_dir = root / "bin"
            bin_dir.mkdir()
            state_path = root / "state.json"
            state_path.write_text(json.dumps(initial))
            env_file, override, evidence, manifest = [root / name for name in
                                                      ("private.env", "override.json", "evidence.json", "images.json")]
            env_file.write_text("PRIVATE=fixture\n")
            for name in ("backend", "migrate"):
                initial["config"]["services"][name]["env_file"] = [{
                    "path": str(override if initial.get("wrong_env_binding") else env_file), "required": True,
                }]
            if initial.get("plan_fault") == "config_migration_command":
                initial["config"]["services"]["migrate"]["command"] = ["python", "other.py"]
            if initial.get("plan_fault") == "config_migration_entrypoint":
                initial["config"]["services"]["migrate"]["entrypoint"] = ["other-tool"]
            state_path.write_text(json.dumps(initial))
            override.write_text("{}")
            manifest.write_text(json.dumps(initial["manifest"]))
            plan_path = root / "migration-plan.json"
            if initial.get("forward_migration"):
                from deploy_application import PLAN_KIND
                plan = {"schema_version": 1, "kind": PLAN_KIND,
                        "commit": initial["commit"], "project": "nerkhbaan",
                        "readiness_url": "https://fixture.invalid/api/health/ready",
                        "images": initial["manifest"]["images"],
                        "baseline_backends": [{"id": item["Id"], "image": item["Image"], "release_version": "2.8.1"}
                                              for item in initial["containers"] if "nerkhbaan-backend-" in item["Id"]],
                        "baseline_migrations": copy.deepcopy(initial["current_migrations"]),
                        "target_migrations": copy.deepcopy(initial["desired_migrations"])}
                proof = {"schema_version": 1, "kind": PLAN_KIND,
                         "checked_at": datetime.now(timezone.utc).isoformat(),
                         "release": {key: copy.deepcopy(value) for key, value in plan.items()
                                     if key not in {"schema_version", "kind"}},
                         "restore": {"isolated": True, "source_database_container_id": "nerkhbaan-postgres-1",
                                     "migration_command": ["python", "-m", "app.migrations.runner"],
                                     "migration_image": initial["manifest"]["images"]["migrate"],
                                     "baseline_migrations": copy.deepcopy(initial["current_migrations"]),
                                     "target_migrations": copy.deepcopy(initial["desired_migrations"]),
                                     "existing_data_sha256_before": "1" * 64, "existing_data_sha256_after": "1" * 64,
                                     "new_table": "public.pricing_reference_records", "new_table_rows": 0},
                         "compatibility": {"old_image": plan["baseline_backends"][0]["image"],
                                           "new_image": initial["manifest"]["images"]["backend"],
                                           "old_release_version": "2.8.1", "old_ready_status": 503,
                                           "old_ready_payload": ready_payload(old=True),
                                           "old_migration_state": {"current": False, "version": REFERENCE_MIGRATION,
                                                                   "applied_count": 9, "expected_count": 8,
                                                                   "missing": [], "changed": [], "unknown": [REFERENCE_MIGRATION]},
                                           "business_probes": [{"path": path, "status": 200, "body_sha256": "2" * 64}
                                                               for path in ("/api/prices", "/api/instruments")],
                                           "new_ready_status": 200, "new_ready_payload": ready_payload()}}
                if initial.get("communications"):
                    from test_deploy_communications import communications_plan_proof
                    plan, proof = communications_plan_proof(initial)
                transcript = root / "restore-transcript.log"
                transcript.write_text("Owned fixture restore transcript. Local mocked deployment only.\n")
                proof["transcript"] = {"path": str(transcript), "sha256": hashlib.sha256(transcript.read_bytes()).hexdigest()}
                fault = initial.get("plan_fault")
                if fault in {"commit", "images", "baseline", "baseline_checksum", "target_checksum"}:
                    if fault == "commit": plan["commit"] = "e" * 40
                    elif fault == "images": plan["images"] = plan["images"] | {"backend": "sha256:" + "e" * 64}
                    elif fault == "baseline": plan["baseline_backends"][0]["id"] = "wrong-old-id"
                    elif fault == "baseline_checksum": plan["baseline_migrations"]["20260718_001_core_pricing.sql"] = "e" * 64
                    else: plan["target_migrations"][REFERENCE_MIGRATION] = "e" * 64
                elif fault == "proof_target": proof["release"]["commit"] = "e" * 40
                elif fault in {"past", "future"}:
                    proof["checked_at"] = (datetime.now(timezone.utc) + timedelta(
                        hours=-25 if fault == "past" else 1)).isoformat()
                elif fault == "no_timezone": proof["checked_at"] = "2026-10-17T12:00:00"
                elif fault == "restore_changed": proof["restore"]["existing_data_sha256_after"] = "e" * 64
                elif fault == "not_isolated": proof["restore"]["isolated"] = False
                elif fault == "source_database": proof["restore"]["source_database_container_id"] = "other-db"
                elif fault == "nonempty_table": proof["restore"]["new_table_rows"] = 1
                elif fault == "business_probe": proof["compatibility"]["business_probes"][0]["status"] = 500
                elif fault == "proof_old_state": proof["compatibility"]["old_migration_state"]["unknown"] += ["other.sql"]
                elif fault == "proof_new_ready": proof["compatibility"]["new_ready_status"] = 503
                elif fault == "missing_new_image": proof["compatibility"].pop("new_image")
                elif fault == "wrong_new_image": proof["compatibility"]["new_image"] = "sha256:" + "e" * 64
                elif fault == "proof_migration_command": proof["restore"]["migration_command"] = ["psql", "raw.sql"]
                elif fault == "proof_migration_image": proof["restore"]["migration_image"] = "sha256:" + "e" * 64
                elif fault == "transcript_hash": proof["transcript"]["sha256"] = "e" * 64
                proof_path = root / "restore-proof.json"
                proof_path.write_text(json.dumps(proof))
                plan["evidence"] = {"path": str(proof_path), "sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest()}
                if fault == "proof_hash": plan["evidence"]["sha256"] = "e" * 64
                if fault == "missing_proof": proof_path.unlink()
                plan_path.write_text(json.dumps(plan))
                for private in (plan_path, proof_path, transcript):
                    if private.exists(): private.chmod(0o600)
            # The validator stays real; only its owned fixture inputs are used.
            from test_verify_operator_gates import evidence as valid_evidence
            evidence.write_text(json.dumps(valid_evidence()))
            resume_path = None
            if initial.get("resume"):
                resume_path = prepare_resume_evidence(root, initial, {
                    "image_manifest": manifest, "operator_evidence": evidence,
                    "compose_override": override, "private_environment": env_file,
                }, plan_path, proof_path, transcript)
                guard_scripts = root / "guard-source/scripts"
                guard_scripts.mkdir(parents=True)
                for name in ("deploy-nerkhbaan-prod.sh", "deploy_application.py"):
                    shutil.copyfile(ROOT / "scripts" / name, guard_scripts / name)
                # The selected wrapper must execute its own guard, not the application's old script.
                (scripts / "deploy_application.py").write_text("raise SystemExit(91)\n")
                scripts = guard_scripts
                state_path.write_text(json.dumps(initial))
            launcher = root / "launcher.py"
            launcher.write_text('''import json, os, runpy, sys
from pathlib import Path
import urllib.request
os.environ['PATH'] = os.environ['FAKE_DEPLOY_BIN'] + os.pathsep + os.environ['PATH']
state = json.loads(Path(os.environ['FAKE_DEPLOY_STATE']).read_text())
if not state.get('external_clis'):
    import contextlib, importlib.util, io, subprocess
    spec = importlib.util.spec_from_file_location('owned_deploy_fixture', os.environ['FAKE_DEPLOY_FIXTURE'])
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    external_run = subprocess.run
    def fixture_run(args, **kwargs):
        kind = Path(args[0]).stem
        if kind not in {'docker', 'git'}: return external_run(args, **kwargs)
        output = io.StringIO()
        with contextlib.redirect_stdout(output): code = fixture_module.fake_cli(kind, args[1:], kwargs.get('input'))
        return subprocess.CompletedProcess(args, code, output.getvalue(), '')
    subprocess.run = fixture_run
class Response:
    def payload(self):
        state = json.loads(Path(os.environ['FAKE_DEPLOY_STATE']).read_text())
        if not state.get('forward_migration'): return {'ready': True}
        old = not state.get('migrated') or any(item['State']['Running'] and item['Id'] in
            {'nerkhbaan-backend-1', 'nerkhbaan-backend-2'} for item in state['containers'])
        migrated = state.get('migrated', False)
        payload = {'ready': not (old and migrated), 'status': 'degraded' if old and migrated else 'ok',
            'database': 'connected', 'redis': 'connected', 'migration_current': not (old and migrated),
            'migration_version': ('20261021_001_communications.sql' if migrated else '20261017_001_iranian_reference_records.sql')
                if state.get('communications') else ('20261017_001_iranian_reference_records.sql' if migrated else '20261011_002_notification_sending_state.sql'),
            'release_version': ('2.8.12' if old else '2.8.13') if state.get('communications') else ('2.8.1' if old else '2.8.8')}
        if migrated and old and state.get('mixed_https_failure'): payload['redis'] = 'disconnected'
        return payload
    @property
    def status(self): return 200 if self.payload().get('ready') else 503
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return json.dumps(self.payload()).encode()
    def geturl(self):
        state = json.loads(Path(os.environ['FAKE_DEPLOY_STATE']).read_text())
        return state.get('response_url', 'https://fixture.invalid/api/health/ready')
def local_readiness(url, timeout):
    assert url == 'https://fixture.invalid/api/health/ready'
    path = Path(os.environ['FAKE_DEPLOY_STATE'])
    state = json.loads(path.read_text())
    state['readiness_checks'] += 1
    path.write_text(json.dumps(state))
    if state.get('readiness_failure_at') == state['readiness_checks']:
        raise OSError('fixture readiness failure')
    return Response()
class Opener:
    def open(self, url, timeout): return local_readiness(url, timeout)
def local_opener(*handlers):
    assert len(handlers) == 1
    assert handlers[0].redirect_request(None, None, 302, '', {}, 'http://other.invalid') is None
    return Opener()
urllib.request.build_opener = local_opener
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
''')
            python_script = f"#!/bin/sh\nexec '{Path(sys.executable).as_posix()}' '{launcher.as_posix()}' \"$@\"\n"
            for name in ("python", "python3"):
                (bin_dir / name).write_text(python_script)
                (bin_dir / name).chmod(0o755)
            for kind in ("docker", "git"):
                if os.name == "nt":
                    wrapper = bin_dir / f"{kind}.cmd"
                    wrapper.write_text(f'@"{sys.executable}" "{Path(__file__).resolve()}" --fake-cli {kind} %*\n')
                else:
                    wrapper = bin_dir / kind
                    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).resolve()}" --fake-cli {kind} "$@"\n')
                    wrapper.chmod(0o755)
            env = dict(os.environ, RELEASE_DIR=str(root), COMPOSE_PROJECT_NAME="nerkhbaan",
                       COMPOSE_ENV_FILE=str(env_file), COMPOSE_OVERRIDE_FILE=str(override),
                       OPERATOR_EVIDENCE_PATH=str(evidence), DEPLOY_IMAGE_MANIFEST=str(manifest),
                       DEPLOY_READINESS_URL="https://fixture.invalid/api/health/ready",
                       FAKE_DEPLOY_STATE=str(state_path), FAKE_DEPLOY_BIN=str(bin_dir),
                       FAKE_DEPLOY_FIXTURE=str(Path(__file__).resolve()),
                       PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            env.pop("BACKEND_REPLICAS", None)
            env.pop("DEPLOY_WAIT_SECONDS", None)
            if initial.get("new_stays_starting"):
                env["DEPLOY_WAIT_SECONDS"] = "1"
            env.pop("DEPLOY_MIGRATION_PLAN", None)
            env.pop("DEPLOY_RESUME_PLAN", None)
            if initial.get("forward_migration") and not initial.get("no_migration_plan"):
                env["DEPLOY_MIGRATION_PLAN"] = str(plan_path)
            if resume_path and not initial.get("resume_no_plan"):
                env["DEPLOY_RESUME_PLAN"] = str(resume_path)
            if omit:
                env.pop(omit, None)
            if missing_python:
                (bin_dir / "python").unlink()
                (bin_dir / "python3").unlink()
                env["PATH"] = str(bin_dir)
            entrypoint = ([sys.executable, str(launcher), str(scripts / "deploy_application.py")]
                          if initial.get("direct_entrypoint") else
                          [str(self.bash), (scripts / "deploy-nerkhbaan-prod.sh").as_posix()])
            result = subprocess.run(entrypoint,
                                    env=env, capture_output=True, text=True,
                                    timeout=180 if initial.get("external_clis") else 90)
            final = json.loads(state_path.read_text())
            return result, final, copy.deepcopy(initial)

    def assert_protected_unchanged(self, initial, final):
        mutable = {"backend", "frontend", "admin-frontend", "price-feed-pull"}
        expected = [item for item in initial["containers"] if not (
            item["Config"]["Labels"]["com.docker.compose.project"] == "nerkhbaan" and
            item["Config"]["Labels"]["com.docker.compose.service"] in mutable)]
        by_id = {item["Id"]: item for item in final["containers"]}
        self.assertEqual(expected, [by_id[item["Id"]] for item in expected])

    def assert_no_mutation(self, final):
        self.assertFalse(any(command[0] == "docker" and any(value in {"run", "up", "stop", "rm"}
                                                          for value in command[1:])
                             and not (command[1] == "run" and "nerkhbaan.deploy-probe=migrations" in command)
                             for command in final["commands"]))

    def test_explicit_resume_uses_recorded_candidate_then_overlap_without_migration(self):
        result, final, initial = self.run_deploy(resume_fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_protected_unchanged(initial, final)
        self.assertFalse(any("run" in call and call[-1] == "migrate" for call in final["commands"]))
        self.assertEqual(final["scale_runs"], 1)
        mutations = [call for call in final["commands"] if call[0] == "docker" and (
            call[1] in {"stop", "rm"} or "up" in call)]
        self.assertEqual(mutations[0], ["docker", "stop", "--time", "20", "nerkhbaan-backend-1"])
        self.assertEqual([call[-1] for call in mutations if call[1] == "rm"],
                         ["nerkhbaan-backend-1", "nerkhbaan-backend-2"])
        self.assertIn(CANDIDATE_ID, {item["Id"] for item in final["containers"]})
        self.assertEqual(final["applied_migrations"], initial["desired_migrations"])
        self.assertIn("without a migration run", result.stdout)

    def test_resume_requires_explicit_plan_and_original_migration_evidence(self):
        for flag in ("resume_no_plan", "no_migration_plan"):
            with self.subTest(flag=flag):
                result, final, _ = self.run_deploy(resume_fixture() | {flag: True})
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_mutation(final)

    def test_resume_rejects_evidence_drift_identity_clock_config_and_unproved_ci_before_mutation(self):
        cases = ("ci_object_shape", "observation_object_shape", "ci_commit", "ci_failed", "ci_missing_job", "ci_duplicate_job", "old_probe_failure",
                 "extra_unknown_migration", "new_probe_failure", "semantic_false", "semantic_integer",
                 "semantic_missing", "resolved_model", "service_hash", "stale", "future", "naive_clock",
                 "binding", "candidate_id", "candidate_hash", "old_identity", "protected_identity",
                 "candidate_unhealthy", "unknown_candidate", "wrong_ledger", "file_hash", "missing_file")
        if os.name != "nt":
            cases += ("private_mode",)
        for fault in cases:
            with self.subTest(fault=fault):
                result, final, _ = self.run_deploy(resume_fixture() | {"resume_fault": fault})
                self.assertNotEqual(result.returncode, 0, fault)
                self.assert_no_mutation(final)

    def test_resume_rejects_dirty_or_changed_guard_source_and_live_candidate_failure(self):
        for flag in ("guard_dirty", "guard_api_changed", "dirty", "new_ready_failure", "old_ready_failure",
                     "old_other_migration_failure", "mixed_https_failure"):
            with self.subTest(flag=flag):
                result, final, _ = self.run_deploy(resume_fixture() | {flag: True})
                self.assertNotEqual(result.returncode, 0, flag)
                self.assert_no_mutation(final)

    def test_resume_second_candidate_failure_retains_recorded_candidate_and_last_old(self):
        result, final, initial = self.run_deploy(resume_fixture() | {"fail_scale": 1})
        self.assertNotEqual(result.returncode, 0)
        self.assert_protected_unchanged(initial, final)
        self.assertEqual([call[-1] for call in final["commands"] if call[:2] == ["docker", "rm"]],
                         ["nerkhbaan-backend-1"])
        by_id = {item["Id"]: item for item in final["containers"]}
        self.assertTrue(by_id[CANDIDATE_ID]["State"]["Running"])
        self.assertEqual(by_id[CANDIDATE_ID]["State"]["Health"]["Status"], "healthy")
        self.assertTrue(by_id["nerkhbaan-backend-2"]["State"]["Running"])
        self.assertFalse(any("run" in call and call[-1] == "migrate" for call in final["commands"]))

    def test_resume_rechecks_private_evidence_before_removing_stopped_old(self):
        for flag in ("resume_file_drift_after_stop", "resume_candidate_drift_after_stop"):
            with self.subTest(flag=flag):
                result, final, _ = self.run_deploy(resume_fixture() | {flag: True})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:2] == ["docker", "rm"] for call in final["commands"]))
                by_id = {item["Id"]: item for item in final["containers"]}
                self.assertFalse(by_id["nerkhbaan-backend-1"]["State"]["Running"])
                self.assertTrue(by_id[CANDIDATE_ID]["State"]["Running"])
                self.assertTrue(by_id["nerkhbaan-backend-2"]["State"]["Running"])

    def test_rollout_only_updates_application_with_healthy_overlap(self):
        result, final, initial = self.run_deploy(fixture() | {"external_clis": True})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_protected_unchanged(initial, final)
        calls = final["commands"]
        self.assertFalse(any(value in {"pull", "build", "down", "--force-recreate", "-v"}
                             for call in calls for value in call if value != "--pull"))
        mutations = [call for call in calls if call[0] == "docker" and any(
            value in {"run", "up", "stop", "rm"} for value in call)]
        self.assertEqual([call[-1] for call in mutations if call[1] in {"stop", "rm"}],
                         ["nerkhbaan-backend-1", "nerkhbaan-backend-1",
                          "nerkhbaan-backend-2", "nerkhbaan-backend-2"])
        for call in mutations:
            if call[1] == "compose":
                self.assertIn("--no-deps", call)
                self.assertEqual(call[call.index("--pull") + 1], "never")
                self.assertIn("nerkhbaan", call)
                self.assertIn("--env-file", call)
                self.assertEqual(call.count("-f"), 2)
        up = [call for call in mutations if "up" in call]
        self.assertEqual(len(up), 3)
        self.assertEqual(up[-1][-3:], ["frontend", "admin-frontend", "price-feed-pull"])
        self.assertGreaterEqual(final["readiness_checks"], 9)

    def test_changing_inspect_mount_order_keeps_reviewed_preflight_and_rollout_valid(self):
        for selected in ("shared-edge-edge-1", "nerkhbaan-backend-1"):
            with self.subTest(container_id=selected):
                state = fixture() | {"reorder_inspected_mounts": True}
                target = next(item for item in state["containers"] if item["Id"] == selected)
                target["Mounts"] = multiple_mounts()
                result, final, initial = self.run_deploy(state)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertGreater(final["inspect_reads"], 2)
                self.assert_protected_unchanged(initial, final)

    def test_schema_addition_change_unknown_or_image_mismatch_refused_before_migration(self):
        for case in ("addition", "changed", "unknown", "image"):
            with self.subTest(case=case):
                state = fixture()
                if case == "addition":
                    state["new_migration_in_checkout"] = True
                    state["desired_migrations"]["002_new.sql"] = hashlib.sha256(b"SELECT 2;\n").hexdigest()
                elif case == "changed":
                    state["applied_migrations"]["001_initial.sql"] = "changed"
                elif case == "unknown":
                    state["applied_migrations"]["future.sql"] = "unknown"
                else:
                    state["desired_migrations"]["001_initial.sql"] = "image-source-mismatch"
                result, final, initial = self.run_deploy(state)
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_mutation(final)
                self.assert_protected_unchanged(initial, final)

    def test_pinned_addition_requires_plan_and_retains_exact_protected_identity(self):
        result, final, initial = self.run_deploy(forward_fixture() | {"no_migration_plan": True})
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation(final)
        result, final, initial = self.run_deploy(forward_fixture() | {"external_clis": True})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_protected_unchanged(initial, final)
        self.assertEqual(final["applied_migrations"], final["desired_migrations"])
        self.assertEqual(final["scale_runs"], 2)
        scaled = [call for call in final["commands"] if "--scale" in call]
        self.assertTrue(all("--wait" not in call and "--no-recreate" in call for call in scaled))
        self.assertIn("migration-only readiness", result.stdout)
        self.assertEqual([call[-1] for call in final["commands"] if call[:2] == ["docker", "rm"]],
                         ["nerkhbaan-backend-1", "nerkhbaan-backend-2"])

    def test_resolved_environment_hash_accepts_only_exact_new_container_identity(self):
        for tampered in (False, True):
            with self.subTest(tampered_actual_hash=tampered):
                state = forward_fixture() | {"raw_config_hash": OLD_HASH, "wrong_new_hash": tampered}
                secret = "owned-fixture-$private-value"
                state["config"]["services"]["backend"]["environment"] = {"FIXTURE_SECRET": secret}
                result, final, initial = self.run_deploy(state)
                self.assertEqual(final.get("raw_hash_reads", 0), 0)
                self.assertEqual(final.get("resolved_hash_reads"), 4)
                self.assertNotIn(secret, result.stdout + result.stderr)
                self.assertTrue(all(secret not in " ".join(call) for call in final["commands"]))
                self.assert_protected_unchanged(initial, final)
                if tampered:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Unexpected backend", result.stderr)
                    self.assertFalse(any(call[:2] in (["docker", "stop"], ["docker", "rm"])
                                         for call in final["commands"]))
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(final["scale_runs"], 2)

    def test_migration_plan_rejects_wrong_binding_or_unproven_restore_before_mutation(self):
        for fault in ("commit", "images", "baseline", "baseline_checksum", "target_checksum", "proof_target",
                      "past", "future", "no_timezone", "restore_changed", "not_isolated", "source_database",
                      "nonempty_table", "business_probe", "proof_old_state", "proof_new_ready", "transcript_hash",
                      "proof_hash", "missing_proof", "sql_changed", "missing_new_image", "wrong_new_image",
                      "config_migration_command", "config_migration_entrypoint", "proof_migration_command",
                      "proof_migration_image"):
            with self.subTest(fault=fault):
                result, final, _ = self.run_deploy(forward_fixture() | {"plan_fault": fault})
                self.assertNotEqual(result.returncode, 0, fault)
                self.assert_no_mutation(final)

    def test_reviewed_transition_rejects_live_drift_and_unrelated_readiness_failure(self):
        for flag in ("baseline_probe_failure", "post_migration_unknown", "post_migration_checksum_change",
                     "old_ready_failure", "old_other_migration_failure", "new_ready_failure", "mixed_https_failure",
                     "protected_drift", "old_identity_drift", "wrong_new_image", "wrong_new_network",
                     "proof_drift_after_migrate", "proof_drift_after_scale", "new_expected_migrations_failure",
                     "new_stays_starting"):
            with self.subTest(flag=flag):
                result, final, _ = self.run_deploy(forward_fixture() | {flag: True})
                self.assertNotEqual(result.returncode, 0, flag)
                self.assertFalse(any(call[:2] in (["docker", "stop"], ["docker", "rm"])
                                     for call in final["commands"]))
                if flag == "baseline_probe_failure":
                    self.assert_no_mutation(final)
                else:
                    self.assertTrue(final.get("migrated"), f"{flag} must reach the forward ledger before failure")
                    if flag not in {"post_migration_unknown", "post_migration_checksum_change", "old_ready_failure",
                                    "old_other_migration_failure", "mixed_https_failure", "proof_drift_after_migrate"}:
                        self.assertEqual(final["scale_runs"], 1, f"{flag} must reach new-image startup")

    def test_additive_new_replica_failure_keeps_old_running_with_recorded_forward_schema(self):
        result, final, initial = self.run_deploy(forward_fixture() | {"fail_scale": 1})
        self.assertNotEqual(result.returncode, 0)
        self.assert_protected_unchanged(initial, final)
        self.assertEqual(final["applied_migrations"], final["desired_migrations"])
        for selected in ("nerkhbaan-backend-1", "nerkhbaan-backend-2"):
            old = next(item for item in final["containers"] if item["Id"] == selected)
            self.assertTrue(old["State"]["Running"])
            self.assertEqual(old["State"]["Health"]["Status"], "unhealthy")
        self.assertFalse(any(call[:2] == ["docker", "stop"] for call in final["commands"]))

    def test_requires_explicit_reviewed_runtime_inputs(self):
        for name in ("RELEASE_DIR", "COMPOSE_PROJECT_NAME", "COMPOSE_ENV_FILE", "COMPOSE_OVERRIDE_FILE",
                     "OPERATOR_EVIDENCE_PATH", "DEPLOY_IMAGE_MANIFEST", "DEPLOY_READINESS_URL"):
            with self.subTest(name=name):
                result, final, _ = self.run_deploy(omit=name)
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_mutation(final)
        result, final, _ = self.run_deploy(missing_python=True)
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation(final)

    def test_refuses_mutable_images_manifest_mismatch_dirty_or_absent_data(self):
        for case in ("mutable", "manifest", "commit", "dirty", "absent", "network", "replicas", "env_binding", "rights_off", "rights_unknown", "migration_rights_off"):
            with self.subTest(case=case):
                state = fixture()
                if case == "mutable":
                    state["config"]["services"]["backend"]["image"] = "nerkhbaan-api:latest"
                elif case == "manifest":
                    state["manifest"]["images"]["backend"] = "sha256:wrong"
                elif case == "commit":
                    state["manifest"]["commit"] = "d" * 40
                elif case == "dirty":
                    state["dirty"] = True
                elif case == "absent":
                    state["containers"] = [item for item in state["containers"] if "postgres" not in item["Id"]]
                elif case == "network":
                    state["config"]["networks"]["app"]["name"] = "replacement-network"
                elif case == "replicas":
                    state["containers"].append(container("backend", "unknown-extra"))
                elif case in {"rights_off", "rights_unknown", "migration_rights_off"}:
                    service = "migrate" if case == "migration_rights_off" else "backend"
                    state["config"]["services"][service].setdefault("environment", {})["PRICING_RIGHTS_ENFORCED"] = "off" if case != "rights_unknown" else "unknown"
                else:
                    state["wrong_env_binding"] = True
                result, final, _ = self.run_deploy(state)
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_mutation(final)

    def test_first_new_replica_failure_keeps_both_old_replicas(self):
        state = fixture() | {"fail_scale": 1}
        result, final, initial = self.run_deploy(state)
        self.assertNotEqual(result.returncode, 0)
        self.assert_protected_unchanged(initial, final)
        self.assertFalse(any(call[1] in {"stop", "rm"} for call in final["commands"] if call[0] == "docker"))
        self.assertEqual(sum(item["State"]["Health"]["Status"] == "healthy" for item in final["containers"]
                             if item["Config"]["Labels"]["com.docker.compose.service"] == "backend"), 2)

    def test_second_new_replica_failure_keeps_surviving_healthy_pair(self):
        result, final, initial = self.run_deploy(fixture() | {"fail_scale": 2})
        self.assertNotEqual(result.returncode, 0)
        self.assert_protected_unchanged(initial, final)
        removed = [call[-1] for call in final["commands"] if call[:2] == ["docker", "rm"]]
        self.assertEqual(removed, ["nerkhbaan-backend-1"])
        self.assertEqual(sum(item["State"]["Health"]["Status"] == "healthy" for item in final["containers"]
                             if item["Config"]["Labels"]["com.docker.compose.service"] == "backend"), 2)

    def test_refuses_changed_old_identity_wrong_image_and_protected_drift(self):
        for flag in ("old_identity_drift", "wrong_new_image", "wrong_new_network", "protected_drift", "config_drift"):
            with self.subTest(flag=flag):
                result, final, _ = self.run_deploy(fixture() | {flag: True})
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:2] in (["docker", "stop"], ["docker", "rm"])
                                     for call in final["commands"]))

    def test_tag_retargeting_stops_further_actions(self):
        result, final, _ = self.run_deploy(fixture() | {"tag_drift": True})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(final["scale_runs"], 1)
        self.assertEqual(len([call for call in final["commands"] if call[:2] == ["docker", "rm"]]), 0)

    def test_https_failure_leaves_old_replicas_running(self):
        result, final, _ = self.run_deploy(fixture() | {"readiness_failure_at": 3})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[:2] == ["docker", "stop"] for call in final["commands"]))

    def test_readiness_rejects_changed_final_url(self):
        for url in ("http://fixture.invalid/api/health/ready", "https://other.invalid/api/health/ready"):
            with self.subTest(url=url):
                result, final, _ = self.run_deploy(fixture() | {"response_url": url})
                self.assertNotEqual(result.returncode, 0)
                self.assert_no_mutation(final)

    def test_migration_failure_or_incompatible_readiness_never_removes_old(self):
        for flag in ("migration_failure", "migration_changes_readiness"):
            with self.subTest(flag=flag):
                result, final, initial = self.run_deploy(fixture() | {flag: True})
                self.assertNotEqual(result.returncode, 0)
                self.assert_protected_unchanged(initial, final)
                self.assertEqual(final["scale_runs"], 0)
                self.assertFalse(any(call[:2] == ["docker", "stop"] for call in final["commands"]))

    def test_already_current_backend_keeps_ids_and_skips_scale(self):
        state = fixture()
        for item in state["containers"]:
            if item["Config"]["Labels"]["com.docker.compose.service"] == "backend":
                item["Image"] = state["manifest"]["images"]["backend"]
                item["Config"]["Labels"]["com.docker.compose.config-hash"] = NEW_HASH
        result, final, initial = self.run_deploy(state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_protected_unchanged(initial, final)
        self.assertEqual(final["scale_runs"], 0)
        self.assertFalse(any(call[:2] == ["docker", "rm"] for call in final["commands"]))

    def test_same_image_new_config_rolls_and_missing_admin_is_not_started(self):
        state = fixture()
        state["containers"] = [item for item in state["containers"] if "admin-frontend" not in item["Id"]]
        for item in state["containers"]:
            if item["Config"]["Labels"]["com.docker.compose.service"] == "backend":
                item["Image"] = state["manifest"]["images"]["backend"]
        result, final, initial = self.run_deploy(state)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_protected_unchanged(initial, final)
        self.assertEqual(final["scale_runs"], 2)
        up = [call for call in final["commands"] if "up" in call]
        self.assertEqual(up[-1][-2:], ["frontend", "price-feed-pull"])

    def test_client_update_failure_or_config_drift_retains_healthy_backend_and_data(self):
        for flag in ("client_failure", "client_config_drift", "client_wrong_hash"):
            with self.subTest(flag=flag):
                result, final, initial = self.run_deploy(fixture() | {flag: True})
                self.assertNotEqual(result.returncode, 0)
                self.assert_protected_unchanged(initial, final)
                current = [item for item in final["containers"] if
                           item["Config"]["Labels"]["com.docker.compose.service"] == "backend"]
                self.assertEqual(len(current), 2)
                self.assertTrue(all(item["State"]["Running"] and item["State"]["Health"]["Status"] == "healthy"
                                    for item in current))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake-cli":
        raise SystemExit(fake_cli(sys.argv[2], sys.argv[3:]))
    unittest.main()
