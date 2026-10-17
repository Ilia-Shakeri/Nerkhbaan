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

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
NEW_HASH = "b" * 64
OLD_HASH = "c" * 64


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


def fake_cli(kind: str, args: list[str]) -> int:
    path = Path(os.environ["FAKE_DEPLOY_STATE"])
    state = json.loads(path.read_text())
    state["commands"].append([kind, *args])
    code, output = 0, ""
    if kind == "git":
        if args[0] == "status":
            output = " M tracked.txt" if state.get("dirty") else ""
        elif args == ["rev-parse", "HEAD"]:
            output = state["commit"]
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
        image = state["images"].get(args[2])
        if image is None:
            code = 1
        else:
            output = json.dumps([{"Id": image}])
    elif args[0] == "run":
        assert "--read-only" in args and "--network" in args and args[args.index("--network") + 1] == "none"
        assert "--rm" in args and "--pull" in args and args[args.index("--pull") + 1] == "never"
        output = json.dumps(state["desired_migrations"])
    elif args[0] == "exec":
        output = json.dumps({"expected": state["current_migrations"], "applied": state["applied_migrations"]})
    elif args[0] in {"stop", "rm"}:
        container_id = args[-1]
        item = next(item for item in state["containers"] if item["Id"] == container_id)
        if args[0] == "stop":
            item["State"]["Running"] = False
            for details in item["NetworkSettings"]["Networks"].values():
                details["EndpointID"] = ""
                details["IPAddress"] = ""
        else:
            state["containers"].remove(item)
    elif args[0] == "compose":
        index = next(index for index, value in enumerate(args) if value in {"config", "ps", "run", "up"})
        command = args[index:]
        if command[0] == "config" and "--format" in command:
            output = json.dumps(state["config"])
        elif command[:2] == ["config", "--hash"]:
            output = f"{command[-1]} {NEW_HASH}"
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
            if state.get("wrong_new_network"):
                new["NetworkSettings"]["Networks"]["nerkhbaan-network"]["NetworkID"] = "other-network"
            if state.get("old_identity_drift"):
                old = next(item for item in state["containers"] if item["Id"] == "nerkhbaan-backend-1")
                old["Mounts"][0]["Source"] = "/changed"
            if state.get("protected_drift"):
                data = next(item for item in state["containers"] if item["Id"] == "nerkhbaan-redis-1")
                data["Mounts"][0]["Source"] = "/changed"
            if state.get("tag_drift"):
                state["images"][image_ref] = "sha256:changed-tag"
            if state.get("config_drift"):
                state["config"]["services"]["frontend"]["environment"] = {"CHANGED": "true"}
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
            state_path.write_text(json.dumps(initial))
            override.write_text("{}")
            manifest.write_text(json.dumps(initial["manifest"]))
            # The validator stays real; only its owned fixture inputs are used.
            from test_verify_operator_gates import evidence as valid_evidence
            evidence.write_text(json.dumps(valid_evidence()))
            launcher = root / "launcher.py"
            launcher.write_text('''import json, os, runpy, sys
from pathlib import Path
import urllib.request
os.environ['PATH'] = os.environ['FAKE_DEPLOY_BIN'] + os.pathsep + os.environ['PATH']
class Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return b'{"ready": true}'
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
                       PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            env.pop("BACKEND_REPLICAS", None)
            if omit:
                env.pop(omit, None)
            if missing_python:
                (bin_dir / "python").unlink()
                (bin_dir / "python3").unlink()
                env["PATH"] = str(bin_dir)
            result = subprocess.run([str(self.bash), str(scripts / "deploy-nerkhbaan-prod.sh")],
                                    env=env, capture_output=True, text=True, timeout=90)
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

    def test_rollout_only_updates_application_with_healthy_overlap(self):
        result, final, initial = self.run_deploy()
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
