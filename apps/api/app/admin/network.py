from __future__ import annotations

import ipaddress

from fastapi import HTTPException, Request, status

from .config import get_admin_config


def admin_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    config = get_admin_config()
    trusted: set[ipaddress._BaseNetwork] = set()
    for item in config.trusted_proxy_ips.split(","):
        clean = item.strip()
        if not clean:
            continue
        try:
            trusted.add(ipaddress.ip_network(clean, strict=False))
        except ValueError:
            continue
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if any(peer_address in network for network in trusted):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded)) if forwarded else str(peer_address)
        except ValueError:
            return str(peer_address)
    return str(peer_address)


def enforce_admin_network(request: Request) -> None:
    config = get_admin_config()
    if not config.frontend_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    raw_allowlist = config.ip_allowlist
    networks: list[ipaddress._BaseNetwork] = []
    for item in raw_allowlist.split(","):
        clean = item.strip()
        if not clean:
            continue
        try:
            networks.append(ipaddress.ip_network(clean, strict=False))
        except ValueError:
            continue
    try:
        address = ipaddress.ip_address(admin_client_ip(request))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin network denied") from exc
    if config.private_network_only and not (address.is_private or address.is_loopback):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin network denied")
    if raw_allowlist and (not networks or not any(address in network for network in networks)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin network denied")
