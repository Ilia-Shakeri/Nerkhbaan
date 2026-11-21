"""Check the public demo without credentials, writes, or stored response bodies."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler

BASE = "https://nerkhbaan.ir"


class SameSiteRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != "https" or target.hostname != "nerkhbaan.ir" or target.port not in (None, 443):
            raise RuntimeError("Redirect outside the reviewed site")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main() -> None:
    opener = build_opener(SameSiteRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    rows = []
    pending = ["/", "/admin/", "/api/health/ready", "/api/prices"]
    while pending and len(rows) < 8:
        path = pending.pop(0)
        started = time.monotonic()
        try:
            with opener.open(Request(urljoin(BASE, path), headers={"Accept-Encoding": "identity"}), timeout=20) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise RuntimeError("Public response too large")
                if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) != len(body):
                    raise RuntimeError("Incomplete public response")
                if path.startswith("/api/"):
                    parsed = json.loads(body)
                    if path.endswith("/ready") and parsed.get("ready") is not True:
                        raise RuntimeError("Application not ready")
                elif path in ("/", "/admin/"):
                    for asset in re.findall(r'(?:src|href)=["\']([^"\']+\.(?:js|css))["\']', body.decode("utf8"))[:2]:
                        url = urlsplit(urljoin(BASE, asset))
                        if url.scheme == "https" and url.hostname == "nerkhbaan.ir":
                            pending.append(url.path)
                rows.append({"path": path, "status": response.status, "bytes": len(body),
                             "sha256": hashlib.sha256(body).hexdigest(), "seconds": time.monotonic() - started})
        except Exception as error:
            rows.append({"path": path, "error_type": type(error).__name__, "seconds": time.monotonic() - started})
    result = {"passed": len(rows) >= 4 and all(row.get("status") == 200 for row in rows),
              "credentials_used": False, "response_bodies_stored": False, "checks": rows}
    Path("initial-public-network-proof.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
