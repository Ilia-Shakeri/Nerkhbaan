"""Update a reviewed application release while retaining the existing stack."""
from __future__ import annotations

import hashlib
import copy
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import errno
import json
import os
import re
import shutil
import stat
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
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
COMMUNICATIONS_PLAN_KIND = "communications-addition-v1"
COMMUNICATIONS_MIGRATION = "20261021_001_communications.sql"
COMMUNICATIONS_CHECKSUM = "b11b349d3501cadbd73b299e2a99bb8eca8a9045bd01735b07823d115c3ceec2"
COMMUNICATIONS_BASELINE = {
    "20260705_timescale_market_prices.sql": "e8ca07d815c3cc87de094ce72f10074dea1bb85274049d238e2889ce4cdbfc1b",
    "20260718_001_core_pricing.sql": "2e88efcff8e700c0fd03ec3de1ff372e733ce9852260818cb725c3eceb892c7b",
    "20260718_002_auth_admin_alerts.sql": "6a0e99a68686ca51638f420f286c8de574e0f2acd55e7c115ab1fcdf3e5aec77",
    "20260718_003_timescale_policies.sql": "f9d05c77720f16565060748e7e7db7ba8689ca13d76bba28e4855c40191b7fa8",
    "20260802_001_alert_price_source_mode.sql": "74b6e8a32c6d60ef6a79191297287de417f88f9aaabc5f931d6013b0f3c32143",
    "20260809_001_pricing_provider_repair.sql": "9a4c5168c8f520b63c271099e36f48c100881c72d15147e02372a2bea8630275",
    "20261011_001_delivery_hardening.sql": "6ffaa5e4a178e237c2197cfb7ebcd2bb0d1c59e1175fce90a53a26cb863bf4bb",
    "20261011_002_notification_sending_state.sql": "e24183c86ec9348e62976afcd1b25946e6b8e79a9468dd426f3c2af207845aa2",
    REFERENCE_MIGRATION: REFERENCE_CHECKSUM,
}
COMMUNICATIONS_COLUMNS = {
    "admin_secrets": "id key ciphertext key_version updated_by updated_at".split(),
    "communication_recipients": "id owner_user_id label phone_ciphertext phone_masked consented created_at".split(),
    "communication_events": ("id owner_user_id recipient_id channel status dry_run client_request_id delivery_key "
                             "provider_reference error_code attempt_count next_retry_at provider_response_summary "
                             "created_at updated_at").split(),
}
COMMUNICATIONS_CONSTRAINTS = {
    "admin_secrets": "admin_secrets_pkey admin_secrets_key_key admin_secrets_updated_by_fkey".split(),
    "communication_recipients": "communication_recipients_pkey communication_recipients_owner_user_id_fkey".split(),
    "communication_events": ("communication_events_pkey communication_events_owner_user_id_fkey "
                             "communication_events_recipient_id_fkey communication_events_delivery_key_key "
                             "uq_communication_request").split(),
}
COMMUNICATIONS_INDEXES = {
    "admin_secrets_pkey", "admin_secrets_key_key", "communication_recipients_pkey",
    "ix_communication_recipients_owner_user_id", "communication_events_pkey",
    "communication_events_delivery_key_key", "uq_communication_request",
    "ix_communication_events_owner_user_id", "ix_communication_events_status",
}
COMMUNICATIONS_STATUS_KEY = "constraint:public.alert_delivery_jobs.ck_alert_delivery_status"
COMMUNICATIONS_ADDED_COLUMNS = {"column:public.alerts.notify_voip", "column:public.alerts.priority"}
# Stable logical public-schema objects; physical files, row counts and internal dependency
# triggers are omitted. Columns, constraints and indexes describe those dependencies.
COMMUNICATIONS_SCHEMA_SQL = """
SELECT 'namespace:public' AS object_id, to_jsonb(n) - 'oid' AS definition
FROM pg_catalog.pg_namespace n WHERE n.nspname = 'public'
UNION ALL
SELECT 'relation:public.' || c.relname,
 to_jsonb(c) - ARRAY['oid','relfilenode','relpages','reltuples','relallvisible','relallfrozen',
 'relfrozenxid','relminmxid','reltoastrelid','relnatts','relchecks']::text[]
FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public'
UNION ALL
SELECT 'column:public.' || c.relname || '.' || a.attname,
 jsonb_build_object('type',pg_catalog.format_type(a.atttypid,a.atttypmod),
 'nullable',NOT a.attnotnull,'default',pg_catalog.pg_get_expr(d.adbin,d.adrelid),
 'identity',a.attidentity,'generated',a.attgenerated,'position',a.attnum,
 'collation',a.attcollation,'storage',a.attstorage,'statistics',a.attstattarget,
 'options',a.attoptions,'acl',a.attacl,'compression',a.attcompression)
FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON c.oid=a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f','c') AND a.attnum>0 AND NOT a.attisdropped
UNION ALL
SELECT 'constraint:public.' || COALESCE(c.relname,t.typname) || '.' || k.conname,
 jsonb_build_object('kind',k.contype,'definition',pg_catalog.pg_get_constraintdef(k.oid,true),
 'deferrable',k.condeferrable,'initially_deferred',k.condeferred,'validated',k.convalidated,
 'no_inherit',k.connoinherit)
FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_namespace n ON n.oid=k.connamespace
LEFT JOIN pg_catalog.pg_class c ON c.oid=k.conrelid LEFT JOIN pg_catalog.pg_type t ON t.oid=k.contypid
WHERE n.nspname='public'
UNION ALL
SELECT 'index:public.' || c.relname, jsonb_build_object('definition',pg_catalog.pg_get_indexdef(i.indexrelid),
 'valid',i.indisvalid,'ready',i.indisready,'live',i.indislive,'clustered',i.indisclustered,
 'replica_identity',i.indisreplident)
FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
UNION ALL
SELECT 'sequence:public.' || c.relname, to_jsonb(s) - 'seqrelid'
FROM pg_catalog.pg_sequence s JOIN pg_catalog.pg_class c ON c.oid=s.seqrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
UNION ALL
SELECT 'type:public.' || t.typname, to_jsonb(t) - 'oid' || jsonb_build_object('enum_labels',
 (SELECT jsonb_agg(e.enumlabel ORDER BY e.enumsortorder) FROM pg_catalog.pg_enum e WHERE e.enumtypid=t.oid))
FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'
UNION ALL
SELECT 'function:public.' || p.proname || '(' || pg_catalog.pg_get_function_identity_arguments(p.oid) || ')',
 to_jsonb(p) - 'oid'
FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public'
UNION ALL
SELECT 'trigger:public.' || c.relname || '.' || t.tgname,
 jsonb_build_object('definition',pg_catalog.pg_get_triggerdef(t.oid,true),'enabled',t.tgenabled)
FROM pg_catalog.pg_trigger t JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal
UNION ALL
SELECT 'rule:public.' || c.relname || '.' || r.rulename,
 jsonb_build_object('definition',pg_catalog.pg_get_ruledef(r.oid,true),'enabled',r.ev_enabled)
FROM pg_catalog.pg_rewrite r JOIN pg_catalog.pg_class c ON c.oid=r.ev_class
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
UNION ALL
SELECT 'policy:public.' || c.relname || '.' || p.polname, to_jsonb(p) - 'oid'
FROM pg_catalog.pg_policy p JOIN pg_catalog.pg_class c ON c.oid=p.polrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
UNION ALL
SELECT 'extension:' || e.extname, to_jsonb(e) - 'oid'
FROM pg_catalog.pg_extension e
ORDER BY object_id
"""


def communications_added_objects() -> set[str]:
    names = set(COMMUNICATIONS_ADDED_COLUMNS)
    for table, columns in COMMUNICATIONS_COLUMNS.items():
        names |= {"relation:public." + table, "relation:public." + table + "_id_seq",
                  "sequence:public." + table + "_id_seq", "type:public." + table, "type:public._" + table}
        names |= {f"column:public.{table}.{column}" for column in columns}
        names |= {f"constraint:public.{table}.{name}" for name in COMMUNICATIONS_CONSTRAINTS[table]}
    for name in COMMUNICATIONS_INDEXES:
        names |= {"relation:public." + name, "index:public." + name}
    return names


def communications_schema_snapshot(rows) -> dict:
    """Encode rows from COMMUNICATIONS_SCHEMA_SQL on one isolated restored database."""
    objects, details = {}, {}
    for identifier, definition in rows:
        if not isinstance(identifier, str) or identifier in objects or not isinstance(definition, dict):
            raise DeployStopped("Schema snapshot contains malformed or duplicate objects")
        objects[identifier] = hashlib.sha256(json.dumps(
            definition, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode()).hexdigest()
        if identifier.startswith("relation:") or identifier in COMMUNICATIONS_ADDED_COLUMNS | {COMMUNICATIONS_STATUS_KEY}:
            details[identifier] = definition
    tables = {key.removeprefix("relation:") for key, value in details.items()
              if key.startswith("relation:") and value.get("relkind") in {"r", "p"}}
    columns = {table: sorted(key.removeprefix("column:" + table + ".") for key in objects
                            if key.startswith("column:" + table + "."))
               for table in sorted(tables) if table != "public.schema_migrations"}
    return {"objects": objects, "details": details, "data_columns": columns}


def validate_communications_schema(before: dict, after: dict) -> dict:
    """Reject every logical public-schema delta beyond the pinned tenth migration."""
    for snapshot in (before, after):
        if not isinstance(snapshot, dict) or set(snapshot) != {"objects", "details", "data_columns"}:
            raise DeployStopped("Communications restore needs complete canonical schema snapshots")
        objects, details = snapshot["objects"], snapshot["details"]
        if not isinstance(objects, dict) or not objects or any(
            not isinstance(key, str) or not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
            for key, value in objects.items()
        ) or not isinstance(details, dict):
            raise DeployStopped("Communications schema object map is malformed")
        detail_keys = {key for key in objects if key.startswith("relation:") or
                       key in COMMUNICATIONS_ADDED_COLUMNS | {COMMUNICATIONS_STATUS_KEY}}
        if set(details) != detail_keys or any(not isinstance(value, dict) or objects[key] != hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest() for key, value in details.items()):
            raise DeployStopped("Communications schema details differ from their object hashes")
        tables = {key.removeprefix("relation:") for key, value in details.items()
                  if key.startswith("relation:") and value.get("relkind") in {"r", "p"}}
        columns = {table: sorted(key.removeprefix("column:" + table + ".") for key in objects
                                if key.startswith("column:" + table + "."))
                   for table in sorted(tables) if table != "public.schema_migrations"}
        if snapshot["data_columns"] != columns or any(not values for values in columns.values()):
            raise DeployStopped("Communications restore data projection omits baseline table columns")
    old, new = before["objects"], after["objects"]
    if set(new) - set(old) != communications_added_objects() or set(old) - set(new) or (
        {key for key in old if old[key] != new.get(key)} != {COMMUNICATIONS_STATUS_KEY}
    ):
        raise DeployStopped("Communications restore contains an unreviewed schema addition, removal or change")
    statuses = "pending processing sending delivered retrying failed dead cancelled".split()
    for snapshot, expected in ((before, statuses), (after, statuses[:3] + ["accepted"] + statuses[3:] + ["unknown"])):
        item = snapshot["details"].get(COMMUNICATIONS_STATUS_KEY, {})
        definition = item.get("definition", "")
        if not isinstance(definition, str):
            raise DeployStopped("Communications status constraint is malformed")
        normalized = re.sub(r"\s+", "", definition).replace("::text[]", "").replace("::charactervarying", "").replace("::text", "")
        normalized = normalized.replace("(", "").replace(")", "")
        if normalized != "CHECKstatus=ANYARRAY[" + ",".join("'" + value + "'" for value in expected) + "]" or (
            item.get("kind") != "c" or item.get("validated") is not True or
            item.get("deferrable") is not False or item.get("initially_deferred") is not False or
            item.get("no_inherit") is not False
        ):
            raise DeployStopped("Communications status constraint differs from the exact reviewed values")
    for key, kind, default in (("column:public.alerts.notify_voip", "boolean", "false"),
                               ("column:public.alerts.priority", "character varying(16)", "'normal'::character varying")):
        column = after["details"][key]
        if column.get("type") != kind or column.get("nullable") is not False or column.get("default") != default or (
            column.get("identity") != "" or column.get("generated") != ""
        ):
            raise DeployStopped("Communications alert columns differ from the reviewed safe defaults")
    return before["data_columns"]
RESUME_KIND = "iranian-reference-resume-after-first-candidate-v1"
RESUME_FILES = {
    "failed_attempt", "failed_proof", "failed_log", "migration_plan", "image_manifest",
    "restore_report", "restore_transcript", "operator_evidence", "compose_override",
    "private_environment", "guard_ci", "fresh_observation",
}
SEMANTIC_CHECKS = {
    "environment", "command", "entrypoint", "user", "working_dir", "stop_signal",
    "custom_labels", "exposed_ports", "healthcheck", "cap_drop", "security_options",
    "read_only_rootfs", "restart_policy", "published_ports", "mounts", "networks",
}
NORMAL_RESUME_KIND = "normal-same-ledger-resume-after-stopped-old-v1"
NORMAL_RESUME_FILES = {
    "original_preflight", "failed_attempt", "failed_proof", "failed_log", "image_manifest",
    "operator_evidence", "compose_override", "private_environment", "guard_ci", "fresh_observation",
}
NORMAL_PRIVATE_NAMES = {
    "operator-gates.json", "operator-finalization-proof.json", "operator-evidence-index.json",
    "source-rights-reviewed.json", "source-rights-probe-attempt.json", "prepared-images.json",
    "execution-plan.json", "stage-proof.json", "predeployment-baseline.json",
    "reviewed-private-environment-proof.json", "ci-run.json", "ci-jobs.json",
    "runtime-trivy-summary.json", "runtime-build-checks.json", "private_environment", "runtime_override",
}
NORMAL_RESUME_CI_JOBS = {
    "Node lock and builds", "Compose configuration", "Build and scan web image",
    "Python static and unit checks", "Desktop package", "Repository security scans",
    "Build and scan relay image", "Build and scan telegram image", "Feed pull Go checks",
    "Build and scan api image", "Build and scan feed-pull image", "Browser auth and alerts",
    "Build and scan admin image", "Timescale, Redis, and migrations", "Build and scan edge image",
}
MIGRATION_COMMAND = ["python", "-m", "app.migrations.runner"]


def private_bytes(path: Path) -> bytes:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise DeployStopped("Migration evidence must be an existing absolute private regular file")
    info = path.stat()
    if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise DeployStopped("Migration evidence must be owned by the deploy user with private permissions")
    return path.read_bytes()


class DeployStopped(RuntimeError):
    def __init__(self, message: str, *, failure_type: str = "validation"):
        self.failure_type = failure_type
        super().__init__(message)


class TransientReadiness(DeployStopped):
    def __init__(self, safe_type: str):
        self.safe_type = safe_type
        super().__init__("Transient target readiness transport failure")


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def command(args: list[str], *, cwd: Path, timeout: int = 300, input_text: str | None = None) -> str:
    executable = shutil.which(args[0]) or args[0]
    try:
        result = subprocess.run(
            [executable, *args[1:]], cwd=cwd, capture_output=True,
            text=True, check=False, timeout=timeout, input=input_text,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        failure_type = "command_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "command_unavailable"
        raise DeployStopped(f"Command unavailable or timed out: {Path(args[0]).name}", failure_type=failure_type) from exc
    if result.returncode:
        # Config and migration output can contain private environment values.
        raise DeployStopped(f"Command failed: {Path(args[0]).name}; inspect private service logs", failure_type="command_failed")
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


def fingerprint(container: dict) -> str:
    value = identity(container) | {"Running": container["State"]["Running"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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
        self.override = override
        self.guard_root = Path(__file__).resolve().parents[1]
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
        self.resume_path = Path(env["DEPLOY_RESUME_PLAN"]) if env.get("DEPLOY_RESUME_PLAN") else None
        self.resume_plan: dict | None = None
        self.normal_resume_path = Path(env["DEPLOY_NORMAL_RESUME_PLAN"]) if env.get("DEPLOY_NORMAL_RESUME_PLAN") else None
        self.normal_resume_plan: dict | None = None
        self.retirement_new_count: int | None = None
        if self.normal_resume_path is not None and (self.plan_path is not None or self.resume_path is not None):
            raise DeployStopped("Normal same-ledger resume cannot select either migration-transition plan")

    def bounded_timeout(self, timeout: float) -> float:
        if self.startup_deadline is not None:
            remaining = self.startup_deadline - time.monotonic()
            if remaining <= 0:
                raise DeployStopped("New backend readiness timed out; keep remaining replicas", failure_type="deadline_before_command")
            timeout = min(timeout, remaining)
        return timeout

    def run(self, args: list[str], *, timeout: int = 300, input_text: str | None = None) -> str:
        try:
            return command(args, cwd=self.root, timeout=self.bounded_timeout(timeout), input_text=input_text)
        except DeployStopped as exc:
            if args[:2] == ["docker", "exec"]:
                kind = "backend_probe"
            elif args[:3] == ["docker", "image", "inspect"]:
                kind = "image_inspect"
            elif args[:2] == ["docker", "compose"]:
                kind = "compose_config" if "config" in args else "compose_inventory"
            elif args[:2] == ["docker", "inspect"]:
                kind = "container_inspect"
            elif args[:2] == ["docker", "ps"]:
                kind = "container_inventory"
            elif args[:2] == ["docker", "rm"]:
                kind = "old_remove"
            else:
                kind = "source_guard" if args[0] == "git" else "guard_command"
            exc.command_kind = kind
            raise

    def compose_run(self, *args: str) -> str:
        return self.run([*self.compose, *args], timeout=self.wait + 60)

    def resolved_service_hash(self, name: str) -> str:
        # Compose's raw hash path skips env_file resolution; hash the reviewed resolved model.
        args = [
            "docker", "compose", "-p", self.project_name, "--env-file", str(self.env_file),
            "--project-directory", str(self.root), "-f", "-", "--profile", "admin",
            "config", "--hash", name,
        ]
        hashed = self.run(args, timeout=self.wait + 60, input_text=json.dumps(self.config)).split()
        if len(hashed) != 2 or hashed[0] != name or not re.fullmatch(r"[a-f0-9]{64}", hashed[1]):
            raise DeployStopped(f"Cannot resolve reviewed {name} configuration identity")
        return hashed[1]

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
        if getattr(self, "normal_resume_plan", None):
            identifier = self.normal_resume_plan["added_backend"]["id"]
            current = self.inspect([identifier])
            if len(current) != 1 or fingerprint(current[0]) != self.normal_resume_observation["current_container_fingerprints"][identifier]:
                raise DeployStopped("Recorded same-ledger candidate identity changed; keep remaining replicas")
        if self.resume_plan:
            identifier = self.resume_plan["added_backend"]["id"]
            current = self.inspect([identifier])
            if len(current) != 1 or fingerprint(current[0]) != self.resume_observation["current_container_fingerprints"][identifier]:
                raise DeployStopped("Recorded existing candidate identity changed; keep remaining replicas")
        selected = {}
        for image, expected in self.images.values():
            if image in selected and selected[image] != expected:
                raise DeployStopped("Reviewed image alias has conflicting identities")
            selected[image] = expected
        actual = json.loads(self.run(["docker", "image", "inspect", *selected]))
        if not isinstance(actual, list) or len(actual) != len(selected) or any(
            not isinstance(row, dict) or row.get("Id") != expected
            for row, expected in zip(actual, selected.values())
        ):
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
        allowed = set(self.targets) | {"backend"}
        if not getattr(self, "resume_plan", None) and not getattr(self, "normal_resume_plan", None):
            allowed.add("migrate")
        for container_id, item in current.items():
            if container_id not in self.protected and not (
                project(item) == self.project_name and service(item) in allowed
            ):
                raise DeployStopped("Unexpected protected container appeared; stop and review")

    @staticmethod
    def transient_readiness_type(error: BaseException) -> str | None:
        reason = error.reason if isinstance(error, URLError) else error
        if isinstance(reason, ssl.SSLError):
            return None
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "transport_timeout"
        if isinstance(reason, OSError) and reason.errno in {
            errno.ECONNRESET, errno.ECONNREFUSED, errno.ECONNABORTED,
            errno.ETIMEDOUT, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPIPE,
        }:
            return "transport_connect_or_reset"
        return None

    @contextmanager
    def retirement_budget(self):
        started = time.monotonic()
        previous = self.startup_deadline
        previous_started = getattr(self, "retirement_started", None)
        deadline = min(started + 30, previous) if previous is not None else started + 30
        self.startup_deadline = deadline
        self.retirement_started = started
        try:
            yield started, deadline
        except DeployStopped as exc:
            if "stage=retirement" in str(exc):
                raise
            elapsed = time.monotonic() - started
            operation = getattr(exc, "retirement_operation", getattr(self, "retirement_operation", "guard"))
            kind = getattr(exc, "command_kind", "none")
            remaining = max(0.0, deadline - time.monotonic())
            raise DeployStopped(f"Target HTTPS readiness failed; stage=retirement type={exc.failure_type} "
                                f"operation={operation} command={kind} elapsed={elapsed:.3f}s remaining={remaining:.3f}s") from exc
        finally:
            self.startup_deadline = previous
            self.retirement_started = previous_started

    @contextmanager
    def retirement_step(self, operation: str):
        previous = getattr(self, "retirement_operation", "guard")
        self.retirement_operation = operation
        try:
            yield
        except DeployStopped as exc:
            if not hasattr(exc, "retirement_operation"):
                exc.retirement_operation = operation
            raise
        finally:
            self.retirement_operation = previous

    def readiness(self, *, allow_old: bool = False, retirement: bool = False) -> None:
        if not retirement:
            self.readiness_once(allow_old=allow_old)
            return
        if getattr(self, "retirement_started", None) is not None:
            self.wait_retirement_readiness(allow_old=allow_old, started=self.retirement_started, deadline=self.startup_deadline)
            return
        with self.retirement_budget() as (started, deadline):
            self.wait_retirement_readiness(allow_old=allow_old, started=started, deadline=deadline)

    def wait_retirement_readiness(self, *, allow_old: bool, started: float, deadline: float) -> None:
        safe_type = "deadline"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                with self.retirement_step("public_probe"):
                    self.readiness_once(allow_old=allow_old, timeout=min(5, remaining), retirement=True)
                if time.monotonic() >= deadline:
                    safe_type = "late_success"
                    break
                return
            except TransientReadiness as exc:
                safe_type = exc.safe_type
                with self.retirement_step("retry_images"):
                    self.check_images()
                with self.retirement_step("retry_protected"):
                    self.check_protected()
                with self.retirement_step("retry_pair"):
                    self.check_retirement_pair()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(2, remaining))
            except DeployStopped as exc:
                elapsed = time.monotonic() - started
                raise DeployStopped(f"Target HTTPS readiness failed; stage=retirement type={exc.failure_type} "
                                    f"operation=public_probe command=none elapsed={elapsed:.3f}s") from exc
        elapsed = time.monotonic() - started
        raise DeployStopped(f"Target HTTPS readiness failed; stage=retirement type={safe_type} operation=public_probe "
                            f"command=none elapsed={elapsed:.3f}s")

    def normal_pair_healthy(self, items: list[dict]) -> bool:
        executor = ThreadPoolExecutor(max_workers=2)
        futures = []
        try:
            futures = [executor.submit(self.backend_healthy, item) for item in items]
            results = [future.result(timeout=self.bounded_timeout(30)) for future in futures]
            self.bounded_timeout(30)
            return all(results)
        except FutureTimeout as exc:
            raise DeployStopped("Strict normal backend probes reached the shared deadline", failure_type="command_timeout") from exc
        finally:
            for future in futures:
                future.cancel()
            # Each real probe command shares startup_deadline; retain it until all readers exit.
            executor.shutdown(wait=True, cancel_futures=True)

    def check_retirement_pair(self) -> None:
        running = [item for item in self.backends() if item["State"].get("Running")]
        expected_new = self.retirement_new_count if self.retirement_new_count is not None else 1
        if len(running) != self.replicas:
            raise DeployStopped("Remaining backend pair changed during retirement readiness wait")
        pair_healthy = self.normal_pair_healthy(running) if getattr(self, "normal_resume_plan", None) else all(
            self.backend_healthy(item) for item in running
        )
        if not pair_healthy or (
            any(network_identity(item) != self.service_networks["backend"] for item in running) or
            sum(self.desired_backend(item) for item in running) < expected_new
        ):
            raise DeployStopped("Remaining backend pair changed during retirement readiness wait")

    def readiness_once(self, *, allow_old: bool = False, timeout: float = 15, retirement: bool = False) -> None:
        try:
            try:
                response = build_opener(RejectRedirect()).open(
                    self.readiness_url, timeout=self.bounded_timeout(timeout),
                )
            except HTTPError as exc:
                if retirement and exc.code in {502, 504}:
                    raise TransientReadiness("http_" + str(exc.code)) from exc
                if exc.code != 503:
                    raise
                response = exc
            with response:
                if response.geturl() != self.readiness_url:
                    raise DeployStopped("Target HTTPS readiness failed")
                payload = json.loads(response.read(65536))
                status = response.status
            self.bounded_timeout(timeout)
            if allow_old and status == 503 and self.plan and self.migrated:
                self.validate_payload(payload, old=True, status=status)
                return
            if status != 200 or not isinstance(payload, dict) or payload.get("ready") is not True:
                raise DeployStopped("Target HTTPS readiness payload failed")
            if self.plan:
                self.validate_payload(payload, old=not self.migrated, status=status)
            if getattr(self, "normal_resume_plan", None):
                self.validate_normal_payload(payload, status=status, old=allow_old and payload.get("release_version") == "2.8.8")
        except (OSError, ValueError) as exc:
            if retirement:
                safe_type = self.transient_readiness_type(exc)
                if safe_type is not None:
                    raise TransientReadiness(safe_type) from exc
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
        if getattr(self, "normal_resume_plan", None):
            if not healthy(item, require_probe=True):
                return False
            self.validate_normal_probe(self.backend_probe(item), old=item["Id"] in self.baseline_backends)
            return True
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
        communications = self.plan.get("kind") == COMMUNICATIONS_PLAN_KIND
        release = self.plan["baseline_backends"][0]["release_version"] if old else (
            self.plan["application_version"] if communications else "2.8.8")
        addition = COMMUNICATIONS_MIGRATION if communications else REFERENCE_MIGRATION
        expected = {
            "ready": not old_after, "status": "degraded" if old_after else "ok",
            "database": "connected", "redis": "connected", "migration_current": not old_after,
            "migration_version": addition if self.migrated else max(self.plan["baseline_migrations"]),
            "release_version": release,
        }
        if status != (503 if old_after else 200) or not isinstance(payload, dict) or any(
            payload.get(key) != value or isinstance(value, bool) and type(payload.get(key)) is not bool
            for key, value in expected.items()
        ):
            raise DeployStopped("Strict readiness or reviewed old migration-only state failed")

    def old_migration_state(self) -> dict:
        if self.plan.get("kind") == COMMUNICATIONS_PLAN_KIND:
            return {"current": False, "version": COMMUNICATIONS_MIGRATION, "applied_count": 10,
                    "expected_count": 9, "missing": [], "changed": [], "unknown": [COMMUNICATIONS_MIGRATION]}
        return {"current": False, "version": REFERENCE_MIGRATION, "applied_count": 9,
                "expected_count": 8, "missing": [], "changed": [], "unknown": [REFERENCE_MIGRATION]}

    def check_plan_files(self) -> None:
        for path, checksum in self.plan_files.items():
            if hashlib.sha256(private_bytes(path)).hexdigest() != checksum:
                raise DeployStopped("Reviewed migration plan or restore evidence changed")
        if self.plan:
            self.check_proof_time(self.proof["checked_at"])
        if getattr(self, "resume_plan", None):
            self.check_resume_time(self.resume_observation["checked_at"])
            self.check_guard_source()
        if getattr(self, "normal_resume_plan", None):
            self.check_resume_time(self.normal_resume_observation["checked_at"])
            self.check_normal_guard_source()

    def check_normal_guard_source(self) -> None:
        expected = self.normal_resume_plan["guard_commit"]
        if self.run(["git", "-C", str(self.guard_root), "rev-parse", "HEAD"]) != expected or self.run(
            ["git", "-C", str(self.guard_root), "status", "--porcelain", "--untracked-files=no"]
        ) or self.run(["git", "-C", str(self.guard_root), "diff", "--name-only", self.commit, expected,
                       "--", "apps", "packages", "VERSION", "package.json", "package-lock.json",
                       "docker-compose.prod.yaml", ".npmrc"]):
            raise DeployStopped("Same-ledger recovery guard must retain the exact application source and runtime recipes")

    def validate_normal_payload(self, payload: dict, *, status: int, old: bool) -> None:
        expected = {"ready": True, "status": "ok", "database": "connected", "redis": "connected",
                    "migration_current": True, "migration_version": max(self.normal_resume_plan["target_migrations"]),
                    "release_version": "2.8.8" if old else "2.8.11"}
        if status != 200 or not isinstance(payload, dict) or any(
            payload.get(key) != value or isinstance(value, bool) and type(payload.get(key)) is not bool
            for key, value in expected.items()
        ):
            raise DeployStopped("Same-ledger resume requires strict current old/new readiness")

    def validate_normal_probe(self, probe: dict, *, old: bool) -> None:
        if not isinstance(probe, dict):
            raise DeployStopped("Same-ledger API probe must be an object")
        self.validate_normal_payload(probe.get("payload"), status=probe.get("status"), old=old)
        ledger = self.normal_resume_plan["target_migrations"]
        state = {"current": True, "version": max(ledger), "applied_count": 9, "expected_count": 9,
                 "missing": [], "changed": [], "unknown": []}
        if probe.get("expected") != ledger or probe.get("applied") != ledger or probe.get("migration_state") != state:
            raise DeployStopped("Same-ledger API files and applied nine-migration ledger differ")

    def load_normal_resume_plan(self, current: list[dict]) -> None:
        raw = private_bytes(self.normal_resume_path)
        plan = json.loads(raw)
        binding_keys = {"application_commit", "guard_commit", "application_version", "project", "readiness_url",
                        "images", "baseline_backends", "stopped_backend", "added_backend", "target_migrations"}
        if not isinstance(plan, dict) or set(plan) != binding_keys | {"schema_version", "kind", "files"} or (
            type(plan["schema_version"]) is not int or plan["schema_version"] != 1 or plan["kind"] != NORMAL_RESUME_KIND or
            plan["application_commit"] != self.commit or plan["application_version"] != "2.8.11" or
            (self.root / "VERSION").read_text().strip() != "2.8.11" or
            not isinstance(plan["guard_commit"], str) or not re.fullmatch(r"[a-f0-9]{40}", plan["guard_commit"]) or
            plan["project"] != self.project_name or plan["readiness_url"] != self.readiness_url or
            plan["images"] != {name: value[1] for name, value in self.images.items()} or
            not isinstance(plan["target_migrations"], dict) or len(plan["target_migrations"]) != 9 or
            not isinstance(plan["files"], dict) or set(plan["files"]) != NORMAL_RESUME_FILES
        ):
            raise DeployStopped("Unsupported explicit normal same-ledger resume plan")
        self.normal_resume_plan = plan
        self.plan_files[self.normal_resume_path] = hashlib.sha256(raw).hexdigest()
        inputs = {name: self.read_bound_file(reference) for name, reference in plan["files"].items()}
        self.check_normal_guard_source()
        selected = {"image_manifest": self.manifest, "operator_evidence": self.evidence,
                    "compose_override": self.override, "private_environment": self.env_file}
        if any(Path(plan["files"][name]["path"]).resolve() != path.resolve() for name, path in selected.items()):
            raise DeployStopped("Normal resume selected private runtime inputs differ")
        pre, attempt, failed, observation, ci = [json.loads(inputs[name]) for name in (
            "original_preflight", "failed_attempt", "failed_proof", "fresh_observation", "guard_ci")]
        if any(not isinstance(value, dict) for value in [pre, attempt, failed, observation, ci]):
            raise DeployStopped("Normal resume evidence must contain objects")
        artifact = Path(plan["files"]["original_preflight"]["path"]).parent
        for key, name in [("original_preflight", "preflight-proof.json"),
                          ("failed_attempt", "deployment-wrapper-attempt.json"),
                          ("failed_proof", "deployment-wrapper-proof.json")]:
            if Path(plan["files"][key]["path"]) != artifact / name:
                raise DeployStopped("Normal resume original receipt paths differ")
        if pre.get("commit") != self.commit or pre.get("mode") != "preflight" or pre.get("passed") is not True or (
            pre.get("same_ledger_no_transition_plan_valid") is not True or
            any(value.get("release_version") != "2.8.11" for value in [pre, attempt, failed]) or
            failed.get("mode") != "deploy" or failed.get("commit") != self.commit or failed.get("passed") is not False or
            type(failed.get("returncode")) is not int or failed["returncode"] == 0 or
            failed.get("wrapper_success_marker") is not False or failed.get("migration_plan_selected") is not False or
            failed.get("resume_plan_selected") is not False or
            failed.get("usual_idempotent_migrator_invoked_by_guard") is not True or
            attempt.get("mode") != "deploy" or attempt.get("commit") != self.commit or
            failed.get("started_at") != attempt.get("started_at") or
            failed.get("private_log") != attempt.get("private_log") or
            attempt.get("private_log") != plan["files"]["failed_log"]["path"] or
            failed.get("log_sha256") != plan["files"]["failed_log"]["sha256"] or
            attempt.get("preflight_proof_sha256") != plan["files"]["original_preflight"]["sha256"] or
            failed.get("preflight_proof_sha256") != attempt.get("preflight_proof_sha256")
        ):
            raise DeployStopped("Normal resume original failed wrapper chain differs")
        log_path = Path(plan["files"]["failed_log"]["path"])
        lines = inputs["failed_log"].decode("utf-8").splitlines()
        if log_path.parent != artifact or not log_path.name.startswith("deploy-") or log_path.suffix != ".log" or lines != [
            "Preflight passed. Existing stack identities retained.",
            "Deploy stopped: Target HTTPS readiness failed. Keep current replicas; review private logs before retry.",
        ]:
            raise DeployStopped("Normal resume requires the actual failed retirement log without transition markers")
        bindings = pre.get("private_bindings")
        if not isinstance(bindings, dict) or set(bindings) != NORMAL_PRIVATE_NAMES or (
            bindings != attempt.get("private_bindings") or bindings != failed.get("private_bindings")
        ):
            raise DeployStopped("Normal resume requires all sixteen original private bindings")
        for name, reference in bindings.items():
            expected = self.env_file if name == "private_environment" else self.override if name == "runtime_override" else artifact / name
            if not isinstance(reference, dict) or set(reference) != {"path", "sha256"} or Path(reference["path"]).resolve() != expected.resolve():
                raise DeployStopped("Normal resume original private binding path differs")
            self.read_bound_file(reference)
        for selected_name, bound_name in {"image_manifest": "prepared-images.json", "operator_evidence": "operator-gates.json",
                                           "compose_override": "runtime_override", "private_environment": "private_environment"}.items():
            if plan["files"][selected_name] != bindings[bound_name]:
                raise DeployStopped("Normal resume selected inputs differ from original preflight")
        run, run_attempt, jobs = ci.get("run_id"), ci.get("run_attempt"), ci.get("jobs")
        if type(ci.get("schema_version")) is not int or ci["schema_version"] != 1 or ci.get("guard_commit") != plan["guard_commit"] or (
            type(run) is not int or run <= 0 or type(run_attempt) is not int or run_attempt <= 0 or
            ci.get("run_url") != "https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/" + str(run) or
            ci.get("status") != "completed" or ci.get("conclusion") != "success" or
            not isinstance(jobs, list) or len(jobs) != 15 or any(not isinstance(row, dict) for row in jobs) or
            {row.get("name") for row in jobs} != NORMAL_RESUME_CI_JOBS or len({row.get("id") for row in jobs}) != 15 or
            any(type(row.get("id")) is not int or row["id"] <= 0 or type(row.get("run_id")) is not int or
                type(row.get("run_attempt")) is not int or row["run_id"] != run or row["run_attempt"] != run_attempt or
                row.get("head_sha") != plan["guard_commit"] or row.get("status") != "completed" or row.get("conclusion") != "success"
                for row in jobs)
        ):
            raise DeployStopped("Normal resume requires fifteen exact successful hosted guard jobs")
        if observation.get("schema_version") != 1 or type(observation.get("schema_version")) is not int or (
            observation.get("kind") != NORMAL_RESUME_KIND or observation.get("source") != "actual_target_read_only" or
            observation.get("binding") != {key: plan[key] for key in binding_keys} or
            observation.get("semantic_checks") != {name: True for name in SEMANTIC_CHECKS} or
            any(value is not True for value in observation.get("semantic_checks", {}).values())
        ):
            raise DeployStopped("Normal resume fresh observation binding differs")
        self.normal_resume_observation = observation
        self.check_resume_time(observation.get("checked_at"))
        try:
            clocks = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (
                pre["checked_at"], attempt["started_at"], failed["checked_at"], observation["checked_at"])]
            if any(value.tzinfo is None or value.utcoffset().total_seconds() != 0 for value in clocks) or clocks != sorted(clocks):
                raise ValueError("normal resume chronology differs")
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            raise DeployStopped("Normal resume needs ordered UTC preflight, failure and fresh observation") from exc
        baseline, baseline_roles = attempt.get("baseline_container_fingerprints"), attempt.get("baseline_container_roles")
        by_id = {item["Id"]: item for item in current}
        actual = {key: fingerprint(item) for key, item in by_id.items()}
        roles = {key: {"project": project(item), "service": service(item)} for key, item in by_id.items()}
        added, stopped, old = plan["added_backend"], plan["stopped_backend"], plan["baseline_backends"]
        if not isinstance(added, dict) or set(added) != {"id", "image", "config_hash"} or (
            not isinstance(stopped, dict) or set(stopped) != {"id", "exit_code", "oom_killed"} or
            type(stopped.get("exit_code")) is not int or stopped["exit_code"] != 137 or stopped.get("oom_killed") is not False or
            not isinstance(baseline, dict) or len(baseline) != 22 or not isinstance(baseline_roles, dict) or set(baseline_roles) != set(baseline) or
            pre.get("container_fingerprints") != baseline or observation.get("baseline_container_fingerprints") != baseline or
            observation.get("current_container_fingerprints") != actual or observation.get("current_container_roles") != roles or
            added.get("id") in baseline or set(actual) != set(baseline) | {added.get("id")} or len(actual) != 23 or
            stopped.get("id") not in baseline or roles.get(added.get("id")) != {"project": self.project_name, "service": "backend"} or
            added.get("image") != self.images["backend"][1] or added.get("config_hash") != self.backend_hash or
            any(roles.get(key) != value for key, value in baseline_roles.items())
        ):
            raise DeployStopped("Normal resume requires the exact original twenty-two and one recorded candidate")
        stopped_item = by_id[stopped["id"]]
        restored = copy.deepcopy(stopped_item)
        restored["State"]["Running"] = True
        if stopped_item["State"].get("Running") is not False or stopped_item["State"].get("ExitCode") != stopped["exit_code"] or (
            stopped_item["State"].get("OOMKilled") is not False or fingerprint(restored) != baseline[stopped["id"]] or
            any(actual[key] != value for key, value in baseline.items() if key != stopped["id"])
        ):
            raise DeployStopped("Only the recorded old backend running bit may differ")
        old_ids = {key for key, role in baseline_roles.items() if role == {"project": self.project_name, "service": "backend"}}
        if not isinstance(old, list) or len(old) != 2 or self.replicas != 2 or any(not isinstance(row, dict) for row in old) or (
            {row.get("id") for row in old} != old_ids or len(old_ids) != 2 or stopped["id"] not in old_ids or
            set(pre.get("baseline_backend_ids", [])) != old_ids or
            any(set(row) != {"id", "image", "release_version"} or row["release_version"] != "2.8.8" or by_id[row["id"]]["Image"] != row["image"] for row in old)
        ):
            raise DeployStopped("Normal resume old API identities differ from the original pair")
        self.baseline_backends = {row["id"]: by_id[row["id"]] for row in old}
        self.normal_stopped = stopped_item
        candidate = by_id[added["id"]]
        if not self.desired_backend(candidate) or not healthy(candidate, require_probe=True) or any(
            not healthy(by_id[key], require_probe=True) for key in old_ids if key != stopped["id"]
        ):
            raise DeployStopped("Normal resume requires the recorded candidate and remaining old API healthy")
        canonical = hashlib.sha256(json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if observation.get("resolved_config_sha256") != canonical or observation.get("service_hashes") != self.service_hashes or (
            observation.get("service_networks") != self.service_networks or pre.get("service_hashes") != self.service_hashes or
            pre.get("service_networks") != self.service_networks or pre.get("resolved_configuration_sha256") != canonical
        ):
            raise DeployStopped("Normal resume resolved configuration differs from original reviewed model")
        probes = observation.get("probes")
        running_ids = (old_ids - {stopped["id"]}) | {added["id"]}
        if not isinstance(probes, list) or len(probes) != 2 or any(not isinstance(row, dict) for row in probes) or {row.get("id") for row in probes} != running_ids:
            raise DeployStopped("Normal resume needs the two running exact API probes")
        for probe in probes:
            if probe.get("image") != by_id[probe["id"]]["Image"]:
                raise DeployStopped("Normal resume probe image differs")
            self.validate_normal_probe(probe, old=probe["id"] in old_ids)

    def check_guard_source(self) -> None:
        if self.run(["git", "-C", str(self.guard_root), "rev-parse", "HEAD"]) != self.resume_plan["guard_commit"] or self.run(
            ["git", "-C", str(self.guard_root), "status", "--porcelain", "--untracked-files=no"]
        ):
            raise DeployStopped("Reviewed guard source changed; keep application checkout and remaining replicas")
        if self.run(["git", "-C", str(self.guard_root), "diff", "--name-only", self.commit,
                     self.resume_plan["guard_commit"], "--", "apps/api/app", "apps/api/db",
                     "apps/api/requirements.lock", "apps/api/Dockerfile"]):
            raise DeployStopped("Guard-only recovery must retain the exact packaged application source and recipe")

    @staticmethod
    def check_resume_time(value: str) -> None:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0 or not -30 <= (
                datetime.now(timezone.utc) - stamp
            ).total_seconds() <= 900:
                raise ValueError("fresh UTC required")
        except (AttributeError, TypeError, ValueError) as exc:
            raise DeployStopped("Resume observation must be UTC, at most fifteen minutes old") from exc

    def load_resume_plan(self, current: list[dict]) -> None:
        raw = private_bytes(self.resume_path)
        plan = json.loads(raw)
        binding_keys = {"application_commit", "guard_commit", "application_version", "project",
                        "readiness_url", "images", "baseline_backends", "added_backend", "target_migrations"}
        if not isinstance(plan, dict) or set(plan) != binding_keys | {"schema_version", "kind", "files"} or (
            type(plan["schema_version"]) is not int or plan["schema_version"] != 1 or plan["kind"] != RESUME_KIND or
            plan["application_commit"] != self.commit or plan["application_version"] != "2.8.8" or
            not isinstance(plan["guard_commit"], str) or not re.fullmatch(r"[a-f0-9]{40}", plan["guard_commit"]) or
            plan["project"] != self.project_name or plan["readiness_url"] != self.readiness_url or
            plan["images"] != {name: value[1] for name, value in self.images.items()} or
            not isinstance(plan["files"], dict) or set(plan["files"]) != RESUME_FILES
        ):
            raise DeployStopped("Unsupported or mismatched explicit resume plan")
        self.resume_plan = plan
        self.plan_files[self.resume_path] = hashlib.sha256(raw).hexdigest()
        inputs = {name: self.read_bound_file(reference) for name, reference in plan["files"].items()}
        self.check_guard_source()
        selected = {"migration_plan": self.plan_path, "image_manifest": self.manifest,
                    "operator_evidence": self.evidence, "compose_override": self.override,
                    "private_environment": self.env_file}
        if any(path is None or Path(plan["files"][name]["path"]).resolve() != path.resolve() for name, path in selected.items()):
            raise DeployStopped("Resume evidence paths differ from selected runtime inputs")
        attempt, failed, observation, ci = [json.loads(inputs[name]) for name in (
            "failed_attempt", "failed_proof", "fresh_observation", "guard_ci"
        )]
        if any(not isinstance(value, dict) for value in (attempt, failed, observation, ci)):
            raise DeployStopped("Resume attempt, failure, observation and hosted CI must be objects")
        if failed.get("mode") != "deploy" or failed.get("commit") != self.commit or failed.get("passed") is not False or (
            type(failed.get("returncode")) is not int or failed["returncode"] == 0 or
            failed.get("wrapper_success_marker") is not False or attempt.get("commit") != self.commit or
            attempt.get("private_log") != plan["files"]["failed_log"]["path"] or
            failed.get("private_log") != attempt.get("private_log") or
            failed.get("log_sha256") != plan["files"]["failed_log"]["sha256"] or
            failed.get("started_at") != attempt.get("started_at")
        ):
            raise DeployStopped("Original failed deployment receipt/log binding is invalid")
        log = inputs["failed_log"].decode("utf-8")
        if "Migration service completed; verifying pinned addition " + REFERENCE_MIGRATION not in log or (
            "Application deployment passed." in log or "Recorded old backend " in log
        ):
            raise DeployStopped("Resume requires the recorded post-migration failure before any old removal")
        jobs = ci.get("jobs")
        if type(ci.get("schema_version")) is not int or ci["schema_version"] != 1 or ci.get("guard_commit") != plan["guard_commit"] or (
            type(ci.get("run_id")) is not int or ci["run_id"] <= 0 or
            ci.get("run_url") != "https://github.com/Ilia-Shakeri/Nerkhbaan/actions/runs/" + str(ci["run_id"]) or
            ci.get("status") != "completed" or ci.get("conclusion") != "success" or
            not isinstance(jobs, list) or len(jobs) != 15 or
            any(not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"] or
                row.get("status") != "completed" or row.get("conclusion") != "success" for row in jobs) or
            len({row["name"] for row in jobs}) != 15
        ):
            raise DeployStopped("Resume requires all fifteen hosted jobs on the exact guard commit")
        if type(observation.get("schema_version")) is not int or observation["schema_version"] != 1 or observation.get("kind") != RESUME_KIND or (
            observation.get("source") != "actual_target_read_only" or
            observation.get("binding") != {key: plan[key] for key in binding_keys} or
            observation.get("semantic_checks") != {name: True for name in SEMANTIC_CHECKS} or
            any(value is not True for value in observation.get("semantic_checks", {}).values())
        ):
            raise DeployStopped("Fresh resume observation lacks the exact target/semantic binding")
        self.resume_observation = observation
        self.check_resume_time(observation.get("checked_at"))
        baseline, baseline_roles = attempt.get("baseline_container_fingerprints"), attempt.get("baseline_container_roles")
        by_id = {item["Id"]: item for item in current}
        actual = {key: fingerprint(item) for key, item in by_id.items()}
        roles = {key: {"project": project(item), "service": service(item)} for key, item in by_id.items()}
        added = plan["added_backend"]
        if not isinstance(added, dict) or set(added) != {"id", "image", "config_hash"} or (
            not isinstance(added["id"], str) or not re.fullmatch(r"[a-f0-9]{64}", added["id"]) or
            added["image"] != self.images["backend"][1] or added["config_hash"] != self.backend_hash or
            not isinstance(baseline, dict) or not isinstance(baseline_roles, dict) or
            set(baseline_roles) != set(baseline) or set(actual) != set(baseline) | {added["id"]} or
            added["id"] in baseline or any(actual.get(key) != value for key, value in baseline.items()) or
            any(roles.get(key) != value for key, value in baseline_roles.items()) or
            roles.get(added["id"]) != {"project": self.project_name, "service": "backend"} or
            observation.get("baseline_container_fingerprints") != baseline or
            observation.get("current_container_fingerprints") != actual or
            observation.get("current_container_roles") != roles
        ):
            raise DeployStopped("Resume requires every original identity and exactly one recorded added backend")
        old = plan["baseline_backends"]
        if not isinstance(old, list) or len(old) != self.replicas or self.replicas != 2 or (
            len({row.get("id") for row in old if isinstance(row, dict)}) != 2 or
            any(not isinstance(row, dict) or set(row) != {"id", "image", "release_version"} or
                row.get("release_version") != "2.8.1" or row.get("id") not in baseline or
                baseline_roles.get(row.get("id")) != {"project": self.project_name, "service": "backend"} or
                by_id[row["id"]]["Image"] != row.get("image") for row in old)
        ):
            raise DeployStopped("Resume baseline must name the same two recorded old APIs")
        self.baseline_backends = {row["id"]: by_id[row["id"]] for row in old}
        if not self.desired_backend(by_id[added["id"]]) or not healthy(by_id[added["id"]], require_probe=True):
            raise DeployStopped("Recorded existing candidate must already have the reviewed image/configuration and health")
        canonical = hashlib.sha256(json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if observation.get("resolved_config_sha256") != canonical or observation.get("service_hashes") != self.service_hashes:
            raise DeployStopped("Resume resolved model differs from independently predicted configuration hashes")
        self.resume_attempt = attempt

    def validate_resume_probes(self) -> None:
        probes = self.resume_observation.get("probes")
        expected_ids = set(self.baseline_backends) | {self.resume_plan["added_backend"]["id"]}
        if not isinstance(probes, list) or len(probes) != 3 or any(not isinstance(row, dict) for row in probes) or {
            row.get("id") for row in probes
        } != expected_ids:
            raise DeployStopped("Resume observation needs all three exact API probes")
        for probe in probes:
            old = probe["id"] in self.baseline_backends
            self.validate_payload(probe.get("payload"), old=old, status=probe.get("status"))
            expected = self.plan["baseline_migrations"] if old else self.plan["target_migrations"]
            image = self.baseline_backends[probe["id"]]["Image"] if old else self.images["backend"][1]
            if probe.get("image") != image or probe.get("expected") != expected or probe.get("applied") != self.plan["target_migrations"] or (
                old and probe.get("migration_state") != self.old_migration_state() or
                not old and probe.get("migration_state", {}).get("current") is not True
            ):
                raise DeployStopped("Resume recorded API files/ledger/readiness exceed the pinned transition")

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
        if isinstance(plan, dict) and plan.get("kind") == COMMUNICATIONS_PLAN_KIND:
            self.load_communications_plan(plan, raw, expected, current)
            return
        keys = {"schema_version", "kind", "commit", "project", "readiness_url", "images",
                "baseline_backends", "baseline_migrations", "target_migrations", "evidence"}
        if not isinstance(plan, dict) or set(plan) != keys or type(plan["schema_version"]) is not int or (
            plan["schema_version"] != 1 or plan["kind"] != PLAN_KIND
        ):
            raise DeployStopped("Unsupported reviewed migration plan")
        baseline = plan["baseline_migrations"]
        if not isinstance(baseline, dict) or set(baseline) != BASELINE_MIGRATIONS or len(baseline) != 8:
            raise DeployStopped("Reviewed migration plan must retain the exact eight-migration baseline")
        applied = expected if self.resume_plan else baseline
        if expected != baseline | {REFERENCE_MIGRATION: REFERENCE_CHECKSUM} or (
            plan["target_migrations"] != expected or current.get("expected") != baseline or
            current.get("applied") != applied
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
        if self.resume_plan and (
            self.resume_plan["target_migrations"] != expected or
            self.resume_plan["baseline_backends"] != declared or
            self.resume_plan["files"]["restore_report"] != plan["evidence"] or
            self.resume_plan["files"]["restore_transcript"] != proof["transcript"]
        ):
            raise DeployStopped("Resume proof chain differs from the original pinned migration/restore")
        self.check_plan_files()

    def load_communications_plan(self, plan: dict, raw: bytes, expected: dict, current: dict) -> None:
        keys = {"schema_version", "kind", "application_version", "commit", "project", "readiness_url", "images",
                "baseline_backends", "baseline_migrations", "target_migrations", "evidence"}
        target = COMMUNICATIONS_BASELINE | {COMMUNICATIONS_MIGRATION: COMMUNICATIONS_CHECKSUM}
        if set(plan) != keys or type(plan.get("schema_version")) is not int or plan["schema_version"] != 1 or (
            plan.get("kind") != COMMUNICATIONS_PLAN_KIND or plan.get("application_version") != "2.8.13" or
            (self.root / "VERSION").read_text().strip() != "2.8.13" or self.resume_path is not None or
            self.resume_plan is not None or self.normal_resume_path is not None
        ):
            raise DeployStopped("Communications migration requires its own reviewed 2.8.13 plan without resume")
        if plan.get("baseline_migrations") != COMMUNICATIONS_BASELINE or expected != target or (
            plan.get("target_migrations") != target or current.get("expected") != COMMUNICATIONS_BASELINE or
            current.get("applied") != COMMUNICATIONS_BASELINE
        ):
            raise DeployStopped("Communications transition must preserve every pinned checksum in the exact nine-to-ten ledger")
        binding = {key: plan[key] for key in keys - {"schema_version", "kind", "evidence"}}
        if plan["commit"] != self.commit or plan["project"] != self.project_name or (
            plan["readiness_url"] != self.readiness_url or
            plan["images"] != {name: image_id for name, (_, image_id) in self.images.items()}
        ):
            raise DeployStopped("Communications migration target differs from the reviewed release")
        declared = plan["baseline_backends"]
        if not isinstance(declared, list) or len(declared) != self.replicas or any(
            not isinstance(row, dict) or set(row) != {"id", "image", "release_version"} or
            not isinstance(row["release_version"], str) or not re.fullmatch(r"\d+\.\d+\.\d+", row["release_version"])
            for row in declared
        ):
            raise DeployStopped("Communications baseline needs exact observed API IDs, images and versions")
        old_versions = {row["release_version"] for row in declared}
        actual = {item["Id"]: item["Image"] for item in self.baseline_backends.values()}
        if len(old_versions) != 1 or len({row["id"] for row in declared}) != self.replicas or (
            {row["id"]: row["image"] for row in declared} != actual or len(set(actual.values())) != 1 or
            tuple(map(int, next(iter(old_versions)).split("."))) >= (2, 8, 13)
        ):
            raise DeployStopped("Communications baseline differs from the observed running APIs")
        self.plan = plan
        self.plan_files[self.plan_path] = hashlib.sha256(raw).hexdigest()
        proof = json.loads(self.read_bound_file(plan["evidence"]))
        self.proof = proof
        if not isinstance(proof, dict) or set(proof) != {
            "schema_version", "kind", "checked_at", "release", "restore", "compatibility", "transcript"
        } or type(proof.get("schema_version")) is not int or proof["schema_version"] != 1 or (
            proof.get("kind") != COMMUNICATIONS_PLAN_KIND or proof.get("release") != binding
        ):
            raise DeployStopped("Communications restore proof differs from its exact reviewed plan")
        self.check_proof_time(proof.get("checked_at"))
        restore = proof["restore"]
        restore_keys = {"isolated", "source_database_container_id", "restore_database", "migration_command",
                        "migration_image", "baseline_migrations", "target_migrations", "existing_data_columns",
                        "existing_data_sha256_before", "existing_data_sha256_after", "schema_before", "schema_after",
                        "new_table_rows", "added_column_nondefault_rows", "data_fingerprint_scope"}
        if not isinstance(restore, dict) or set(restore) != restore_keys:
            raise DeployStopped("Communications restore proof needs the complete schema and data observations")
        digest = restore["existing_data_sha256_before"]
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) or (
            restore["existing_data_sha256_after"] != digest or restore["isolated"] is not True or
            restore["source_database_container_id"] != self.database_id or
            not isinstance(restore["restore_database"], str) or
            not re.fullmatch(r"[a-z0-9_]+_restore(?:_[a-z0-9_]+)?", restore["restore_database"]) or
            restore["migration_command"] != MIGRATION_COMMAND or restore["migration_image"] != self.images["migrate"][1] or
            restore["baseline_migrations"] != COMMUNICATIONS_BASELINE or restore["target_migrations"] != target or
            restore["data_fingerprint_scope"] != "all-public-tables-baseline-columns-except-schema-migrations-v1"
        ):
            raise DeployStopped("Communications restore must run the pinned packaged migrator on an isolated unchanged baseline")
        projection = validate_communications_schema(restore["schema_before"], restore["schema_after"])
        if restore["existing_data_columns"] != projection or restore["new_table_rows"] != {
            "public." + name: 0 for name in COMMUNICATIONS_COLUMNS
        } or any(type(value) is not int for value in restore["new_table_rows"].values()) or (
            restore["added_column_nondefault_rows"] != {"public.alerts.notify_voip": 0, "public.alerts.priority": 0} or
            any(type(value) is not int for value in restore["added_column_nondefault_rows"].values())
        ):
            raise DeployStopped("Communications restore must preserve every baseline projection and safe empty/default additions")
        compatibility = proof["compatibility"]
        if not isinstance(compatibility, dict) or set(compatibility) != {
            "old_image", "new_image", "old_release_version", "old_migration_state", "old_ready_status",
            "old_ready_payload", "new_ready_status", "new_ready_payload", "business_probes"
        } or compatibility.get("old_image") != next(iter(actual.values())) or (
            compatibility.get("new_image") != self.images["backend"][1] or
            compatibility.get("old_release_version") != next(iter(old_versions)) or
            compatibility.get("old_migration_state") != self.old_migration_state()
        ):
            raise DeployStopped("Communications compatibility proof differs from the observed old/new images")
        self.migrated = True
        try:
            self.validate_payload(compatibility["old_ready_payload"], old=True, status=compatibility["old_ready_status"])
            self.validate_payload(compatibility["new_ready_payload"], old=False, status=compatibility["new_ready_status"])
        finally:
            self.migrated = False
        probes = compatibility["business_probes"]
        if not isinstance(probes, list) or len(probes) != 2 or any(not isinstance(probe, dict) for probe in probes) or (
            {probe.get("path") for probe in probes} != {"/api/prices", "/api/instruments"} or
            any(type(probe.get("status")) is not int or probe["status"] != 200 or not isinstance(
                probe.get("body_sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", probe["body_sha256"]) for probe in probes)
        ):
            raise DeployStopped("Communications compatibility needs both old-image read-only business routes")
        self.read_bound_file(proof["transcript"])
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
        if self.resume_path is None and self.normal_resume_path is None and (
            len(backends) != self.replicas or any(not healthy(item, require_probe=True) for item in backends)
        ):
            raise DeployStopped("Backend baseline must match healthy requested replica count")
        if self.resume_path is not None and (len(backends) != 3 or any(not item["State"].get("Running") for item in backends)):
            raise DeployStopped("Explicit resume requires two running old APIs and one running recorded candidate")
        self.baseline_backends = {item["Id"]: item for item in backends}
        self.service_hashes = {}
        for name in ("backend", *self.targets):
            self.service_hashes[name] = self.resolved_service_hash(name)
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
        if self.resume_path is not None:
            self.load_resume_plan(current)
        if self.normal_resume_path is not None:
            self.load_normal_resume_plan(current)
        schema_baseline = next(item for item in self.baseline_backends.values() if item["State"].get("Running"))
        self.check_schema(schema_baseline)
        excluded = {"backend", *self.targets}
        self.protected = {
            item["Id"]: item for item in current
            if not (project(item) == self.project_name and service(item) in excluded)
        }
        self.check_protected()
        if self.normal_resume_plan:
            expected_protected = {
                key for key, role in self.normal_resume_observation["current_container_roles"].items()
                if not (role["project"] == self.project_name and role["service"] in excluded)
            }
            if len(self.protected) != 17 or set(self.protected) != expected_protected or self.plan is not None or self.resume_plan is not None:
                raise DeployStopped("Normal resume protected set or migration mode differs")
            self.check_images()
            self.check_retirement_pair()
            self.readiness(allow_old=True)
            return list(self.baseline_backends.values())
        if self.resume_plan:
            expected_protected = {key for key, row in self.resume_attempt["baseline_container_roles"].items()
                                  if not (row["project"] == self.project_name and row["service"] in excluded)}
            if set(self.protected) != expected_protected or self.plan is None:
                raise DeployStopped("Resume protected set differs from the original failed attempt")
            self.migrated = True
            self.validate_resume_probes()
            self.backend_health(self.replicas + 1, 1)
            return list(self.baseline_backends.values())
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
        if self.normal_resume_plan and self.normal_resume_plan["target_migrations"] != expected:
            raise DeployStopped("Normal resume must retain the exact packaged nine-migration ledger")
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
        if self.normal_resume_plan:
            self.finish_stopped_normal_retirement()
            print("Reviewed same-ledger stopped-old retirement complete; no migration run.", flush=True)
        elif not self.resume_plan:
            self.compose_run("run", "--rm", "--no-deps", "--pull", "never", "migrate")
            if self.plan:
                self.migrated = True
                addition = COMMUNICATIONS_MIGRATION if self.plan.get("kind") == COMMUNICATIONS_PLAN_KIND else REFERENCE_MIGRATION
                print(f"Migration service completed; verifying pinned addition {addition}, exact ledger "
                      "and old migration-only readiness.", flush=True)
            self.backend_health(self.replicas, 0)
        pending = [item for item in old if not self.desired_backend(item) and not (
            self.normal_resume_plan and item["Id"] == self.normal_resume_plan["stopped_backend"]["id"]
        )]
        if self.resume_plan:
            new_count = 1
            self.backend_health(self.replicas + 1, new_count)
            print("Reviewed existing candidate ready; retaining the already applied pinned ledger without a migration run.", flush=True)
            self.retire_backend(pending.pop(0), new_count)
        else:
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
            self.retire_backend(baseline, new_count)
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

    def retire_backend(self, baseline: dict, new_count: int) -> None:
        self.check_images()
        self.backend_health(self.replicas + 1, new_count)
        self.check_plan_files()
        self.check_protected()
        self.guard_old(baseline, running=True)
        self.run(["docker", "stop", "--time", "20", baseline["Id"]])
        self.retirement_new_count = new_count
        try:
            with self.retirement_budget():
                with self.retirement_step("pair_before_public"):
                    running = [item for item in self.backends() if item["State"].get("Running")]
                    if len(running) != self.replicas:
                        raise DeployStopped("Remaining backend health failed; no container removal")
                    pair_healthy = self.normal_pair_healthy(running) if getattr(self, "normal_resume_plan", None) else all(
                        self.backend_healthy(item) for item in running
                    )
                    if not pair_healthy:
                        raise DeployStopped("Remaining backend health failed; no container removal")
                with self.retirement_step("protected_before_public"):
                    self.check_protected()
                self.readiness(allow_old=any(item["Id"] in self.baseline_backends for item in running), retirement=True)
                with self.retirement_step("images_after_public"):
                    self.check_images()
                with self.retirement_step("pair_after_public"):
                    self.check_retirement_pair()
                with self.retirement_step("stopped_identity"):
                    self.guard_old(baseline, running=False)
                with self.retirement_step("old_remove"):
                    self.run(["docker", "rm", baseline["Id"]])
        finally:
            self.retirement_new_count = None
        print(f"Recorded old backend {baseline['Id']} removed after replacement readiness; "
              "remaining identities retained.", flush=True)
        self.backend_health(self.replicas, new_count)

    def finish_stopped_normal_retirement(self) -> None:
        self.retirement_new_count = 1
        try:
            with self.retirement_budget():
                with self.retirement_step("images_before_public"):
                    self.check_images()
                with self.retirement_step("protected_before_public"):
                    self.check_protected()
                with self.retirement_step("pair_before_public"):
                    self.check_retirement_pair()
                self.readiness(allow_old=True, retirement=True)
                with self.retirement_step("images_after_public"):
                    self.check_images()
                with self.retirement_step("protected_after_public"):
                    self.check_protected()
                with self.retirement_step("pair_after_public"):
                    self.check_retirement_pair()
                with self.retirement_step("stopped_identity"):
                    self.guard_old(self.normal_stopped, running=False)
                with self.retirement_step("snapshot_before_remove"):
                    observed = self.normal_resume_observation["current_container_fingerprints"]
                    if {item["Id"]: fingerprint(item) for item in self.containers()} != observed:
                        raise DeployStopped("Normal resume snapshot changed before stopped-old removal")
                with self.retirement_step("old_remove"):
                    self.run(["docker", "rm", self.normal_stopped["Id"]])
        finally:
            self.retirement_new_count = None
        print(f"Recorded old backend {self.normal_stopped['Id']} removed after replacement readiness; "
              "remaining identities retained.", flush=True)
        self.check_images()
        self.check_protected()
        remaining = {item["Id"]: fingerprint(item) for item in self.containers()}
        if remaining != {key: value for key, value in observed.items() if key != self.normal_stopped["Id"]}:
            raise DeployStopped("Normal resume identities changed after stopped-old removal")
        self.backend_health(self.replicas, 1)


def main() -> int:
    try:
        ApplicationDeploy(dict(os.environ)).deploy()
    except (DeployStopped, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"Deploy stopped: {exc}. Keep current replicas; review private logs before retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
