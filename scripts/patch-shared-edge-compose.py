from __future__ import annotations

import shutil
import sys
from pathlib import Path


compose_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/target/compose.yml")
backup_path = compose_path.with_name("compose.yml.pre-nerkhbaan")

source = compose_path.read_text(encoding="utf-8")

if "target: /etc/nginx/conf.d/nerkhbaan.conf" in source:
    required = (
        "target: /etc/nginx/nerkhbaan-tls/fullchain.pem",
        "target: /etc/nginx/nerkhbaan-tls/privkey.pem",
        "      - nerkhbaan\n    healthcheck:",
        "name: nerkhbaan_nerkhbaan-network",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise RuntimeError(f"incomplete shared edge compose patch: {missing}")
    print("shared edge compose patch verified")
    raise SystemExit(0)

mount_anchor = """      - type: bind
        source: ${DOLPHIN_TLS_KEY_PATH:?DOLPHIN_TLS_KEY_PATH must name the approved private key file}
        target: /etc/nginx/tls/privkey.pem
        read_only: true
"""
mount_addition = mount_anchor + """      - type: bind
        source: ./nginx/nerkhbaan.conf
        target: /etc/nginx/conf.d/nerkhbaan.conf
        read_only: true
      - type: bind
        source: ./secrets/nerkhbaan/fullchain.pem
        target: /etc/nginx/nerkhbaan-tls/fullchain.pem
        read_only: true
      - type: bind
        source: ./secrets/nerkhbaan/privkey.pem
        target: /etc/nginx/nerkhbaan-tls/privkey.pem
        read_only: true
"""
network_anchor = """    networks:
      - frontend
    healthcheck:
"""
network_addition = """    networks:
      - frontend
      - nerkhbaan
    healthcheck:
"""
definition_anchor = """networks:
  backend:
    internal: true
  frontend: {}
"""
definition_addition = definition_anchor + """  nerkhbaan:
    external: true
    name: nerkhbaan_nerkhbaan-network
"""

for needle in (mount_anchor, network_anchor, definition_anchor):
    if source.count(needle) != 1:
        raise RuntimeError(f"expected one compose anchor, found {source.count(needle)}")

patched = source.replace(mount_anchor, mount_addition, 1)
patched = patched.replace(network_anchor, network_addition, 1)
patched = patched.replace(definition_anchor, definition_addition, 1)

if not backup_path.exists():
    shutil.copy2(compose_path, backup_path)
compose_path.write_text(patched, encoding="utf-8")
print("shared edge mounts and network added")
