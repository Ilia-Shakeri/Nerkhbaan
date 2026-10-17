"""Update a reviewed application release while retaining the existing stack."""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import HTTPRedirectHandler, build_opener


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

    def run(self, args: list[str], *, timeout: int = 300) -> str:
        return command(args, cwd=self.root, timeout=timeout)

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

    def readiness(self) -> None:
        try:
            with build_opener(RejectRedirect()).open(self.readiness_url, timeout=15) as response:
                if response.status != 200 or response.geturl() != self.readiness_url:
                    raise DeployStopped("Target HTTPS readiness failed")
                payload = json.loads(response.read(65536))
            if not isinstance(payload, dict) or payload.get("ready") is not True:
                raise DeployStopped("Target HTTPS readiness payload failed")
        except (OSError, ValueError) as exc:
            raise DeployStopped("Target HTTPS readiness failed") from exc

    def backend_health(self, count: int, new_count: int) -> list[dict]:
        current = self.backends()
        if len(current) != count or any(not healthy(item, require_probe=True) for item in current):
            raise DeployStopped("Backend replica count or health failed; keep remaining replicas")
        if any(network_identity(item) != self.service_networks["backend"] for item in current):
            raise DeployStopped("Backend network identity failed; keep remaining replicas")
        if sum(self.desired_backend(item) for item in current) < new_count:
            raise DeployStopped("Reviewed backend image health failed; keep remaining replicas")
        self.check_protected()
        self.readiness()
        return current

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
        self.readiness()
        return backends

    def check_schema(self, baseline: dict) -> None:
        # A forward ledger makes the old API unready; this route keeps schema fixed.
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
        if desired != expected or current.get("expected") != desired or current.get("applied") != desired:
            raise DeployStopped("Schema differs across release/image/current ledger; use a reviewed migration plan")

    def deploy(self) -> None:
        old = self.preflight()
        print("Preflight passed. Existing stack identities retained.")
        self.check_images()
        self.compose_run("run", "--rm", "--no-deps", "--pull", "never", "migrate")
        self.backend_health(self.replicas, 0)
        pending = [item for item in old if not self.desired_backend(item)]
        new_count = self.replicas - len(pending)
        for baseline in pending:
            self.check_images()
            self.backend_health(self.replicas, new_count)
            self.guard_old(baseline, running=True)
            self.compose_run(
                "up", "-d", "--no-build", "--no-deps", "--pull", "never", "--no-recreate",
                "--wait", "--wait-timeout", str(self.wait), "--scale",
                f"backend={self.replicas + 1}", "backend",
            )
            new_count += 1
            self.backend_health(self.replicas + 1, new_count)
            self.check_images()
            self.guard_old(baseline, running=True)
            self.run(["docker", "stop", "--time", "20", baseline["Id"]])
            running = [item for item in self.backends() if item["State"].get("Running")]
            if len(running) != self.replicas or any(not healthy(item, require_probe=True) for item in running):
                raise DeployStopped("Remaining backend health failed; no container removal")
            self.check_protected()
            self.readiness()
            self.check_images()
            self.guard_old(baseline, running=False)
            self.run(["docker", "rm", baseline["Id"]])
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
    except (DeployStopped, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Deploy stopped: {exc}. Keep current replicas; review private logs before retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
