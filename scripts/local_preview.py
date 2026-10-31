"""Manage an owned local review stack without reading production configuration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import uuid

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / ".local-preview"
API_PORT, WEB_PORT, DB_PORT = 43187, 43188, 55449
ORIGIN = f"http://127.0.0.1:{WEB_PORT}"
OWNER = "nerkhbaan-local-preview-v1"


def base_environment():
    keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "PROGRAMDATA", "TEMP", "TMP", "WSLENV", "HOMEDRIVE", "HOMEPATH"}
    result = {k: v for k, v in os.environ.items() if k.upper() in keep}
    result["PYTHONUTF8"] = "1"
    return result


def private_home():
    HOME.mkdir(exist_ok=True)
    if os.name == "nt":
        sid = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True).strip().split(",")[-1].strip('"')
        r = subprocess.run(["icacls", str(HOME), "/inheritance:r", "/grant:r",
                            f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"], capture_output=True)
        if r.returncode:
            raise RuntimeError("Cannot protect the private local preview directory")
    else:
        HOME.chmod(0o700)


def config():
    private_home()
    file = HOME / "settings.private.json"
    if not file.exists():
        value = {"owner": OWNER, "workspace": str(ROOT), "id": uuid.uuid4().hex,
                 "password": secrets.token_urlsafe(32), "jwt": secrets.token_urlsafe(48)}
        with file.open("x", encoding="utf8") as stream:
            json.dump(value, stream)
    value = json.loads(file.read_text(encoding="utf8"))
    if value.get("owner") != OWNER or value.get("workspace") != str(ROOT):
        raise RuntimeError("Local preview directory belongs to another workspace")
    if (not isinstance(value.get("id"), str) or not re.fullmatch(r"[0-9a-f]{32}", value["id"])
            or any(not isinstance(value.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,}", value[key])
                   for key in ("password", "jwt"))):
        raise RuntimeError("Invalid private preview configuration; refusing to use it")
    return value


def docker(*args, check=True, timeout=45):
    prefix = ["wsl", "-e", "docker"] if os.name == "nt" else ["docker"]
    result = subprocess.run([*prefix, *args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        (HOME / "docker-error.private.log").write_text(result.stdout + result.stderr, encoding="utf8")
        raise RuntimeError("Local Docker operation failed; see .local-preview/docker-error.private.log")
    return result


def database_url(value):
    return f"postgresql+psycopg://preview:{value['password']}@127.0.0.1:{DB_PORT}/nerkhbaan_browser_preview"


def preview_environment(value):
    env = base_environment()
    env.update({"NERKHBAAN_LOCAL_PREVIEW": "1", "NERKHBAAN_BROWSER_SCHEMA": "browser_fixture_" + value["id"],
                "TEST_DATABASE_URL": database_url(value), "BROWSER_TEST_JWT_SECRET": value["jwt"],
                "BROWSER_TEST_PUBLIC_ORIGIN": ORIGIN, "BROWSER_TEST_ADMIN_ORIGIN": ORIGIN,
                "LOCAL_PREVIEW_WEB_ORIGIN": ORIGIN, "BACKGROUND_TASKS_ENABLED": "false",
                "REDIS_URL": "", "JWT_SECRET_KEY": value["jwt"], "PRICING_REQUIRE_PROVIDER_KEYS": "true",
                "AUTH_COOKIE_NAME": "nerkhbaan_local_session", "AUTH_REFRESH_COOKIE_NAME": "nerkhbaan_local_refresh",
                "VITE_API_URL": f"http://127.0.0.1:{API_PORT}", "VITE_LOCAL_PREVIEW": "true",
                "VITE_VAPID_PUBLIC_KEY": ""})
    return env


def wait_for(predicate, timeout=75):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(.5)
    raise RuntimeError("Local preview did not become ready; inspect .local-preview logs")


def api_ready():
    with urlopen(f"http://127.0.0.1:{API_PORT}/__preview__/health", timeout=2) as response:
        return json.load(response).get("mode") == "local-preview"


def assert_port_free(port):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def owned_container(name):
    row = json.loads(docker("inspect", name).stdout)[0]
    if row["Config"].get("Labels", {}).get("nerkhbaan.local-preview") != OWNER:
        raise RuntimeError("Refusing to change an unowned container")
    return row


def serve():
    value = config()
    lock = HOME / "worker.lock"
    with lock.open("x", encoding="utf8") as stream:
        stream.write(str(os.getpid()))
    children, streams = [], []
    name = "nerkhbaan-local-preview-" + value["id"][:12]
    volume = name + "-data"
    started_db = False
    try:
        for port in [API_PORT, WEB_PORT]:
            assert_port_free(port)
        image = "postgres:17-alpine"
        docker("image", "inspect", image)
        old = docker("inspect", name, check=False)
        if old.returncode == 0:
            row = owned_container(name)
            if not row["State"]["Running"]:
                docker("start", row["Id"])
            started_db = True
        else:
            assert_port_free(DB_PORT)
            existing = docker("volume", "inspect", volume, check=False)
            if existing.returncode == 0:
                if json.loads(existing.stdout)[0].get("Labels", {}).get("nerkhbaan.local-preview") != OWNER:
                    raise RuntimeError("Refusing an unowned data volume")
            else:
                docker("volume", "create", "--label", "nerkhbaan.local-preview=" + OWNER, volume)
            pg_env = HOME / "postgres.private.env"
            pg_env.write_text("POSTGRES_USER=preview\nPOSTGRES_DB=nerkhbaan_browser_preview\nPOSTGRES_PASSWORD=" + value["password"] + "\n", encoding="utf8")
            env_file = "/mnt/" + pg_env.drive[0].lower() + pg_env.as_posix()[2:] if os.name == "nt" else str(pg_env)
            docker("run", "-d", "--pull=never", "--name", name, "--label", "nerkhbaan.local-preview=" + OWNER,
                   "-p", f"127.0.0.1:{DB_PORT}:5432", "--env-file", env_file,
                   "--mount", f"type=volume,source={volume},target=/var/lib/postgresql/data", image)
            started_db = True
        if os.name == "nt":
            # Keep the subsystem alive while the Windows API uses its database.
            children.append(subprocess.Popen(["wsl", "-e", "docker", "wait", name], stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW))
        import psycopg
        def database_ready():
            with psycopg.connect(database_url(value).replace("postgresql+psycopg:", "postgresql:"), connect_timeout=2) as db:
                return db.execute("SELECT 1").fetchone()[0] == 1
        wait_for(database_ready)
        env = preview_environment(value)
        cwd = HOME / "runtime" / "process"
        cwd.mkdir(parents=True, exist_ok=True)
        if (cwd / "../../.env").resolve().exists():
            raise RuntimeError("Preview refuses an inherited dotenv file")
        api_log, web_log = (HOME / "api.private.log").open("a", encoding="utf8"), (HOME / "web.log").open("a", encoding="utf8")
        streams.extend([api_log, web_log])
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "local_preview_server:app", "--app-dir",
                                str(ROOT / "apps/api/scripts"), "--host", "127.0.0.1", "--port", str(API_PORT)],
                               cwd=cwd, env=env, stdout=api_log, stderr=subprocess.STDOUT, creationflags=flags)
        children.append(api)
        wait_for(api_ready)
        if os.name == "nt":
            command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f'npm.cmd run dev --workspace=nerkhbaan-web -- --host 127.0.0.1 --port {WEB_PORT} --strictPort']
        else:
            command = ["npm", "run", "dev", "--workspace=nerkhbaan-web", "--", "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"]
        web = subprocess.Popen(command, cwd=ROOT, env=env, stdout=web_log, stderr=subprocess.STDOUT, creationflags=flags)
        children.append(web)
        def web_ready():
            with urlopen(ORIGIN + "/auth", timeout=2) as response:
                return response.status == 200
        wait_for(web_ready)
        (HOME / "running.json").write_text(json.dumps({"owner": OWNER, "id": value["id"], "url": ORIGIN,
            "worker_pid": os.getpid(), "api_pid": api.pid, "web_pid": web.pid, "container": name}), encoding="utf8")
        while not (HOME / "stop.request").exists():
            if api.poll() is not None or web.poll() is not None:
                raise RuntimeError("A local preview process stopped; data volume preserved")
            time.sleep(.5)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
                else:
                    child.terminate()
        if started_db:
            row = owned_container(name)
            docker("stop", row["Id"], check=False)
        for stream in streams:
            stream.close()
        lock.unlink(missing_ok=True)
        (HOME / "running.json").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "serve", "stop", "status"])
    action = parser.parse_args().action
    if action == "serve":
        serve()
        return
    config()
    if action == "stop":
        (HOME / "stop.request").touch()
        wait_for(lambda: not (HOME / "worker.lock").exists(), timeout=45)
        print("Local preview stopped; database data is preserved.")
    elif action == "status":
        if not (HOME / "running.json").exists():
            print("Local preview is stopped.")
        elif api_ready():
            with urlopen(ORIGIN + "/auth", timeout=2) as response:
                if response.status != 200:
                    raise RuntimeError("Local website is not ready")
            print(ORIGIN)
        else:
            raise RuntimeError("Local preview receipt exists but the API is not ready")
    else:
        if (HOME / "worker.lock").exists():
            if (HOME / "running.json").exists() and api_ready():
                print(ORIGIN)
                return
            raise RuntimeError("A preview worker or stale lock exists; inspect .local-preview before starting again")
        (HOME / "stop.request").unlink(missing_ok=True)
        with (HOME / "supervisor.private.log").open("a", encoding="utf8") as stream:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve"], cwd=ROOT,
                stdout=stream, stderr=subprocess.STDOUT,
                creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
        wait_for(lambda: (HOME / "running.json").exists(), timeout=120)
        print(ORIGIN)


if __name__ == "__main__":
    main()
