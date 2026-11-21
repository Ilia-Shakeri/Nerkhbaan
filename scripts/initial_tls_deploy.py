"""Deploy the initial host certificate in place, preserving container bind mounts."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time
from datetime import UTC, datetime


def run(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Certificate operation failed: " + args[0])
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/nerkhbaan"))
    parser.add_argument("--owner", required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if (root / ".owner").read_text().strip() != args.owner:
        raise RuntimeError("Deployment owner mismatch")
    hostname = "nerkhbaan.ir"
    if args.lineage != Path("/etc/letsencrypt/live") / hostname:
        raise RuntimeError("Unexpected renewal lineage")
    cert, key = args.lineage / "fullchain.pem", args.lineage / "privkey.pem"
    run(["openssl", "x509", "-in", str(cert), "-noout", "-checkhost", hostname, "-checkend", "86400"])
    run(["openssl", "verify", "-CAfile", "/etc/ssl/certs/ca-certificates.crt", "-untrusted", str(cert), str(cert)])
    public_cert = run(["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"])
    public_key = run(["openssl", "pkey", "-in", str(key), "-pubout"])
    if public_cert != public_key:
        raise RuntimeError("Certificate key mismatch")
    targets = [root / "tls/fullchain.pem", root / "tls/privkey.pem"]
    for target in targets:
        if target.is_symlink() or target.stat().st_uid != 101 or target.stat().st_mode & 0o777 != 0o600:
            raise RuntimeError("Unexpected live certificate ownership")
    if args.check_only:
        print(json.dumps({"checked": True, "hostname": hostname, "live_changed": False}))
        return
    command = ["docker", "compose", "--env-file", str(root / "compose.private.env"), "-p", "nerkhbaan-initial", "-f", str(root / "docker-compose.single.yaml"), "-f", str(root / "docker-compose.initial.yaml")]
    edge = run(command + ["ps", "-q", "edge"]).decode().strip()
    info = json.loads(run(["docker", "inspect", edge]))[0]
    if info["Config"]["Labels"].get("io.nerkhbaan.initial-owner") != args.owner:
        raise RuntimeError("Gateway owner mismatch")
    old = [target.read_bytes() for target in targets]
    new = [cert.read_bytes(), key.read_bytes()]
    saved = root / "tls" / ("before-renewal-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    saved.mkdir(mode=0o700)
    for target, data in zip(targets, old):
        backup = saved / target.name
        backup.write_bytes(data)
        backup.chmod(0o600)

    def write(values: list[bytes]) -> None:
        for target, data in zip(targets, values):
            # Keep the same inode: the container mounts each file separately.
            descriptor = os.open(target, os.O_WRONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
                output.truncate()
                output.flush()
                os.fsync(output.fileno())

    def reload_services() -> None:
        run(["docker", "exec", edge, "nginx", "-c", "/etc/nginx/initial-edge.conf", "-t"])
        run(["nginx", "-t"])
        run(["docker", "exec", edge, "nginx", "-c", "/etc/nginx/initial-edge.conf", "-s", "reload"])
        run(["systemctl", "reload", "nginx"])

    try:
        write(new)
        reload_services()
        wanted = hashlib.sha256(run(["openssl", "x509", "-in", str(cert), "-outform", "DER"])).hexdigest()
        for attempt in range(15):
            seen = []
            for port in (443, 8443):
                with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
                    with ssl.create_default_context().wrap_socket(connection, server_hostname=hostname) as tls:
                        seen.append(hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest())
            if seen == [wanted, wanted]:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Both gateways must serve the renewed certificate")
    except BaseException:
        write(old)
        reload_services()
        raise
    receipt = {"renewed": True, "hostname": hostname, "certificate_sha256": wanted,
               "both_gateways_verified": True, "old_certificate_preserved": str(saved)}
    (root / "tls/renewal-receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
