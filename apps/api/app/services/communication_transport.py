from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import queue
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

MAX_RESPONSE_BYTES = 32768
REQUEST_SECONDS = 12
DNS_SECONDS = 3
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_PHONE = re.compile(r"^\+[1-9][0-9]{7,14}$")
_METADATA = {"100.100.100.200", "169.254.169.254", "169.254.170.2", "fd00:ec2::254", "168.63.129.16", "147.75.207.207"}
_DNS_SLOTS = threading.BoundedSemaphore(4)


class TransportConfigurationError(ValueError):
    def __init__(self, code: str = "invalid_provider_configuration"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TransportResult:
    status: str
    provider_reference: str | None = None
    error_code: str | None = None
    provider_id: str = "none"

    @property
    def summary(self) -> dict:
        return {"provider_id": self.provider_id, "status": self.status,
                "accepted": self.status == "accepted", "delivered": False, "answered": False,
                "automatic_retry": False,
                "reference_hash": self.provider_reference, "error_code": self.error_code}


def _require(value, code="invalid_provider_configuration"):
    if not value:
        raise TransportConfigurationError(code)


def validate_provider_config(channel: str, provider_id: str, config: dict) -> dict:
    """Validate stored configuration without DNS, credentials, or a request."""
    _require(channel in {"sms", "voip"} and isinstance(config, dict))
    allowed = {"sms": {"none", "kavenegar"}, "voip": {"none", "asterisk_ari"}}
    _require(provider_id in allowed[channel])
    if provider_id == "none":
        _require(not config)
        return {}
    if provider_id == "kavenegar":
        _require(set(config) <= {"sender", "template_id"})
        sender, template = config.get("sender", ""), config.get("template_id", "")
        _require(isinstance(sender, str) and isinstance(template, str))
        _require(not sender or bool(re.fullmatch(r"[0-9]{3,20}", sender)))
        _require(not template or bool(_NAME.fullmatch(template)))
        _require(bool(sender))
    else:
        _require(set(config) <= {"endpoint", "trunk", "ari_app", "caller_id", "context", "extension"})
        _endpoint(config.get("endpoint", ""))
        trunk = config.get("trunk", "")
        _require(isinstance(trunk, str) and bool(_NAME.fullmatch(trunk)))
        app, context, extension = (config.get(key, "") for key in ("ari_app", "context", "extension"))
        _require(all(isinstance(value, str) for value in (app, context, extension)))
        _require((bool(app) and not context and not extension) or (not app and bool(context) and bool(extension)))
        _require(all(not value or bool(_NAME.fullmatch(value)) for value in (app, context, extension)))
        caller = config.get("caller_id", "")
        _require(isinstance(caller, str) and (not caller or bool(re.fullmatch(r"\+?[0-9]{3,20}", caller))))
    return dict(config)


def _endpoint(value: str):
    _require(isinstance(value, str) and len(value) <= 300 and not any(c.isspace() for c in value))
    try:
        parsed = urlsplit(value)
        port = parsed.port or 443
    except ValueError:
        raise TransportConfigurationError() from None
    _require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password)
    _require(parsed.path.rstrip("/") in {"", "/ari"} and not parsed.query and not parsed.fragment)
    _require(1 <= port <= 65535 and "%" not in parsed.hostname and "\\" not in value)
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii")
    except UnicodeError:
        raise TransportConfigurationError() from None
    return hostname, port


def _allowed_address(value: str, private_allowlist: str) -> str:
    try:
        address = ipaddress.ip_address(value)
        _require(not (address.is_loopback or address.is_link_local or address.is_multicast
                      or address.is_unspecified or address.is_reserved or str(address) in _METADATA))
        _require(not isinstance(address, ipaddress.IPv6Address) or address.ipv4_mapped is None)
        if not address.is_global:
            private_ranges = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
            _require(any(address in ipaddress.ip_network(net) for net in private_ranges
                         if ipaddress.ip_network(net).version == address.version))
            networks = [ipaddress.ip_network(item.strip(), strict=True)
                        for item in private_allowlist.split(",") if item.strip()]
            _require(any(address.version == net.version and address in net for net in networks))
        return str(address)
    except (ValueError, TypeError):
        raise TransportConfigurationError("provider_address_forbidden") from None


def resolve_addresses(host: str, port: int, private_allowlist: str = "") -> frozenset[str]:
    """One bounded lookup; reject mixed public/private DNS rather than selecting around it."""
    result = queue.Queue(maxsize=1)
    _require(_DNS_SLOTS.acquire(timeout=DNS_SECONDS), "provider_dns_unavailable")
    def resolve():
        try:
            result.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
        except Exception:
            result.put(None)
        finally:
            _DNS_SLOTS.release()
    try:
        threading.Thread(target=resolve, daemon=True).start()
    except Exception:
        _DNS_SLOTS.release()
        raise TransportConfigurationError("provider_dns_unavailable") from None
    try:
        records = result.get(timeout=DNS_SECONDS)
    except queue.Empty:
        raise TransportConfigurationError("provider_dns_unavailable") from None
    _require(records and len(records) <= 32, "provider_dns_unavailable")
    return frozenset(_allowed_address(row[4][0], private_allowlist) for row in records)


class _PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, addresses, deadline):
        self.addresses, self.deadline = addresses, deadline
        super().__init__(host, port, timeout=REQUEST_SECONDS, context=ssl.create_default_context())
        self.set_debuglevel(0)

    def connect(self):
        # The selected literal is used once. TLS still authenticates the configured hostname.
        address = min(self.addresses, key=lambda item: (ipaddress.ip_address(item).version != 4, int(ipaddress.ip_address(item))))
        plain = socket.create_connection((address, self.port), timeout=self._remaining())
        try:
            _require(str(ipaddress.ip_address(plain.getpeername()[0])) in self.addresses,
                     "provider_peer_changed")
            plain.settimeout(self._remaining())
            self.sock = self._context.wrap_socket(plain, server_hostname=self.host)
        except BaseException:
            plain.close()
            raise

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        return min(REQUEST_SECONDS, remaining)


def _request(host: str, port: int, addresses: frozenset[str], path: str,
             body: bytes, headers: dict) -> tuple[int, dict]:
    deadline = time.monotonic() + REQUEST_SECONDS
    connection = _PinnedConnection(host, port, addresses, deadline)
    def expire():
        sock = connection.sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        connection.close()
    timer = threading.Timer(REQUEST_SECONDS, expire)
    timer.daemon = True
    timer.start()
    try:
        connection.request("POST", path, body=body, headers=headers)
        if connection.sock:
            connection.sock.settimeout(connection._remaining())
        response = connection.getresponse()
        _require(not 300 <= response.status < 400, "provider_redirect_forbidden")
        raw = bytearray()
        while True:
            if connection.sock:
                connection.sock.settimeout(connection._remaining())
            chunk = response.read1(min(4096, MAX_RESPONSE_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            _require(len(raw) <= MAX_RESPONSE_BYTES, "provider_response_too_large")
        payload = json.loads(raw)
        _require(isinstance(payload, dict), "provider_response_invalid")
        return response.status, payload
    finally:
        timer.cancel()
        connection.close()


def send_transport(channel: str, provider: dict, secret: dict, *, phone: str,
                   message: str, delivery_key: str, template_token: str | None = None) -> TransportResult:
    """One paid request at most. Ambiguous results are terminal and never retried here."""
    provider_id = provider.get("provider_id", "none")
    try:
        _require(provider.get("enabled") is True and provider_id != "none", "provider_disabled")
        config = validate_provider_config(channel, provider_id, provider.get("config", {}))
        _require(isinstance(phone, str) and bool(_PHONE.fullmatch(phone)), "recipient_invalid")
        _require(isinstance(message, str) and 0 < len(message) <= 1000, "message_invalid")
        _require(isinstance(delivery_key, str) and 0 < len(delivery_key) <= 160, "delivery_key_invalid")
        key_hash = hashlib.sha256(delivery_key.encode()).hexdigest()
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        if provider_id == "kavenegar":
            api_key = secret.get("api_key", "")
            _require(isinstance(api_key, str) and bool(re.fullmatch(r"[A-Za-z0-9]{8,256}", api_key)), "secret_unavailable")
            host, port = "api.kavenegar.com", 443
            if config.get("template_id") and template_token is not None:
                path = f"/v1/{api_key}/verify/lookup.json"
                token = template_token
                _require(isinstance(token, str) and bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", token)), "template_token_invalid")
                values = {"receptor": phone, "template": config["template_id"], "token": token, "type": "sms"}
            else:
                path = f"/v1/{api_key}/sms/send.json"
                values = {"receptor": phone, "sender": config["sender"], "message": message}
            body = urlencode(values).encode("utf8")
            addresses = resolve_addresses(host, port)
        else:
            username, password = secret.get("username", ""), secret.get("password", "")
            _require(isinstance(username, str) and username and ":" not in username
                     and isinstance(password, str) and password
                     and len(username) <= 256 and len(password) <= 1024, "secret_unavailable")
            from ..config import settings
            host, port = _endpoint(config["endpoint"])
            addresses = resolve_addresses(host, port, settings.communications_private_pbx_allowlist)
            path = "/ari/channels/nerkhbaan-" + key_hash
            values = {"endpoint": f"PJSIP/{phone}@{config['trunk']}", "timeout": 20}
            if config.get("caller_id"):
                values["callerId"] = config["caller_id"]
            if config.get("ari_app"):
                values["app"] = config["ari_app"]
            else:
                values.update(context=config["context"], extension=config["extension"], priority=1)
            headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            headers["Content-Type"] = "application/json"
            body = json.dumps(values).encode("utf8")
    except Exception as exc:
        code = exc.code if isinstance(exc, TransportConfigurationError) else "provider_configuration_unavailable"
        return TransportResult("failed", error_code=code, provider_id=provider_id)
    try:
        status, payload = _request(host, port, addresses, path, body, headers)
        if not 200 <= status < 300:
            return TransportResult("failed" if 400 <= status < 500 and status not in {408, 409, 429} else "unknown",
                                   error_code="provider_rejected" if status < 500 else "provider_result_unknown", provider_id=provider_id)
        if provider_id == "kavenegar":
            returned = payload.get("return", {}).get("status")
            _require(type(returned) is int, "provider_response_invalid")
            if returned != 200:
                rejected = {400, 401, 403, 404, 405, 406, 407, 411, 412, 413, 414, 415, 416,
                            417, 418, 419, 420, 422, 424, 426, 427, 428, 429, 431, 432, 451, 501, 607}
                if returned in rejected:
                    return TransportResult("failed", error_code="provider_rejected", provider_id=provider_id)
                return TransportResult("unknown", error_code="provider_result_unknown", provider_id=provider_id)
            entries = payload.get("entries")
            _require(isinstance(entries, list) and len(entries) == 1, "provider_response_invalid")
            reference = entries[0].get("messageid")
            _require(type(reference) is int and reference > 0, "provider_response_invalid")
        else:
            reference = payload.get("id")
            _require(reference == "nerkhbaan-" + key_hash, "provider_response_invalid")
        reference_hash = hashlib.sha256(str(reference).encode()).hexdigest()
        return TransportResult("accepted", reference_hash, provider_id=provider_id)
    except Exception:
        # Do not expose URLs, numbers, response bodies, authentication, or exception text.
        return TransportResult("unknown", error_code="provider_result_unknown", provider_id=provider_id)
