"""Update a reviewed application release while retaining the existing stack."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener


REFERENCE_MIGRATION = "20261017_001_iranian_reference_records.sql"
REFERENCE_CHECKSUM = "05ba325399df2b031459b6484d5cc02b4071f12dd708cdad7e65e5a8cd1e642b"
BASELINE_MIGRATIONS = {
    "20260705_timescale_market_prices.sql", "20260718_001_core_pricing.sql",
    "20260718_002_auth_admin_alerts.sql", "20260718_003_timescale_policies.sql",
    "20260802_001_alert_price_source_mode.sql", "20260809_001_pricing_provider_repair.sql",
    "20261011_001_delivery_hardening.sql", "20261011_002_notification_sending_state.sql",
}
PLAN_KIND = "iranian-reference-addition-v1"
MIGRATION_COMMAND = ["python", "-m", "app.migrations.runner"]


def private_bytes(path: Path) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise DeployStopped("Migration evidence must be an existing absolute private regular file")
    info = path.stat()
    if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise DeployStopped("Migration evidence must be owned by the deploy user with private permissions")
    return path.read_bytes()


class DeployStopped(RuntimeError):
    pass


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def command(args: list[str], *, cwd: Path, timeout: int = 300) -> str:
    executable = shutil.which(args[0]) or args[0]
    try:
        result = subprocess.run(
            [executable, *args[1:]], cwd=cwd, capture_output=True,
            text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeployStopped(f"Command unavailable or timed out: {Path(args[0]).name}") from exc
    if result.returncode:
        # Config and migration output can contain private environment values.
        raise DeployStopped(f"Command failed: {Path(args[0]).name}; inspect private service logs")
    return result.stdout.strip()


def required_file(env: dict[str, str], name: str) -> Path:
    value = env.get(name, "")
    path = Path(value)
    if not value or not path.is_absolute() or not path.is_file():
        raise DeployStopped(f"{name} must name an existing absolute private file")
    return path.resolve()


def immutable_image(image: str) -> bool:
    if re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", image):
        return True
    tag = image.rsplit("/", 1)[-1].rsplit(":", 1)
    return len(tag) == 2 and bool(re.fullmatch(r"(?:\d+\.\d+\.\d+-)?[a-f0-9]{7,40}", tag[1]))


def network_identity(container: dict) -> dict:
    return {
        name: details.get("NetworkID")
        for name, details in container.get("NetworkSettings", {}).get("Networks", {}).items()
    }


def identity(container: dict) -> dict:
    mounts = container.get("Mounts")
    if isinstance(mounts, list):
        mounts = sorted(mounts, key=lambda mount: (
            mount.get("Destination", ""), mount.get("Type", ""), mount.get("Source", ""),
        ))
    return {
        key: container.get(key)
        for key in ("Id", "Image", "Config", "HostConfig", "Created")
    } | {
        "Mounts": mounts,
        "StartedAt": container["State"].get("StartedAt"),
        "Networks": network_identity(container),
    }


def service(container: dict) -> str:
    return container.get("Config", {}).get("Labels", {}).get("com.docker.compose.service", "")


def project(container: dict) -> str:
    return container.get("Config", {}).get("Labels", {}).get("com.docker.compose.project", "")


def healthy(container: dict, *, require_probe: bool = False) -> bool:
    state = container.get("State", {})
    health = state.get("Health")
    return bool(state.get("Running")) and (
        isinstance(health, dict) and health.get("Status") == "healthy"
        if require_probe or health is not None else True
    )


class ApplicationDeploy:
    def __init__(self, env: dict[str, str]):
        value = env.get("RELEASE_DIR", "")
        self.root = Path(value)
        if not value or not self.root.is_absolute() or not self.root.is_dir():
            raise DeployStopped("RELEASE_DIR must name the reviewed absolute checkout")
        self.root = self.root.resolve()
        self.project_name = env.get("COMPOSE_PROJECT_NAME", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", self.project_name):
            raise DeployStopped("COMPOSE_PROJECT_NAME must explicitly name the existing stack")
        env_file = required_file(env, "COMPOSE_ENV_FILE")
        self.env_file = env_file
        override = required_file(env, "COMPOSE_OVERRIDE_FILE")
        self.evidence = required_file(env, "OPERATOR_EVIDENCE_PATH")
        self.manifest = required_file(env, "DEPLOY_IMAGE_MANIFEST")
        self.compose = [
            "docker", "compose", "-p", self.project_name, "--env-file", str(env_file),
            "-f", str(self.root / "docker-compose.prod.yaml"), "-f", str(override),
            "--profile", "admin",
        ]
        try:
            self.replicas = int(env.get("BACKEND_REPLICAS", "2"))
            self.wait = int(env.get("DEPLOY_WAIT_SECONDS", "240"))
        except ValueError as exc:
            raise DeployStopped("Replica count and wait must be integers") from exc
        if not 2 <= self.replicas <= 8 or not 1 <= self.wait <= 600:
            raise DeployStopped("Require 2-8 backend replicas and a 1-600 second health wait")
        self.readiness_url = env.get("DEPLOY_READINESS_URL", "")
        if not re.fullmatch(r"https://[^\s/?#@]+/api/health/ready", self.readiness_url):
            raise DeployStopped("DEPLOY_READINESS_URL must name the target HTTPS readiness route")
        self.protected: dict[str, dict] = {}
        self.images: dict[str, tuple[str, str]] = {}
        self.targets: list[str] = []
        self.plan_path = Path(env["DEPLOY_MIGRATION_PLAN"]) if env.get("DEPLOY_MIGRATION_PLAN") else None
        self.plan: dict | None = None
        self.plan_files: dict[Path, str] = {}
        self.migrated = False
        self.baseline_backends: dict[str, dict] = {}
        self.startup_deadline: float | None = None

    def bounded_timeout(self, timeout: float) -> float:
        if self.startup_deadline is not None:
            remaining = self.startup_deadline - time.monotonic()
            if remaining <= 0:
                raise DeployStopped("New backend readiness timed out; keep remaining replicas")
            timeout = min(timeout, remaining)
        return timeout

    def run(self, args: list[str], *, timeout: int = 300) -> str:
        return command(args, cwd=self.root, timeout=self.bounded_timeout(timeout))

    def compose_run(self, *args: str) -> str:
        return self.run([*self.compose, *args], timeout=self.wait + 60)

    def inspect(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        return json.loads(self.run(["docker", "inspect", *ids]))

    def containers(self) -> list[dict]:
        return self.inspect(self.run(["docker", "ps", "-aq", "--no-trunc"]).split())

    def backends(self) -> list[dict]:
        ids = self.compose_run("ps", "--all", "-q", "backend").split()
        containers = self.inspect(ids)
        if any(project(item) != self.project_name or service(item) != "backend" for item in containers):
            raise DeployStopped("Backend identity differs from the selected stack")
        return containers

    def check_images(self) -> None:
        self.check_plan_files()
        for image, expected in self.images.values():
            actual = json.loads(self.run(["docker", "image", "inspect", image]))
            if len(actual) != 1 or actual[0].get("Id") != expected:
                raise DeployStopped("Reviewed image identity changed; stop and review")
        if json.loads(self.compose_run("config", "--format", "json")) != self.config:
            raise DeployStopped("Reviewed Compose configuration changed; stop and review")
        self.check_env_binding()
        if self.run(["git", "rev-parse", "HEAD"]) != self.commit or self.run(
            ["git", "status", "--porcelain", "--untracked-files=no"]
        ):
            raise DeployStopped("Reviewed checkout changed; stop and review")

    def check_env_binding(self) -> None:
        config = json.loads(self.compose_run("config", "--no-env-resolution", "--format", "json"))
        for name in ("backend", "migrate"):
            paths = config.get("services", {}).get(name, {}).get("env_file", [])
            selected = {
                Path(item["path"] if isinstance(item, dict) else item).resolve() for item in paths
            }
            if selected != {self.env_file}:
                raise DeployStopped(f"{name} env_file differs from the selected private environment")

    def check_protected(self) -> None:
        current = {item["Id"]: item for item in self.containers()}
        for container_id, baseline in self.protected.items():
            item = current.get(container_id)
            if item is None or identity(item) != identity(baseline):
                raise DeployStopped("Protected container identity/configuration changed; stop and review")
            if item["State"].get("Running") != baseline["State"].get("Running"):
                raise DeployStopped("Protected container running state changed; stop and review")
            if project(item) == self.project_name and service(item) in {"postgres", "redis", "db-backup"}:
                if not healthy(item, require_probe=True):
                    raise DeployStopped("Existing data or backup service is unhealthy")
        allowed = set(self.targets) | {"backend", "migrate"}
        for container_id, item in current.items():
            if container_id not in self.protected and not (
                project(item) == self.project_name and service(item) in allowed
            ):
                raise DeployStopped("Unexpected protected container appeared; stop and review")

    def readiness(self, *, allow_old: bool = False) -> None:
        try:
            try:
                response = build_opener(RejectRedirect()).open(
                    self.readiness_url, timeout=self.bounded_timeout(15),
                )
            except HTTPError as exc:
                if exc.code != 503:
                    raise
                response = exc
            with response:
                if response.geturl() != self.readiness_url:
                    raise DeployStopped("Target HTTPS readiness failed")
                payload = json.loads(response.read(65536))
                status = response.status
            self.bounded_timeout(15)
            if allow_old and status == 503 and self.plan and self.migrated:
                self.validate_payload(payload, old=True, status=status)
                return
            if status != 200 or not isinstance(payload, dict) or payload.get("ready") is not True:
                raise DeployStopped("Target HTTPS readiness payload failed")
            if self.plan:
                self.validate_payload(payload, old=not self.migrated, status=status)
        except (OSError, ValueError) as exc:
            raise DeployStopped("Target HTTPS readiness failed") from exc

    def backend_health(self, count: int, new_count: int) -> list[dict]:
        current = self.backends()
        if len(current) != count or any(not self.backend_healthy(item) for item in current):
            raise DeployStopped("Backend replica count or health failed; keep remaining replicas")
        if any(network_identity(item) != self.service_networks["backend"] for item in current):
            raise DeployStopped("Backend network identity failed; keep remaining replicas")
        if sum(self.desired_backend(item) for item in current) < new_count:
            raise DeployStopped("Reviewed backend image health failed; keep remaining replicas")
        self.check_protected()
        self.readiness(allow_old=any(item["Id"] in self.baseline_backends for item in current))
        return current

    def backend_healthy(self, item: dict) -> bool:
        if not self.plan:
            return healthy(item, require_probe=True)
        old = item["Id"] in self.baseline_backends
        if old:
            self.guard_old(self.baseline_backends[item["Id"]], running=True)
            if not self.migrated and not healthy(item, require_probe=True):
                return False
        elif not self.desired_backend(item) or not healthy(item, require_probe=True):
            return False
        probe = self.backend_probe(item)
        self.validate_payload(probe.get("payload"), old=old, status=probe.get("status"))
        expected = self.plan["baseline_migrations"] if old else self.plan["target_migrations"]
        applied = self.plan["target_migrations"] if self.migrated else self.plan["baseline_migrations"]
        if probe.get("expected") != expected or probe.get("applied") != applied:
            raise DeployStopped("Backend migration files or exact ledger changed")
        if old and self.migrated and probe.get("migration_state") != self.old_migration_state():
            raise DeployStopped("Old backend has a migration failure beyond the reviewed addition")
        if not old and probe.get("migration_state", {}).get("current") is not True:
            raise DeployStopped("New backend migration readiness failed")
        return True

    def backend_probe(self, item: dict) -> dict:
        return json.loads(self.run([
            "docker", "exec", item["Id"], "python", "-c",
            "from urllib.request import urlopen\nimport json\nfrom urllib.error import HTTPError\n"
            "from app.db import engine\nfrom app.migrations.state import expected_migrations, migration_state\n"
            "from sqlalchemy import text\n"
            "try:\n response = urlopen('http://127.0.0.1:8000/api/health/ready', timeout=10)\n"
            "except HTTPError as error:\n response = error\n"
            "with response:\n status = response.status\n payload = json.load(response)\n"
            "with engine.connect() as connection:\n connection.execute(text('SET TRANSACTION READ ONLY'))\n"
            " rows = connection.execute(text('SELECT version, checksum FROM public.schema_migrations ORDER BY version')).mappings().all()\n"
            "print(json.dumps({'status': status, 'payload': payload, 'expected': expected_migrations(), "
            "'applied': {row['version']: row['checksum'] for row in rows}, 'migration_state': migration_state(engine)}))",
        ], timeout=30))

    def validate_payload(self, payload: dict, *, old: bool, status: int) -> None:
        old_after = old and self.migrated
        release = self.plan["baseline_backends"][0]["release_version"] if old else "2.8.8"
        expected = {
            "ready": not old_after, "status": "degraded" if old_after else "ok",
            "database": "connected", "redis": "connected", "migration_current": not old_after,
            "migration_version": REFERENCE_MIGRATION if self.migrated else max(self.plan["baseline_migrations"]),
            "release_version": release,
        }
        if status != (503 if old_after else 200) or not isinstance(payload, dict) or any(
            payload.get(key) != value or isinstance(value, bool) and type(payload.get(key)) is not bool
            for key, value in expected.items()
        ):
            raise DeployStopped("Strict readiness or reviewed old migration-only state failed")

    def old_migration_state(self) -> dict:
        return {"current": False, "version": REFERENCE_MIGRATION, "applied_count": 9,
                "expected_count": 8, "missing": [], "changed": [], "unknown": [REFERENCE_MIGRATION]}

    def check_plan_files(self) -> None:
        for path, checksum in self.plan_files.items():
            if hashlib.sha256(private_bytes(path)).hexdigest() != checksum:
                raise DeployStopped("Reviewed migration plan or restore evidence changed")
        if self.plan:
            self.check_proof_time(self.proof["checked_at"])

    @staticmethod
    def check_proof_time(value: str) -> None:
        try:
            checked = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if checked.tzinfo is None or checked.utcoffset().total_seconds() != 0:
                raise ValueError("UTC required")
            age = (datetime.now(timezone.utc) - checked).total_seconds()
            if not -300 <= age <= 86400:
                raise ValueError("stale or future")
        except (AttributeError, TypeError, ValueError) as exc:
            raise DeployStopped("Migration restore evidence must have a fresh UTC timestamp") from exc

    def read_bound_file(self, reference: dict) -> bytes:
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"} or not re.fullmatch(
            r"[a-f0-9]{64}", reference.get("sha256", "")
        ):
            raise DeployStopped("Migration proof needs an exact file/hash reference")
        path = Path(reference["path"])
        data = private_bytes(path)
        if not data or hashlib.sha256(data).hexdigest() != reference["sha256"]:
            raise DeployStopped("Migration evidence file/hash differs from the reviewed proof")
        self.plan_files[path] = reference["sha256"]
        return data

    def load_migration_plan(self, expected: dict, current: dict) -> None:
        if self.plan_path is None:
            raise DeployStopped("Schema differs across release/image/current ledger; use a reviewed migration plan")
        migration_spec = self.config["services"]["migrate"]
        if migration_spec.get("command") != MIGRATION_COMMAND or migration_spec.get("entrypoint") not in (None, []):
            raise DeployStopped("Reviewed additive migration requires the exact packaged migration runner")
        raw = private_bytes(self.plan_path)
        plan = json.loads(raw)
        keys = {"schema_version", "kind", "commit", "project", "readiness_url", "images",
                "baseline_backends", "baseline_migrations", "target_migrations", "evidence"}
        if not isinstance(plan, dict) or set(plan) != keys or type(plan["schema_version"]) is not int or (
            plan["schema_version"] != 1 or plan["kind"] != PLAN_KIND
        ):
            raise DeployStopped("Unsupported reviewed migration plan")
        baseline = plan["baseline_migrations"]
        if not isinstance(baseline, dict) or set(baseline) != BASELINE_MIGRATIONS or len(baseline) != 8:
            raise DeployStopped("Reviewed migration plan must retain the exact eight-migration baseline")
        if expected != baseline | {REFERENCE_MIGRATION: REFERENCE_CHECKSUM} or (
            plan["target_migrations"] != expected or current.get("expected") != baseline or
            current.get("applied") != baseline
        ):
            raise DeployStopped("Only the pinned reference-table addition may extend the unchanged ledger")
        if plan["commit"] != self.commit or plan["project"] != self.project_name or (
            plan["readiness_url"] != self.readiness_url or
            plan["images"] != {name: image_id for name, (_, image_id) in self.images.items()}
        ):
            raise DeployStopped("Reviewed migration plan target differs from the release")
        declared = plan["baseline_backends"]
        actual = [{"id": item["Id"], "image": item["Image"], "release_version": "2.8.1"}
                  for item in self.baseline_backends.values()]
        if not isinstance(declared, list) or sorted(declared, key=lambda item: item["id"]) != sorted(
            actual, key=lambda item: item["id"]
        ) or len({item["image"] for item in actual}) != 1:
            raise DeployStopped("Reviewed migration baseline IDs/images/release differ from the running API")
        self.plan = plan
        self.plan_files[self.plan_path] = hashlib.sha256(raw).hexdigest()
        proof = json.loads(self.read_bound_file(plan["evidence"]))
        self.proof = proof
        binding = {key: plan[key] for key in (
            "commit", "project", "readiness_url", "images", "baseline_backends",
            "baseline_migrations", "target_migrations",
        )}
        if not isinstance(proof, dict) or type(proof.get("schema_version")) is not int or (
            proof.get("schema_version") != 1 or proof.get("kind") != PLAN_KIND or proof.get("release") != binding
        ):
            raise DeployStopped("Restore proof differs from the exact reviewed migration plan")
        self.check_proof_time(proof.get("checked_at"))
        restore = proof.get("restore", {})
        if not isinstance(restore, dict):
            raise DeployStopped("Restore proof must contain an object with observed restore results")
        digest = restore.get("existing_data_sha256_before", "")
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or restore.get("existing_data_sha256_after") != digest or (
            restore.get("isolated") is not True or restore.get("source_database_container_id") != self.database_id or
            restore.get("baseline_migrations") != baseline or restore.get("target_migrations") != expected or
            restore.get("migration_command") != MIGRATION_COMMAND or
            restore.get("migration_image") != self.images["migrate"][1] or
            restore.get("new_table") != "public.pricing_reference_records" or
            type(restore.get("new_table_rows")) is not int or restore["new_table_rows"] != 0
        ):
            raise DeployStopped("Restore proof must run the exact migrator, preserve existing data and verify the empty added table")
        compatibility = proof.get("compatibility", {})
        if not isinstance(compatibility, dict):
            raise DeployStopped("Compatibility proof must contain observed old/new image results")
        if compatibility.get("old_image") != actual[0]["image"] or (
            compatibility.get("new_image") != self.images["backend"][1] or
            compatibility.get("old_release_version") != "2.8.1" or
            compatibility.get("old_migration_state") != self.old_migration_state()
        ):
            raise DeployStopped("Compatibility proof differs from the reviewed old/new images")
        self.migrated = True
        try:
            self.validate_payload(compatibility.get("old_ready_payload"), old=True,
                                  status=compatibility.get("old_ready_status"))
            self.validate_payload(compatibility.get("new_ready_payload"), old=False,
                                  status=compatibility.get("new_ready_status"))
        finally:
            self.migrated = False
        probes = compatibility.get("business_probes", [])
        if (
            not isinstance(probes, list) or len(probes) != 2 or
            any(not isinstance(probe, dict) for probe in probes) or
            {probe.get("path") for probe in probes} != {"/api/prices", "/api/instruments"} or
            any(probe.get("status") != 200 or not re.fullmatch(
                r"[a-f0-9]{64}", probe.get("body_sha256", "")
            ) for probe in probes)
        ):
            raise DeployStopped("Compatibility proof needs both read-only old-image business routes")
        self.read_bound_file(proof.get("transcript"))
        self.check_plan_files()

    def desired_backend(self, item: dict) -> bool:
        return item["Image"] == self.images["backend"][1] and (
            item["Config"]["Labels"].get("com.docker.compose.config-hash") == self.backend_hash
        )

    def guard_old(self, baseline: dict, *, running: bool) -> None:
        current = self.inspect([baseline["Id"]])
        if len(current) != 1 or identity(current[0]) != identity(baseline):
            raise DeployStopped("Recorded backend identity changed; no container removal")
        item = current[0]
        if project(item) != self.project_name or service(item) != "backend":
            raise DeployStopped("Recorded backend labels changed; no container removal")
        if item["State"].get("Running") is not running:
            raise DeployStopped("Recorded backend running state changed; no container removal")

    def preflight(self) -> list[dict]:
        self.run([sys.executable, "scripts/verify_operator_gates.py", str(self.evidence)])
        if self.run(["git", "status", "--porcelain", "--untracked-files=no"]):
            raise DeployStopped("Tracked checkout changes exist")
        self.commit = self.run(["git", "rev-parse", "HEAD"])
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        if not re.fullmatch(r"[a-f0-9]{40}", self.commit) or manifest.get("commit") != self.commit:
            raise DeployStopped("Reviewed image manifest commit differs from the checkout")
        config = json.loads(self.compose_run("config", "--format", "json"))
        self.config = config
        if config.get("name") != self.project_name:
            raise DeployStopped("Resolved Compose project differs from the existing stack")
        self.check_env_binding()
        current = self.containers()
        owned = [item for item in current if project(item) == self.project_name]
        for name in ("postgres", "redis", "db-backup"):
            matches = [item for item in owned if service(item) == name]
            if len(matches) != 1 or not healthy(matches[0], require_probe=True):
                raise DeployStopped(f"Existing {name} must be healthy; initial stack creation is separate")
            if name == "postgres":
                self.database_id = matches[0]["Id"]
        self.targets = [
            name for name in ("frontend", "admin-frontend", "price-feed-pull")
            if any(service(item) == name for item in owned)
        ]
        if "frontend" not in self.targets or "price-feed-pull" not in self.targets:
            raise DeployStopped("Existing frontend and price feed are required")
        for name in self.targets:
            matches = [item for item in owned if service(item) == name]
            if len(matches) != 1 or not healthy(matches[0]):
                raise DeployStopped(f"Existing {name} baseline is ambiguous or unhealthy")
        for name in ("backend", "migrate", *self.targets):
            spec = config.get("services", {}).get(name, {})
            if name in {"backend", "migrate"}:
                rights_setting = spec.get("environment", {}).get("PRICING_RIGHTS_ENFORCED", "true")
                if str(rights_setting).lower() not in {"true", "1", "yes", "on"}:
                    raise DeployStopped("Production source-rights enforcement must remain enabled")
            image = spec.get("image", "")
            if not immutable_image(image):
                raise DeployStopped(f"{name} needs a reviewed commit/digest image reference")
            loaded = json.loads(self.run(["docker", "image", "inspect", image]))
            if len(loaded) != 1 or not re.fullmatch(r"sha256:[a-f0-9]{64}", loaded[0].get("Id", "")):
                raise DeployStopped(f"Reviewed {name} image must already be loaded")
            if manifest.get("images", {}).get(name) != loaded[0]["Id"]:
                raise DeployStopped(f"Reviewed {name} image differs from the manifest")
            if name in {"backend", "frontend", "admin-frontend"} and not spec.get("healthcheck"):
                raise DeployStopped(f"{name} needs a configured health probe")
            self.images[name] = (image, loaded[0]["Id"])
        if self.images["migrate"][1] != self.images["backend"][1]:
            raise DeployStopped("Migration and backend must use the same reviewed image")
        backends = self.backends()
        if len(backends) != self.replicas or any(not healthy(item, require_probe=True) for item in backends):
            raise DeployStopped("Backend baseline must match healthy requested replica count")
        self.baseline_backends = {item["Id"]: item for item in backends}
        self.service_hashes = {}
        for name in ("backend", *self.targets):
            hashed = self.compose_run("config", "--hash", name).split()
            if len(hashed) != 2 or hashed[0] != name or not re.fullmatch(r"[a-f0-9]{64}", hashed[1]):
                raise DeployStopped(f"Cannot resolve reviewed {name} configuration identity")
            self.service_hashes[name] = hashed[1]
        self.backend_hash = self.service_hashes["backend"]
        self.service_networks = {}
        for name in ("backend", *self.targets):
            spec = config["services"][name]
            expected_networks = {
                config["networks"][key]["name"] for key in spec.get("networks", {})
            }
            matches = [item for item in owned if service(item) == name]
            if not expected_networks or any(
                set(item.get("NetworkSettings", {}).get("Networks", {})) != expected_networks
                for item in matches
            ):
                raise DeployStopped(f"{name} network differs from the existing stack")
            self.service_networks[name] = network_identity(matches[0])
            if any(network_identity(item) != self.service_networks[name] for item in matches):
                raise DeployStopped(f"{name} network identity is ambiguous")
        migration_networks = {
            config["networks"][key]["name"] for key in config["services"]["migrate"].get("networks", {})
        }
        if migration_networks != set(self.service_networks["backend"]):
            raise DeployStopped("Migration network differs from the existing backend")
        self.check_schema(backends[0])
        excluded = {"backend", *self.targets}
        self.protected = {
            item["Id"]: item for item in current
            if not (project(item) == self.project_name and service(item) in excluded)
        }
        self.check_protected()
        if self.plan:
            self.backend_health(self.replicas, 0)
        else:
            self.readiness()
        return backends

    def check_schema(self, baseline: dict) -> None:
        # Default deployment retains a fixed ledger. One pinned addition needs restore proof.
        expected = {
            path.name: hashlib.sha256(path.read_text(encoding="utf-8").replace("\r\n", "\n").replace(
                "\r", "\n"
            ).encode("utf-8")).hexdigest()
            for path in sorted((self.root / "apps/api/db/migrations").glob("*.sql"))
        }
        if not expected:
            raise DeployStopped("Reviewed checkout has no migration manifest")
        for name in ("backend", "migrate"):
            path = self.config["services"][name].get("environment", {}).get("MIGRATIONS_DIR", "/app/db/migrations")
            if path != "/app/db/migrations":
                raise DeployStopped("Reviewed migration directory differs from the packaged path")
        desired = json.loads(self.run([
            "docker", "run", "--rm", "--pull", "never", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--label", "nerkhbaan.deploy-probe=migrations", "--entrypoint", "python",
            self.images["backend"][1], "-c",
            "import json; from app.migrations.state import expected_migrations; print(json.dumps(expected_migrations()))",
        ]))
        self.guard_old(baseline, running=True)
        current = json.loads(self.run([
            "docker", "exec", baseline["Id"], "python", "-c",
            "import json\nfrom app.db import engine\nfrom app.migrations.state import expected_migrations\n"
            "from sqlalchemy import text\nwith engine.connect() as connection:\n"
            " connection.execute(text('SET TRANSACTION READ ONLY'))\n"
            " rows = connection.execute(text('SELECT version, checksum FROM public.schema_migrations ORDER BY version')).mappings().all()\n"
            "print(json.dumps({'expected': expected_migrations(), 'applied': {row['version']: row['checksum'] for row in rows}}))",
        ]))
        if desired != expected:
            raise DeployStopped("Reviewed image migrations differ from the checkout")
        if current.get("expected") != desired or current.get("applied") != desired:
            self.load_migration_plan(expected, current)
        elif self.plan_path is not None:
            raise DeployStopped("Migration plan is only valid for the exact reviewed baseline transition")

    def wait_added_backend(self, count: int, new_count: int) -> None:
        self.startup_deadline = time.monotonic() + self.wait
        try:
            self.poll_added_backend(count, new_count)
        finally:
            self.startup_deadline = None

    def poll_added_backend(self, count: int, new_count: int) -> None:
        deadline = self.startup_deadline
        while True:
            current = self.backends()
            new = [item for item in current if item["Id"] not in self.baseline_backends]
            if len(current) > count or any(not self.desired_backend(item) for item in new):
                raise DeployStopped("Unexpected backend appeared during the reviewed transition")
            if len(current) == count and len(new) >= new_count and all(
                healthy(item, require_probe=True) for item in new
            ):
                self.backend_health(count, new_count)
                print("Verified new backend IDs: " + ", ".join(item["Id"] for item in new), flush=True)
                return
            self.check_images()
            self.check_protected()
            for item in current:
                if item["Id"] in self.baseline_backends and not self.backend_healthy(item):
                    raise DeployStopped("Old backend failed during bounded new-image startup")
                if item in new and (not item["State"].get("Running") or
                                   item["State"].get("Health", {}).get("Status") == "unhealthy"):
                    raise DeployStopped("New backend failed readiness; keep remaining replicas")
            if time.monotonic() >= deadline:
                raise DeployStopped("New backend readiness timed out; keep remaining replicas")
            time.sleep(min(2, max(0, deadline - time.monotonic())))

    def deploy(self) -> None:
        old = self.preflight()
        print("Preflight passed. Existing stack identities retained.")
        self.check_images()
        self.check_protected()
        self.compose_run("run", "--rm", "--no-deps", "--pull", "never", "migrate")
        if self.plan:
            self.migrated = True
            print(f"Migration service completed; verifying pinned addition {REFERENCE_MIGRATION}, exact ledger "
                  "and old migration-only readiness.", flush=True)
        self.backend_health(self.replicas, 0)
        pending = [item for item in old if not self.desired_backend(item)]
        new_count = self.replicas - len(pending)
        for baseline in pending:
            self.check_images()
            self.backend_health(self.replicas, new_count)
            self.guard_old(baseline, running=True)
            wait_args = [] if self.plan else ["--wait", "--wait-timeout", str(self.wait)]
            self.compose_run(
                "up", "-d", "--no-build", "--no-deps", "--pull", "never", "--no-recreate",
                *wait_args, "--scale",
                f"backend={self.replicas + 1}", "backend",
            )
            new_count += 1
            if self.plan:
                self.wait_added_backend(self.replicas + 1, new_count)
                print(f"Reviewed new backend ready; {new_count} replacement(s) verified.")
            else:
                self.backend_health(self.replicas + 1, new_count)
            self.check_images()
            self.guard_old(baseline, running=True)
            self.run(["docker", "stop", "--time", "20", baseline["Id"]])
            running = [item for item in self.backends() if item["State"].get("Running")]
            if len(running) != self.replicas or any(not self.backend_healthy(item) for item in running):
                raise DeployStopped("Remaining backend health failed; no container removal")
            self.check_protected()
            self.readiness(allow_old=any(item["Id"] in self.baseline_backends for item in running))
            self.check_images()
            self.guard_old(baseline, running=False)
            self.run(["docker", "rm", baseline["Id"]])
            if self.plan:
                print(f"Recorded old backend {baseline['Id']} removed after replacement readiness; "
                      "remaining identities retained.", flush=True)
            self.backend_health(self.replicas, new_count)
        self.check_images()
        self.backend_health(self.replicas, self.replicas)
        self.compose_run(
            "up", "-d", "--no-build", "--no-deps", "--pull", "never",
            "--wait", "--wait-timeout", str(self.wait), *self.targets,
        )
        self.check_images()
        self.check_protected()
        self.backend_health(self.replicas, self.replicas)
        current = self.containers()
        for name in self.targets:
            matches = [item for item in current if project(item) == self.project_name and service(item) == name]
            if len(matches) != 1 or matches[0]["Image"] != self.images[name][1] or not healthy(matches[0]):
                raise DeployStopped(f"Updated {name} identity or health failed")
            if network_identity(matches[0]) != self.service_networks[name]:
                raise DeployStopped(f"Updated {name} network identity failed")
            if matches[0]["Config"]["Labels"].get("com.docker.compose.config-hash") != self.service_hashes[name]:
                raise DeployStopped(f"Updated {name} configuration identity failed")
        print(f"Application deployment passed. Commit: {self.commit}")


def main() -> int:
    try:
        ApplicationDeploy(dict(os.environ)).deploy()
    except (DeployStopped, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"Deploy stopped: {exc}. Keep current replicas; review private logs before retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
