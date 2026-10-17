"""Current source permissions for collection, storage and application output."""
from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from ..config import settings

_APP_ACTIONS = frozenset({"collect", "store", "display", "history", "derive", "own_app_transport"})
_ACTIONS = _APP_ACTIONS | {"external_processing", "relay"}
_REVIEWED = "2026-10-17T00:00:00Z"
_EXPIRES = "2027-01-15T00:00:00Z"
_BUILTIN = {
    name: {
        "permissions": sorted(_APP_ACTIONS),
        "checked_at": _REVIEWED,
        "expires_at": _EXPIRES,
        "evidence_ref": "https://gold-api.com/terms",
        "hosts": ["api.gold-api.com"],
        "attribution": {"label": "Gold API", "url": "https://gold-api.com/"},
    }
    for name in ("gold_api_free_xau", "gold_api_free_xag", "gold_api_free_btc")
}


def enforced() -> bool:
    return bool(getattr(settings, "pricing_rights_enforced", True))


@lru_cache(maxsize=4)
def _read_manifest(path: str, modified: int, changed: int, inode: int, size: int) -> dict:
    if size > 262_144:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if (type(payload.get("schema_version")) is not int or payload["schema_version"] != 1
                or payload.get("environment") != "production"
                or not isinstance(payload.get("providers"), dict)):
            return {}
        return payload["providers"]
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def grants() -> dict:
    path = getattr(settings, "pricing_rights_manifest_path", None)
    if not path:
        return _BUILTIN
    try:
        selected = Path(path)
        if not selected.is_absolute():
            return {}
        stat = selected.stat()
        return _read_manifest(str(selected), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino, stat.st_size)
    except (OSError, ValueError, TypeError):
        return {}


def _time(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Permission times require a timezone")
    return parsed.astimezone(UTC)


def _grant(provider_id: str) -> dict | None:
    if not isinstance(provider_id, str) or not provider_id:
        return None
    grant = grants().get(provider_id)
    if not isinstance(grant, dict):
        return None
    try:
        now = datetime.now(UTC)
        checked, expires = _time(grant.get("checked_at")), _time(grant.get("expires_at"))
        ref = urlsplit(str(grant.get("evidence_ref", "")))
        actions = grant.get("permissions")
        if (not checked <= now < expires or (expires - checked).total_seconds() > 366 * 86400
                or ref.scheme != "https" or not ref.hostname or ref.username or ref.password
                or not isinstance(actions, list) or not actions
                or any(not isinstance(item, str) or item not in _ACTIONS for item in actions)):
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    return grant


def provider_allowed(provider_id: str, action: str = "display") -> bool:
    if action not in _ACTIONS:
        return False
    if not enforced():
        return True
    grant = _grant(provider_id)
    required = {action, "display"} if action == "history" else {action}
    return bool(grant and required <= set(grant["permissions"]))


def endpoint_allowed(provider_id: str, url: str) -> bool:
    if not enforced():
        return True
    grant = _grant(provider_id)
    try:
        target = urlsplit(url)
        hosts = grant.get("hosts") if grant else None
        return bool(grant and target.scheme == "https" and target.port in (None, 443)
                    and not target.username and not target.password
                    and isinstance(hosts, list) and hosts
                    and all(isinstance(host, str) and host for host in hosts)
                    and target.hostname in hosts)
    except (TypeError, ValueError):
        return False


def allowed_provider_ids(action: str = "display") -> tuple[str, ...]:
    return tuple(sorted(name for name in grants() if provider_allowed(name, action)))


def _leaves(summary: Mapping, depth: int = 0) -> set[str] | None:
    if depth > 6 or not isinstance(summary, Mapping):
        return None
    ids = summary.get("provider_ids")
    primary = summary.get("primary_provider_id")
    if "derived" in summary and type(summary["derived"]) is not bool:
        return None
    if (not isinstance(ids, list) or not 0 < len(ids) <= 64
            or any(not isinstance(item, str) or not item for item in ids)):
        return None
    derived = summary.get("derived") is True or (isinstance(primary, str) and primary.startswith("derived:"))
    if derived:
        if not isinstance(primary, str) or primary not in ids or any(not name.startswith("derived:") for name in ids):
            return None
        inputs = summary.get("inputs")
        if not isinstance(inputs, list) or not 0 < len(inputs) <= 16:
            return None
        result: set[str] = set()
        for item in inputs:
            if not isinstance(item, Mapping):
                return None
            leaf = _leaves(item.get("source_summary"), depth + 1)
            if not leaf:
                return None
            result.update(leaf)
        for field in ("candidate_provider_id", "previous_provider_id"):
            extra = summary.get(field)
            if extra is not None:
                if not isinstance(extra, str) or not extra or extra.startswith("derived:"):
                    return None
                result.add(extra)
        return result
    if primary is not None and (not isinstance(primary, str) or primary not in ids):
        return None
    if any(item.startswith("derived:") for item in ids):
        return None
    result = set(ids)
    for field in ("candidate_provider_id", "previous_provider_id"):
        extra = summary.get(field)
        if extra is not None:
            if not isinstance(extra, str) or not extra or extra.startswith("derived:"):
                return None
            result.add(extra)
    return result


def canonical_allowed(summary: Mapping, action: str = "display") -> bool:
    if action not in _ACTIONS:
        return False
    if not enforced():
        return True
    leaves = _leaves(summary)
    if not leaves:
        return False
    derived = summary.get("derived") is True or str(summary.get("primary_provider_id", "")).startswith("derived:")
    return all(provider_allowed(name, action) and (not derived or provider_allowed(name, "derive"))
               for name in leaves)


def attribution(summary: Mapping) -> list[dict[str, str]]:
    if not canonical_allowed(summary):
        return []
    result = []
    for name in sorted(_leaves(summary) or ()):
        value = (_grant(name) or {}).get("attribution")
        if isinstance(value, dict):
            label, url = value.get("label"), value.get("url")
            try:
                parsed = urlsplit(str(url))
                if isinstance(label, str) and label and parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
                    entry = {"label": label[:120], "url": url}
                    if entry not in result:
                        result.append(entry)
            except (ValueError, TypeError):
                pass
    return result


def stamp_summary(summary: dict) -> dict:
    """Record verified leaves for SQL aggregation; old unproved formulas stay hidden."""
    result = dict(summary)
    leaves = _leaves(result)
    if leaves and canonical_allowed(result, "store"):
        result["rights_provenance_version"] = 1
        result["rights_provider_ids"] = sorted(leaves)
    else:
        result.pop("rights_provenance_version", None)
        result.pop("rights_provider_ids", None)
    return result


def sql_filter(action: str = "history", column: str = "source_summary") -> tuple[str, dict]:
    """Filter source rows before bucket, baseline, LIMIT and DISTINCT selection."""
    if column not in {"source_summary", "c.source_summary", "cq.source_summary"}:
        raise ValueError("Unrecognised source-summary SQL column")
    if action not in _ACTIONS:
        raise ValueError("Unrecognised source permission action")
    if not enforced():
        return "TRUE", {}
    allowed = json.dumps(allowed_provider_ids(action))
    derive = json.dumps([name for name in allowed_provider_ids(action) if provider_allowed(name, "derive")])
    def is_derived(value):
        return f"(COALESCE({value}->>'derived','false') = 'true' OR COALESCE({value}->>'primary_provider_id','') LIKE 'derived:%')"

    def array(value, field):
        return f"CASE WHEN jsonb_typeof({value}->'{field}') = 'array' THEN {value}->'{field}' ELSE '[]'::jsonb END"

    node = "rights_node.summary"
    ids, inputs = array(node, "provider_ids"), array(node, "inputs")
    node_derived = is_derived(node)
    allowed_leaves = f"CASE WHEN {is_derived(column)} THEN CAST(:rights_derived_sources AS jsonb) ELSE CAST(:rights_allowed_sources AS jsonb) END"
    # Validate the same bounded tree as _leaves. Flattened stamps are not proof.
    clause = f"""NOT EXISTS (
      WITH RECURSIVE rights_nodes(summary, depth) AS (
        SELECT {column}, 0
        UNION ALL
        SELECT rights_input.value->'source_summary', rights_node.depth + 1
        FROM rights_nodes AS rights_node
        CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN rights_node.depth < 7 AND {node_derived}
            AND jsonb_array_length({inputs}) BETWEEN 1 AND 16
            THEN {inputs} ELSE '[]'::jsonb END
        ) AS rights_input(value)
      )
      SELECT 1 FROM rights_nodes AS rights_node
      WHERE jsonb_typeof({node}) IS DISTINCT FROM 'object'
        OR rights_node.depth > 6
        OR ({node}->'derived' IS NOT NULL AND jsonb_typeof({node}->'derived') <> 'boolean')
        OR jsonb_array_length({ids}) NOT BETWEEN 1 AND 64
        OR EXISTS (SELECT 1 FROM jsonb_array_elements({ids}) AS rights_id(value)
          WHERE jsonb_typeof(value) <> 'string' OR value #>> '{{}}' = '')
        OR (COALESCE({node}->'primary_provider_id','null'::jsonb) <> 'null'::jsonb
          AND (jsonb_typeof({node}->'primary_provider_id') <> 'string'
            OR NOT ({ids} ? ({node}->>'primary_provider_id'))))
        OR ({node_derived} AND (
          jsonb_typeof({node}->'primary_provider_id') IS DISTINCT FROM 'string'
          OR COALESCE({node}->>'primary_provider_id','') NOT LIKE 'derived:%'
          OR jsonb_array_length({inputs}) NOT BETWEEN 1 AND 16
          OR EXISTS (SELECT 1 FROM jsonb_array_elements({ids}) AS rights_id(value)
            WHERE value #>> '{{}}' NOT LIKE 'derived:%')))
        OR (NOT {node_derived} AND EXISTS (
          SELECT 1 FROM jsonb_array_elements({ids}) AS rights_id(value)
          WHERE value #>> '{{}}' LIKE 'derived:%'
            OR NOT ({allowed_leaves} ? (value #>> '{{}}'))))
        OR EXISTS (
          SELECT 1 FROM (VALUES ({node}->'candidate_provider_id'),
                                ({node}->'previous_provider_id')) AS rights_extra(value)
          WHERE value IS NOT NULL AND value <> 'null'::jsonb
            AND (jsonb_typeof(value) <> 'string' OR value #>> '{{}}' = ''
              OR value #>> '{{}}' LIKE 'derived:%'
              OR NOT ({allowed_leaves} ? (value #>> '{{}}'))))
    )"""
    return clause, {"rights_allowed_sources": allowed, "rights_derived_sources": derive}


def describe() -> dict:
    return {"enforced": enforced(), "approved_collect_sources": list(allowed_provider_ids("collect")),
            "approved_display_sources": list(allowed_provider_ids("display")),
            "approved_history_sources": list(allowed_provider_ids("history")),
            "manifest_configured": bool(getattr(settings, "pricing_rights_manifest_path", None))}


def revision() -> str:
    payload = {name: value for name in sorted(grants()) if (value := _grant(name)) is not None}
    encoded = json.dumps({"enforced": enforced(), "providers": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
