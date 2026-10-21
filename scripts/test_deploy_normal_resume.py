"""Exercise the complete guard against an owned, deterministic stopped-old fixture."""
from __future__ import annotations

import copy
import errno
import hashlib
import io
import json
import os
import ssl
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import deploy_application as guard
import test_deploy_application as existing
from test_verify_operator_gates import evidence as operator_evidence
from verify_operator_gates import validate as validate_operator


ROOT = Path(__file__).resolve().parents[1]
KIND = "normal-same-ledger-resume-after-stopped-old-v1"
OLD_VERSION, VERSION = "2.8.8", "2.8.11"
APP, GUARD = "a" * 40, "d" * 40
STOPPED, SURVIVOR, ADDED = [hashlib.sha256(value.encode()).hexdigest() for value in (
    "owned-stopped-api", "owned-surviving-api", "owned-added-api")]
CI_NAMES = (
    "Node lock and builds", "Compose configuration", "Build and scan web image",
    "Python static and unit checks", "Desktop package", "Repository security scans",
    "Build and scan relay image", "Build and scan telegram image", "Feed pull Go checks",
    "Build and scan api image", "Build and scan feed-pull image", "Browser auth and alerts",
    "Build and scan admin image", "Timescale, Redis, and migrations", "Build and scan edge image",
)
BINDING_NAMES = (
    "operator-gates.json", "operator-finalization-proof.json", "operator-evidence-index.json",
    "source-rights-reviewed.json", "source-rights-probe-attempt.json", "prepared-images.json",
    "execution-plan.json", "stage-proof.json", "predeployment-baseline.json",
    "reviewed-private-environment-proof.json", "ci-run.json", "ci-jobs.json",
    "runtime-trivy-summary.json", "runtime-build-checks.json", "private_environment", "runtime_override",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def roles(rows):
    return {row["Id"]: {"project": guard.project(row), "service": guard.service(row)} for row in rows}


def fingerprints(rows):
    return {row["Id"]: guard.fingerprint(row) for row in rows}


def normal_payload(version=VERSION):
    return {"ready": True, "status": "ok", "database": "connected", "redis": "connected",
            "migration_current": True, "migration_version": existing.REFERENCE_MIGRATION,
            "release_version": version}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        if seconds < 0:
            raise AssertionError("Negative fixture sleep")
        self.now += seconds


class Response(io.BytesIO):
    def __init__(self, payload, url, status=200):
        super().__init__(json.dumps(payload).encode())
        self.url, self.status = url, status

    def geturl(self):
        return self.url


class OwnedGuardFixture:
    """Only fake Docker/Git commands; all evidence and guard validation stay real."""

    def __enter__(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="nerkhbaan-normal-resume-")
        self.root = Path(self.temporary.name)
        self.state_lock = threading.RLock()
        self.clock, self.trace, self.http_calls = Clock(), [], []
        self.faults, self.http_events = {}, []
        self.transient_seen, self.child_timeouts = False, []
        self.active_probes, self.maximum_active_probes = 0, 0
        self.probe_entries, self.probe_threads = 0, []
        self.probe_gate = None
        state = existing.fixture()
        state["guard_commit"] = GUARD
        state["config"]["services"]["migrate"]["image"] = state["config"]["services"]["backend"]["image"]
        old_image = "sha256:" + digest(b"owned-old-api")
        for row, identifier in zip(state["containers"][:2], (STOPPED, SURVIVOR)):
            row["Id"], row["Image"] = identifier, old_image
            row["State"].update(ExitCode=0, OOMKilled=False)
        for index in range(6):
            state["containers"].append(existing.container("protected", str(index), owner=f"other-{index}"))
        self.write("VERSION", VERSION + "\n", raw=True)
        directory = self.root / "apps/api/db/migrations"
        directory.mkdir(parents=True)
        migrations = {}
        for name in sorted(guard.COMMUNICATIONS_BASELINE):
            source = ROOT / "apps/api/db/migrations" / name
            data = source.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").encode()
            (directory / source.name).write_bytes(data)
            migrations[source.name] = digest(data)
        if migrations != guard.COMMUNICATIONS_BASELINE:
            raise AssertionError("The owned fixture must bind the actual nine immutable migrations")
        for name in ("current_migrations", "desired_migrations", "applied_migrations"):
            state[name] = copy.deepcopy(migrations)
        self.paths = {
            "private_environment": self.write("private.env", "PRIVATE=owned-fixture-only\n", raw=True),
            "runtime_override": self.write("runtime.override.json", {}),
            "prepared-images.json": self.write("prepared-images.json", state["manifest"]),
            "operator-gates.json": self.write("operator-gates.json", operator_evidence()),
        }
        for name in BINDING_NAMES:
            if name not in self.paths:
                self.paths[name] = self.write(name, {"owned_fixture": True, "name": name})
        for name in ("backend", "migrate"):
            state["config"]["services"][name]["env_file"] = [{
                "path": str(self.paths["private_environment"]), "required": True}]
        self.state_path = self.root / "state.json"
        self.save(state)
        self.original = copy.deepcopy(state["containers"])
        self.bindings = {name: self.reference(path) for name, path in self.paths.items()}
        self.env = {
            "RELEASE_DIR": str(self.root), "COMPOSE_PROJECT_NAME": "nerkhbaan",
            "COMPOSE_ENV_FILE": str(self.paths["private_environment"]),
            "COMPOSE_OVERRIDE_FILE": str(self.paths["runtime_override"]),
            "DEPLOY_IMAGE_MANIFEST": str(self.paths["prepared-images.json"]),
            "OPERATOR_EVIDENCE_PATH": str(self.paths["operator-gates.json"]),
            "DEPLOY_READINESS_URL": "https://fixture.invalid/api/health/ready", "BACKEND_REPLICAS": "2",
        }
        return self

    def __exit__(self, *args):
        self.temporary.cleanup()

    def write(self, name, value, *, raw=False):
        path = self.root / name
        path.write_text(value if raw else json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
        return path

    @staticmethod
    def reference(path):
        return {"path": str(path), "sha256": digest(path.read_bytes())}

    def read(self):
        with self.state_lock:
            return copy.deepcopy(self._state)

    def save(self, state):
        with self.state_lock:
            self._state = copy.deepcopy(state)

    def probe(self, row):
        ledger = self.read()["desired_migrations"]
        version = VERSION if row["Image"] == self.read()["manifest"]["images"]["backend"] else OLD_VERSION
        result = {"id": row["Id"], "image": row["Image"], "status": 200,
                  "payload": normal_payload(version), "expected": ledger, "applied": ledger,
                  "migration_state": {"current": True, "version": existing.REFERENCE_MIGRATION,
                                      "applied_count": 9, "expected_count": 9,
                                      "missing": [], "changed": [], "unknown": []}}
        if self.faults.get("failed_probe") == row["Id"]:
            result["payload"]["redis"] = "disconnected"
        return result

    def command(self, args, *, cwd, timeout=300, input_text=None):
        probe = args[:2] == ["docker", "exec"] and "urlopen" in args[-1]
        gate = None
        if probe:
            with self.state_lock:
                self.active_probes += 1
                self.maximum_active_probes = max(self.maximum_active_probes, self.active_probes)
                self.probe_threads.append((args[2], threading.get_ident()))
                self.probe_entries += 1
                if self.probe_gate is not None and self.probe_entries <= 2:
                    gate = self.probe_gate
        try:
            if gate is not None:
                gate.wait(timeout=5)
            with self.state_lock:
                return self.command_serial(args, cwd=cwd, timeout=timeout, input_text=input_text)
        finally:
            if probe:
                with self.state_lock:
                    self.active_probes -= 1

    def command_serial(self, args, *, cwd, timeout=300, input_text=None):
        self.clock.now += 0.001
        if timeout <= 0:
            raise AssertionError("Every child command needs a positive remaining budget")
        if self.faults.get("slow_retirement_check") and self.transient_seen:
            self.child_timeouts.append(timeout)
            self.clock.now += timeout
            raise guard.DeployStopped("Owned child command reached its deadline")
        kind = Path(args[0]).stem
        state = self.read()
        if kind not in {"docker", "git"}:
            if len(args) == 3 and Path(args[1]).name == "verify_operator_gates.py":
                errors = validate_operator(Path(args[2]))
                if errors:
                    raise guard.DeployStopped("Owned operator evidence rejected")
                return "Operator evidence passed"
            raise AssertionError("Unexpected real process in owned fixture: " + kind)
        output = io.StringIO()
        fixture = self

        class StateFile:
            def read_text(self):
                return json.dumps(fixture._state)

            def write_text(self, value):
                fixture._state = json.loads(value)

        def local_path(value, *parts, **kwargs):
            if not parts and str(value) == str(self.state_path):
                return StateFile()
            return Path(value, *parts, **kwargs)

        with patch.dict(os.environ, {"FAKE_DEPLOY_STATE": str(self.state_path)}), patch.object(
            existing, "Path", local_path
        ), redirect_stdout(output):
            code = existing.fake_cli(kind, args[1:], input_text)
        state = self.read()
        if args[:3] == ["docker", "image", "inspect"] and len(args) > 4 and self.faults.get("batch_response"):
            rows = json.loads(output.getvalue())
            fault = self.faults["batch_response"]
            if fault == "missing":
                rows.pop()
            elif fault == "reordered":
                rows.reverse()
            elif fault == "wrong_id":
                rows[0]["Id"] = "sha256:" + "f" * 64
            output = io.StringIO(json.dumps(rows))
        if args[:2] == ["docker", "exec"] and "urlopen" in args[-1]:
            row = next(row for row in state["containers"] if row["Id"] == args[2])
            if not row["State"]["Running"]:
                raise AssertionError("A stopped API cannot execute a readiness probe")
            output = io.StringIO(json.dumps(self.probe(row)))
            if self.faults.get("late_probe") == row["Id"] and timeout < 30:
                self.clock.now += 31
        if args[:2] == ["docker", "stop"]:
            row = next(row for row in state["containers"] if row["Id"] == args[-1])
            row["State"].update(ExitCode=137, OOMKilled=False)
        if kind == "docker" and "up" in args and "--scale" in args:
            for row in state["containers"]:
                if row["Id"].startswith("nerkhbaan-backend-new-"):
                    row["Id"] = ADDED if state["scale_runs"] == 1 else digest(b"owned-second-new-api")
        if args[:2] == ["docker", "rm"] and args[-1] == STOPPED and self.faults.get("late_candidate_drift"):
            candidate = next(row for row in state["containers"] if row["Id"] == ADDED)
            candidate["HostConfig"]["RestartPolicy"]["Name"] = "always"
        self.save(state)
        self.trace.append({"args": list(args), "count": len(state["containers"]),
                           "running_backends": [r["Id"] for r in state["containers"]
                                                if guard.service(r) == "backend" and r["State"]["Running"]],
                           "timeout": timeout})
        if code:
            raise guard.DeployStopped("Owned fixture command failed")
        return output.getvalue().strip()

    def opener(self, *_args):
        fixture = self

        class Opener:
            def open(self, url, timeout):
                fixture.http_calls.append((url, timeout))
                fixture.clock.now += min(timeout, 1.0)
                event = fixture.http_events.pop(0) if fixture.http_events else None
                if fixture.faults.get("https_failure_from") is not None and len(fixture.http_calls) >= fixture.faults["https_failure_from"]:
                    event = "timeout"
                if event == "timeout":
                    fixture.transient_seen = True
                    raise TimeoutError("owned timeout")
                if event == "reset":
                    raise URLError(ConnectionResetError(errno.ECONNRESET, "owned reset"))
                if event == "unknown_reset":
                    raise URLError(ConnectionResetError("unclassified owned reset"))
                if event == "tls":
                    raise URLError(ssl.SSLCertVerificationError("owned certificate rejection"))
                if event in (502, 503, 504):
                    raise HTTPError(url, event, "owned gateway error", {}, io.BytesIO(b"{}"))
                if event == "late":
                    fixture.clock.now += 1000
                payload = normal_payload()
                if event == "bad_payload":
                    payload["ready"] = False
                response = Response(payload, "https://other.invalid/api/health/ready" if event == "redirect" else url)
                if event == "bad_json":
                    response = io.BytesIO(b"{not-json}")
                    response.status, response.geturl = 200, lambda: url
                return response

        return Opener()

    def run(self):
        output = io.StringIO()
        with patch.dict(os.environ, self.env, clear=True), patch.object(guard, "command", self.command), patch.object(
            guard, "build_opener", self.opener
        ), patch.object(guard.time, "monotonic", self.clock.monotonic), patch.object(
            guard.time, "sleep", self.clock.sleep
        ), redirect_stdout(output), redirect_stderr(output):
            result = guard.main()
        return result, output.getvalue()

    def fail_after_first_stop(self):
        self.faults["https_failure_from"] = 6
        result, output = self.run()
        if result == 0:
            raise AssertionError("The original HTTPS failure must be retained as a failed attempt")
        self.faults.pop("https_failure_from")
        return output

    def seed_original_retirement_failure(self):
        state = self.read()
        old = next(row for row in state["containers"] if row["Id"] == STOPPED)
        old["State"].update(Running=False, ExitCode=137, OOMKilled=False)
        for network in old["NetworkSettings"]["Networks"].values():
            network.update(EndpointID="", IPAddress="")
        candidate = existing.container("backend", "recorded", image=state["manifest"]["images"]["backend"],
                                       config_hash=existing.NEW_HASH)
        candidate["Id"] = ADDED
        state["containers"].append(candidate)
        state["scale_runs"] = 1
        self.save(state)
        self.prepare_resume("Owned seed of the earlier failed guard; no live operation.\n")

    def prepare_resume(self, output):
        state = self.read()
        stamp = datetime.now(timezone.utc).isoformat()
        service_hashes = {name: existing.NEW_HASH for name in ("backend", "frontend", "admin-frontend", "price-feed-pull")}
        networks = {name: {"nerkhbaan-network": "stable-network"} for name in service_hashes}
        model_sha = digest(json.dumps(state["config"], sort_keys=True, separators=(",", ":")).encode())
        preflight = {"mode": "preflight", "commit": APP, "passed": True, "checked_at": stamp,
                     "release_version": VERSION, "same_ledger_no_transition_plan_valid": True,
                     "container_fingerprints": fingerprints(self.original), "private_bindings": self.bindings,
                     "protected_container_count": 17, "baseline_backend_ids": [STOPPED, SURVIVOR],
                     "service_hashes": service_hashes, "service_networks": networks,
                     "resolved_configuration_sha256": model_sha}
        preflight_path = self.write("preflight-proof.json", preflight)
        self.write("current-guard-failure.log", output, raw=True)
        # The resume plan consumes the earlier guard's exact recorded log format.
        original_log = ("Preflight passed. Existing stack identities retained.\n"
                        "Deploy stopped: Target HTTPS readiness failed. Keep current replicas; review private logs before retry.\n")
        log = self.write("deploy-owned-original.log", original_log, raw=True)
        attempt = {"mode": "deploy", "commit": APP, "started_at": stamp, "completed": False,
                   "release_version": VERSION, "private_log": str(log), "private_bindings": self.bindings,
                   "preflight_proof_sha256": digest(preflight_path.read_bytes()), "protected_container_count": 17,
                   "baseline_container_fingerprints": fingerprints(self.original),
                   "baseline_container_roles": roles(self.original), "service_hashes": service_hashes,
                   "service_networks": networks, "resolved_configuration_sha256": model_sha}
        attempt_path = self.write("deployment-wrapper-attempt.json", attempt)
        failed = {"mode": "deploy", "commit": APP, "started_at": stamp, "checked_at": stamp,
                  "passed": False, "returncode": 1, "wrapper_success_marker": False, "private_log": str(log),
                  "log_sha256": digest(log.read_bytes()), "release_version": VERSION,
                  "preflight_proof_sha256": digest(preflight_path.read_bytes()), "private_bindings": self.bindings,
                  "protected_container_count": 17, "migration_plan_selected": False, "resume_plan_selected": False,
                  "usual_idempotent_migrator_invoked_by_guard": True}
        failure_path = self.write("deployment-wrapper-proof.json", failed)
        ci = {"schema_version": 1, "guard_commit": GUARD, "run_id": 12345, "run_attempt": 1,
              "head_sha": GUARD, "run_url": "https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/12345",
              "status": "completed", "conclusion": "success", "jobs": [
                  {"id": index + 1, "run_id": 12345, "run_attempt": 1, "head_sha": GUARD,
                   "name": name, "status": "completed", "conclusion": "success"}
                  for index, name in enumerate(CI_NAMES)]}
        binding = {"application_commit": APP, "guard_commit": GUARD, "application_version": VERSION,
                   "project": "nerkhbaan", "readiness_url": self.env["DEPLOY_READINESS_URL"],
                   "images": state["manifest"]["images"], "baseline_backends": [
                       {"id": row["Id"], "image": row["Image"], "release_version": OLD_VERSION}
                       for row in self.original if guard.service(row) == "backend"],
                   "stopped_backend": {"id": STOPPED, "exit_code": 137, "oom_killed": False},
                   "added_backend": {"id": ADDED, "image": state["manifest"]["images"]["backend"],
                                     "config_hash": existing.NEW_HASH}, "target_migrations": state["desired_migrations"]}
        observation = {"schema_version": 1, "kind": KIND, "source": "actual_target_read_only",
                       "checked_at": stamp, "binding": copy.deepcopy(binding),
                       "baseline_container_fingerprints": fingerprints(self.original),
                       "current_container_fingerprints": fingerprints(state["containers"]),
                       "current_container_roles": roles(state["containers"]),
                       "semantic_checks": {name: True for name in guard.SEMANTIC_CHECKS},
                       "service_hashes": service_hashes, "service_networks": networks,
                       "resolved_config_sha256": model_sha, "probes": [self.probe(row) for row in state["containers"]
                           if guard.service(row) == "backend" and row["State"]["Running"]]}
        files = {"original_preflight": preflight_path, "failed_attempt": attempt_path,
                 "failed_proof": failure_path, "failed_log": log,
                 "image_manifest": self.paths["prepared-images.json"],
                 "operator_evidence": self.paths["operator-gates.json"],
                 "compose_override": self.paths["runtime_override"],
                 "private_environment": self.paths["private_environment"],
                 "guard_ci": self.write("guard-ci.json", ci),
                 "fresh_observation": self.write("fresh-observation.json", observation)}
        self.plan = {"schema_version": 1, "kind": KIND, **binding,
                     "files": {name: self.reference(path) for name, path in files.items()}}
        self.resume_path = self.write("normal-resume-plan.json", self.plan)
        self.env["DEPLOY_NORMAL_RESUME_PLAN"] = str(self.resume_path)
        self.trace.clear()
        self.http_calls.clear()
        state["commands"] = []
        self.save(state)

    def mutate_evidence(self, key, mutate):
        path = Path(self.plan["files"][key]["path"])
        value = json.loads(path.read_text())
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")
        self.plan["files"][key] = self.reference(path)
        self.resume_path.write_text(json.dumps(self.plan), encoding="utf-8")


class NormalResumeTests(unittest.TestCase):
    def mutations(self, fixture):
        return [row["args"] for row in fixture.trace if row["args"][:2] in (
            ["docker", "stop"], ["docker", "rm"]) or "up" in row["args"] or
            ("run" in row["args"] and row["args"][-1] == "migrate")]

    def prepare(self, fixture):
        fixture.seed_original_retirement_failure()

    def assert_protected(self, fixture):
        current = fingerprints(fixture.read()["containers"])
        protected = [row for row in fixture.original if not (
            guard.project(row) == "nerkhbaan" and guard.service(row) in {
                "backend", "frontend", "admin-frontend", "price-feed-pull"})]
        self.assertEqual(len(protected), 17)
        for row in protected:
            self.assertEqual(current[row["Id"]], guard.fingerprint(row))

    def test_https_failure_after_first_stop_retains_exact_survivors_before_remove(self):
        with OwnedGuardFixture() as fixture:
            fixture.fail_after_first_stop()
            rows = {row["Id"]: row for row in fixture.read()["containers"]}
            self.assertEqual(len(rows), 23)
            self.assertFalse(rows[STOPPED]["State"]["Running"])
            self.assertEqual(rows[STOPPED]["State"]["ExitCode"], 137)
            self.assertTrue(rows[SURVIVOR]["State"]["Running"])
            self.assertTrue(rows[ADDED]["State"]["Running"])
            self.assertFalse(any(call[:2] == ["docker", "rm"] for call in self.mutations(fixture)))
            self.assertFalse(any(call[-3:] == ["frontend", "admin-frontend", "price-feed-pull"] for call in self.mutations(fixture)))
            self.assert_protected(fixture)

    def test_explicit_same_ledger_resume_removes_only_recorded_stop_then_keeps_overlap(self):
        with OwnedGuardFixture() as fixture:
            fixture.prepare_resume(fixture.fail_after_first_stop())
            original_failures = {key: Path(fixture.plan["files"][key]["path"]).read_bytes()
                                 for key in ("failed_attempt", "failed_proof", "failed_log")}
            result, output = fixture.run()
            self.assertEqual(result, 0, output)
            mutations = self.mutations(fixture)
            self.assertEqual(mutations[0], ["docker", "rm", STOPPED])
            self.assertEqual([call[-1] for call in mutations if call[:2] == ["docker", "stop"]], [SURVIVOR])
            self.assertEqual([call[-1] for call in mutations if call[:2] == ["docker", "rm"]], [STOPPED, SURVIVOR])
            self.assertFalse(any(call[-1] == "migrate" for call in mutations))
            topology = [(row["args"], row["count"], len(row["running_backends"]))
                        for row in fixture.trace if row["args"] in mutations]
            self.assertEqual(topology[0][1:], (22, 2))
            scaled = [row for row in topology if "--scale" in row[0]]
            self.assertEqual(len(scaled), 1)
            self.assertEqual(scaled[0][1:], (23, 3))
            self.assertEqual(len(fixture.read()["containers"]), 22)
            for row in fixture.read()["containers"]:
                if guard.service(row) == "backend":
                    self.assertEqual(row["Image"], fixture.read()["manifest"]["images"]["backend"])
                    self.assertTrue(guard.healthy(row, require_probe=True))
            for key, original in original_failures.items():
                self.assertEqual(Path(fixture.plan["files"][key]["path"]).read_bytes(), original)
            self.assertNotIn("PRIVATE=owned-fixture-only", output)
            self.assert_protected(fixture)

    def test_stopped_old_state_without_explicit_new_plan_never_restarts_or_removes(self):
        with OwnedGuardFixture() as fixture:
            self.prepare(fixture)
            fixture.env.pop("DEPLOY_NORMAL_RESUME_PLAN")
            result, _ = fixture.run()
            self.assertNotEqual(result, 0)
            self.assertEqual(self.mutations(fixture), [])

    def test_exact_guard_source_and_private_inputs_are_rechecked_before_mutation(self):
        for fault in ("guard_dirty", "guard_api_changed", "dirty", "private_environment", "file_hash"):
            with self.subTest(fault=fault), OwnedGuardFixture() as fixture:
                self.prepare(fixture)
                if fault == "private_environment":
                    with fixture.paths["private_environment"].open("a") as stream:
                        stream.write("CHANGED=owned-only\n")
                elif fault == "file_hash":
                    fixture.plan["files"]["failed_log"]["sha256"] = "0" * 64
                    fixture.resume_path.write_text(json.dumps(fixture.plan))
                else:
                    state = fixture.read()
                    state[fault] = True
                    fixture.save(state)
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertEqual(self.mutations(fixture), [])
                self.assert_protected(fixture)

    def test_ci_requires_exact_job_names_ids_run_attempt_and_guard_sha(self):
        faults = {
            "wrong_name": lambda value: value["jobs"][0].update(name="unreviewed-job"),
            "duplicate_id": lambda value: value["jobs"][1].update(id=value["jobs"][0]["id"]),
            "wrong_head": lambda value: value["jobs"][0].update(head_sha=APP),
            "wrong_run": lambda value: value["jobs"][0].update(run_id=12346),
            "wrong_attempt": lambda value: value["jobs"][0].update(run_attempt=2),
            "boolean_id": lambda value: value["jobs"][0].update(id=True),
            "missing_job": lambda value: value["jobs"].pop(),
            "skipped_job": lambda value: value["jobs"][0].update(conclusion="skipped"),
        }
        for name, mutate in faults.items():
            with self.subTest(fault=name), OwnedGuardFixture() as fixture:
                self.prepare(fixture)
                fixture.mutate_evidence("guard_ci", mutate)
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertEqual(self.mutations(fixture), [])

    def test_fresh_observation_rejects_role_semantic_model_and_clock_tampering(self):
        faults = {
            "role": lambda value: value["current_container_roles"][ADDED].update(service="frontend"),
            "false_semantic": lambda value: value["semantic_checks"].update(environment=False),
            "numeric_semantic": lambda value: value["semantic_checks"].update(environment=1),
            "service_hash": lambda value: value["service_hashes"].update(backend="f" * 64),
            "network": lambda value: value["service_networks"]["backend"].update({"nerkhbaan-network": "other-network"}),
            "model": lambda value: value.update(resolved_config_sha256="f" * 64),
            "stale": lambda value: value.update(checked_at=(datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()),
            "future": lambda value: value.update(checked_at=(datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()),
            "schema_bool": lambda value: value.update(schema_version=True),
            "wrong_ledger": lambda value: value["probes"][0]["applied"].update({existing.REFERENCE_MIGRATION: "0" * 64}),
            "stopped_probe": lambda value: value["probes"].append({"id": STOPPED}),
        }
        for name, mutate in faults.items():
            with self.subTest(fault=name), OwnedGuardFixture() as fixture:
                self.prepare(fixture)
                fixture.mutate_evidence("fresh_observation", mutate)
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertEqual(self.mutations(fixture), [])

    def test_stopped_normalization_allows_only_exact_running_flag_transition(self):
        faults = {
            "running": lambda row: row["State"].update(Running=True),
            "numeric_false": lambda row: row["State"].update(Running=0),
            "exit_code": lambda row: row["State"].update(ExitCode=1),
            "oom": lambda row: row["State"].update(OOMKilled=True),
            "restart": lambda row: row["State"].update(StartedAt="2026-10-18T13:59:00Z"),
            "mount": lambda row: row["Mounts"][0].update(Source="/other-owned-data"),
            "network": lambda row: row["NetworkSettings"]["Networks"]["nerkhbaan-network"].update(NetworkID="other"),
            "config": lambda row: row["Config"]["Labels"].update({"extra": "changed"}),
        }
        for name, mutate in faults.items():
            with self.subTest(fault=name), OwnedGuardFixture() as fixture:
                self.prepare(fixture)
                state = fixture.read()
                stopped = next(row for row in state["containers"] if row["Id"] == STOPPED)
                mutate(stopped)
                fixture.save(state)
                current = fingerprints(state["containers"])
                fixture.mutate_evidence("fresh_observation", lambda value: value.update(current_container_fingerprints=current))
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertEqual(self.mutations(fixture), [])

    def test_late_recorded_candidate_drift_stops_before_second_scale_or_old_stop(self):
        with OwnedGuardFixture() as fixture:
            self.prepare(fixture)
            fixture.faults["late_candidate_drift"] = True
            result, output = fixture.run()
            self.assertNotEqual(result, 0, output)
            self.assertEqual(self.mutations(fixture), [["docker", "rm", STOPPED]])
            self.assertTrue(next(row for row in fixture.read()["containers"] if row["Id"] == SURVIVOR)["State"]["Running"])
            self.assert_protected(fixture)

    def test_second_new_replica_failure_keeps_recorded_candidate_and_last_old(self):
        with OwnedGuardFixture() as fixture:
            self.prepare(fixture)
            state = fixture.read()
            state["fail_scale"] = 2
            fixture.save(state)
            result, output = fixture.run()
            self.assertNotEqual(result, 0, output)
            mutations = self.mutations(fixture)
            self.assertEqual([call[-1] for call in mutations if call[:2] == ["docker", "rm"]], [STOPPED])
            self.assertFalse(any(call[:2] == ["docker", "stop"] for call in mutations))
            rows = {row["Id"]: row for row in fixture.read()["containers"]}
            self.assertTrue(guard.healthy(rows[ADDED], require_probe=True))
            self.assertTrue(guard.healthy(rows[SURVIVOR], require_probe=True))
            self.assert_protected(fixture)

    def test_retirement_retries_only_transient_ingress_failure_after_direct_health(self):
        for event in ("timeout", "reset", 502, 504):
            with self.subTest(event=event), OwnedGuardFixture() as fixture:
                fixture.http_events = [None] * 5 + [event]
                result, output = fixture.run()
                self.assertEqual(result, 0, output)
                mutations = self.mutations(fixture)
                self.assertEqual([call[-1] for call in mutations if call[:2] == ["docker", "rm"]], [STOPPED, SURVIVOR])
                self.assertEqual([call[-1] for call in mutations if call[:2] == ["docker", "stop"]], [STOPPED, SURVIVOR])
                self.assert_protected(fixture)

    def test_retirement_certificate_redirect_or_invalid_payload_fails_without_remove(self):
        for event in ("tls", "unknown_reset", "redirect", "bad_payload", "bad_json", 503):
            with self.subTest(event=event), OwnedGuardFixture() as fixture:
                fixture.http_events = [None] * 5 + [event]
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertEqual(len(fixture.http_calls), 6)
                self.assertFalse(any(call[:2] == ["docker", "rm"] for call in self.mutations(fixture)))
                self.assert_protected(fixture)

    def test_retirement_deadline_rejects_persistent_failure_and_late_success(self):
        for event in ("persistent", "late"):
            with self.subTest(event=event), OwnedGuardFixture() as fixture:
                if event == "persistent":
                    fixture.faults["https_failure_from"] = 6
                else:
                    fixture.http_events = [None] * 5 + ["timeout", "late"]
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertFalse(any(call[:2] == ["docker", "rm"] for call in self.mutations(fixture)))
                if event == "persistent":
                    self.assertLessEqual(fixture.clock.now - 1000, 40)
                    self.assertTrue(all(0 < timeout <= 5 for _, timeout in fixture.http_calls[5:]))
                self.assert_protected(fixture)

    def test_preflight_ingress_failure_never_uses_retirement_retry(self):
        with OwnedGuardFixture() as fixture:
            fixture.http_events = ["timeout"]
            result, output = fixture.run()
            self.assertNotEqual(result, 0, output)
            self.assertEqual(len(fixture.http_calls), 1)
            self.assertEqual(self.mutations(fixture), [])

    def test_retirement_child_verification_cannot_outlive_shared_deadline(self):
        with OwnedGuardFixture() as fixture:
            fixture.http_events = [None] * 5 + ["timeout"]
            fixture.faults["slow_retirement_check"] = True
            result, output = fixture.run()
            self.assertNotEqual(result, 0, output)
            self.assertEqual(len(fixture.child_timeouts), 1)
            self.assertLessEqual(fixture.child_timeouts[0], 29)
            self.assertLessEqual(fixture.clock.now - 1000, 36)
            self.assertFalse(any(call[:2] == ["docker", "rm"] for call in self.mutations(fixture)))
            self.assert_protected(fixture)

    def test_image_checks_batch_four_canonical_tags_without_losing_migrator_binding(self):
        with OwnedGuardFixture() as fixture:
            self.prepare(fixture)
            result, output = fixture.run()
            self.assertEqual(result, 0, output)
            calls = [row["args"][3:] for row in fixture.trace
                     if row["args"][:3] == ["docker", "image", "inspect"] and len(row["args"]) > 4]
            state = fixture.read()
            expected = [state["config"]["services"][name]["image"]
                        for name in ("backend", "frontend", "admin-frontend", "price-feed-pull")]
            self.assertTrue(calls)
            self.assertTrue(all(call == expected for call in calls))
            self.assertEqual(state["config"]["services"]["backend"]["image"],
                             state["config"]["services"]["migrate"]["image"])
            self.assert_protected(fixture)

    def test_missing_reordered_or_changed_batched_image_row_stops_before_removal(self):
        for fault in ("missing", "reordered", "wrong_id"):
            with self.subTest(fault=fault), OwnedGuardFixture() as fixture:
                self.prepare(fixture)
                fixture.faults["batch_response"] = fault
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertEqual(self.mutations(fixture), [])
                self.assert_protected(fixture)

    def test_two_normal_api_probes_overlap_without_fake_state_or_history_races(self):
        with OwnedGuardFixture() as fixture:
            self.prepare(fixture)
            fixture.probe_gate = threading.Barrier(2)
            result, output = fixture.run()
            self.assertEqual(result, 0, output)
            self.assertEqual(fixture.maximum_active_probes, 2)
            self.assertEqual(fixture.active_probes, 0)
            self.assertEqual({identifier for identifier, _thread in fixture.probe_threads[:2]}, {SURVIVOR, ADDED})
            self.assertEqual(len({thread for _identifier, thread in fixture.probe_threads[:2]}), 2)
            trace_count = sum(row["args"][:2] == ["docker", "exec"] and "urlopen" in row["args"][-1]
                              for row in fixture.trace)
            state_count = sum(call[:2] == ["docker", "exec"] and "urlopen" in call[-1]
                              for call in fixture.read()["commands"])
            self.assertEqual(trace_count, state_count)
            self.assertEqual(trace_count, len(fixture.probe_threads))
            self.assert_protected(fixture)

    def test_failure_of_either_concurrent_normal_probe_never_removes_any_api(self):
        for identifier in (SURVIVOR, ADDED):
            with self.subTest(identifier=identifier), OwnedGuardFixture() as fixture:
                self.prepare(fixture)
                fixture.probe_gate = threading.Barrier(2)
                fixture.faults["failed_probe"] = identifier
                result, output = fixture.run()
                self.assertNotEqual(result, 0, output)
                self.assertEqual(self.mutations(fixture), [])
                self.assertEqual(fixture.active_probes, 0)
                self.assertEqual(fixture.maximum_active_probes, 2)
                self.assert_protected(fixture)

    def test_late_parallel_api_probe_cannot_authorize_stopped_old_removal(self):
        with OwnedGuardFixture() as fixture:
            self.prepare(fixture)
            fixture.faults["late_probe"] = ADDED
            result, output = fixture.run()
            self.assertNotEqual(result, 0, output)
            self.assertEqual(self.mutations(fixture), [])
            self.assertEqual(fixture.active_probes, 0)
            self.assertNotIn("PRIVATE=owned-fixture-only", output)
            self.assert_protected(fixture)

    def test_old_additive_migration_pair_stays_serial_with_exact_legacy_validation(self):
        with OwnedGuardFixture() as fixture:
            self.prepare(fixture)
            env = dict(fixture.env)
            env.pop("DEPLOY_NORMAL_RESUME_PLAN")
            deploy = guard.ApplicationDeploy(env)
            state = fixture.read()
            current = {row["Id"]: row for row in state["containers"]}
            deploy.config = state["config"]
            deploy.commit = APP
            deploy.images = {name: (state["config"]["services"][name]["image"], value)
                             for name, value in state["manifest"]["images"].items()}
            deploy.backend_hash = existing.NEW_HASH
            deploy.service_networks = {"backend": {"nerkhbaan-network": "stable-network"}}
            deploy.baseline_backends = {identifier: current[identifier] for identifier in (STOPPED, SURVIVOR)}
            target = state["desired_migrations"]
            baseline = {name: value for name, value in target.items() if name != existing.REFERENCE_MIGRATION}
            deploy.plan = {"baseline_migrations": baseline, "target_migrations": target,
                           "baseline_backends": [{"release_version": "2.8.1"}]}
            deploy.migrated = True
            original_probe = fixture.probe

            def legacy_probe(row):
                result = original_probe(row)
                old = row["Id"] == SURVIVOR
                result["payload"] = existing.ready_payload(old=old)
                result["status"] = 503 if old else 200
                result["expected"] = baseline if old else target
                if old:
                    result["migration_state"] = deploy.old_migration_state()
                return result

            with patch.object(fixture, "probe", side_effect=legacy_probe), patch.object(
                guard, "command", fixture.command
            ), patch.object(guard, "ThreadPoolExecutor", side_effect=AssertionError("Legacy pair must stay serial")):
                deploy.check_retirement_pair()
            self.assertEqual(fixture.maximum_active_probes, 1)
            self.assertEqual(fixture.active_probes, 0)
            self.assertEqual(self.mutations(fixture), [])


if __name__ == "__main__":
    unittest.main()
