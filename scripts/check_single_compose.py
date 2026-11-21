"""Render the separate initial-delivery plan with disposable credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def validate(plan: dict) -> dict:
    services = plan["services"]
    caps = {"postgres": 320, "redis": 48, "migrate": 192, "backend": 192,
            "web": 24, "price-feed-pull": 32, "db-backup": 48}
    if set(services) != set(caps):
        raise ValueError("Unexpected service graph")
    for name, cap in caps.items():
        service = services[name]
        expected = cap * 1024 * 1024
        if int(service["deploy"]["resources"]["limits"]["memory"]) != expected:
            raise ValueError("Unexpected memory limit: " + name)
        if int(service["memswap_limit"]) != expected:
            raise ValueError("Host swap must remain unavailable: " + name)
        if (service.get("ports") or service.get("privileged") or not service.get("read_only")
                or service.get("network_mode") or service.get("pid")
                or "ALL" not in service.get("cap_drop", [])
                or "no-new-privileges:true" not in service["security_opt"]
                or service.get("oom_score_adj") != 500 or service.get("pids_limit") != 96):
            raise ValueError("Unexpected host access: " + name)
        if set(service.get("cap_add", [])) - {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}:
            raise ValueError("Unexpected capability: " + name)
        if name != "postgres" and service.get("cap_add"):
            raise ValueError("Unexpected capability: " + name)
        if service["deploy"].get("replicas", 1) != 1:
            raise ValueError("Initial plan requires one instance: " + name)
        if service["logging"] != {"driver": "local", "options": {"max-file": "3", "max-size": "2m"}}:
            raise ValueError("Logs must remain bounded: " + name)
    env = services["backend"]["environment"]
    for name in ("AUTH_COOKIE_SECURE", "ADMIN_COOKIE_SECURE", "ADMIN_MFA_REQUIRED"):
        if env[name] != "true":
            raise ValueError("Required security setting changed: " + name)
    for name in ("AUTH_COOKIE_DOMAIN", "ADMIN_COOKIE_DOMAIN"):
        if env[name] != "":
            raise ValueError("Cookies must remain host-only")
    if not plan["networks"]["private"]["internal"]:
        raise ValueError("Database network must remain internal")
    if not plan["networks"]["gateway"]["external"]:
        raise ValueError("Existing gateway must be reused")
    for name in ("postgres", "redis", "migrate", "db-backup"):
        if set(services[name]["networks"]) != {"private"}:
            raise ValueError("Unexpected data-service network: " + name)
    for name in ("backend", "price-feed-pull"):
        if set(services[name]["networks"]) != {"private", "egress"}:
            raise ValueError("Unexpected application network: " + name)
    if set(services["web"]["networks"]) != {"private", "gateway"}:
        raise ValueError("Unexpected web network")
    for volume in plan["volumes"].values():
        opts = volume["driver_opts"]
        if volume["driver"] != "local" or opts["type"] != "none" or opts["o"] != "bind":
            raise ValueError("Bounded storage mounts required")
    return {"services": len(services), "steady_limit_mib": sum(caps.values()) - caps["migrate"],
            "api_instances": 1, "public_ports": 0, "deployment_accepted": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl", action="store_true")
    parser.add_argument("--initial", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    # Inside WSL use its own temporary filesystem and the same source checkout.
    if args.wsl:
        source = subprocess.check_output(["wsl", "-e", "wslpath", "-a", str(Path(__file__).resolve())], text=True).strip()
        subprocess.run(["wsl", "-e", "python3", source, *(["--initial"] if args.initial else [])], check=True)
        return
    values = {"OWNER_ID": "0" * 32, "POSTGRES_IMAGE": "postgres:test", "API_IMAGE": "api:test",
              "REDIS_IMAGE": "redis:test", "WEB_IMAGE": "web:test", "FEED_IMAGE": "feed:test",
              "PUBLIC_HOST": "public.example.test", "ADMIN_HOST": "admin.example.test",
              "PUBLIC_ORIGIN": "https://public.example.test", "ADMIN_ORIGIN": "https://admin.example.test",
              "GATEWAY_CIDR": "10.203.89.2/32", "WEB_PRIVATE_IPV4": "10.203.87.10",
              "PRIVATE_SUBNET": "10.203.87.0/24", "EGRESS_SUBNET": "10.203.88.0/24",
              "DATA_ROOT": "/unused-initial-data", "BACKUP_ROOT": "/unused-initial-backup",
              "GATEWAY_NETWORK": "unused-initial-gateway"}
    values["GATEWAY_IPV4"] = "10.203.89.2"
    with tempfile.TemporaryDirectory(prefix="nerkhbaan-single-compose-") as work:
        directory = Path(work)
        shutil.copyfile(root / "docker-compose.single.yaml", directory / "compose.yaml")
        files = ["-f", str(directory / "compose.yaml")]
        if args.initial:
            shutil.copyfile(root / "docker-compose.initial.yaml", directory / "initial.yaml")
            files += ["-f", str(directory / "initial.yaml")]
        (directory / "env").mkdir()
        for name in ("postgres", "backend", "feed", "backup"):
            (directory / "env" / (name + ".private.env")).write_text("DISPOSABLE_RENDER_ONLY=true\n")
        output = subprocess.check_output(["docker", "compose", *files,
                                          "config", "--format", "json"], env={**os.environ, **values}, text=True)
        plan = json.loads(output)
        if args.initial:
            edge = plan["services"].pop("edge")
            postgres = plan["services"]["postgres"]
            if (int(postgres["memswap_limit"]) != 512 * 1024**2
                    or int(postgres["deploy"]["resources"]["limits"]["memory"]) != 512 * 1024**2):
                raise ValueError("Unexpected dedicated database budget")
            postgres["memswap_limit"] = 320 * 1024**2
            postgres["deploy"]["resources"]["limits"]["memory"] = 320 * 1024**2
            if (edge["image"] != plan["services"]["web"]["image"]
                    or not edge["read_only"] or edge.get("cap_add")
                    or edge["cap_drop"] != ["ALL"]
                    or "no-new-privileges:true" not in edge["security_opt"]
                    or set(edge["networks"]) != {"gateway"}
                    or int(edge["memswap_limit"]) != 32 * 1024**2
                    or int(edge["deploy"]["resources"]["limits"]["memory"]) != 32 * 1024**2
                    or {(p["published"], p["target"]) for p in edge["ports"]} != {("80", 8081), ("443", 8443)}):
                raise ValueError("Unexpected initial TLS gateway")
            env = plan["services"]["backend"]["environment"]
            if env["ADMIN_FRONTEND_ORIGIN"] != env["PUBLIC_FRONTEND_ORIGIN"]:
                raise ValueError("Path-based panel must use the public origin")
        result = validate(plan)
        if args.initial:
            result.update(services=8, steady_limit_mib=888, public_ports=2)
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
