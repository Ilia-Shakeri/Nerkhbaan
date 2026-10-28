from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from . import source_rights
from .parser import ParsedTelegramQuote, message_hash, normalize_channel_id, normalize_text, parse_message, parser_policy_version

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("telegram_worker")


class SourceRightsRevoked(RuntimeError):
    pass


def _require_source_rights(source: dict[str, Any]) -> None:
    if not source_rights.source_allowed(source.get("id")):
        raise SourceRightsRevoked("Source collection or storage permission is absent")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _database_url() -> str:
    return require_env("DATABASE_URL").replace("postgresql+psycopg://", "postgresql://", 1)


def _connect():
    return psycopg.connect(_database_url(), row_factory=dict_row, connect_timeout=10,
                           options="-c statement_timeout=10000 -c lock_timeout=3000")


def _source_for(cursor: psycopg.Cursor, channel_id: str, username: str | None) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT * FROM telegram_sources
        WHERE enabled = TRUE AND channel_id = %s
        LIMIT 1
        """,
        (channel_id,),
    )
    return cursor.fetchone()


def _eligible_sources() -> list[dict[str, Any]]:
    source_ids = source_rights.allowed_source_ids()
    if not source_ids:
        return []
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM telegram_sources "
                "WHERE enabled = TRUE AND id = ANY(%s)",
                (list(source_ids),),
            )
            return [row for row in cursor.fetchall() if source_rights.source_allowed(row["id"])]


def _store_parse_result(
    cursor: psycopg.Cursor,
    source: dict[str, Any],
    telegram_message_id: int,
    quote: ParsedTelegramQuote,
    identity_key: str,
) -> None:
    _require_source_rights(source)
    provider_quote_id: int | None = None
    if quote.validation_status == "accepted" and quote.instrument_id and quote.price is not None:
        cursor.execute(
            """
            INSERT INTO provider_quotes (
                instrument_id, provider_id, source_type, price, currency, weight_unit, purity,
                observed_at, received_at, parser_version, validation_status, confidence_score,
                is_direct, is_derived, is_suspicious, metadata, persistence_status,
                idempotency_key, quote_role
            )
            SELECT
                %s, %s, 'telegram', %s, %s, %s, %s,
                message_date, now(), %s, 'accepted', %s,
                TRUE, FALSE, FALSE, %s::jsonb, 'persisted', %s, %s
            FROM telegram_messages WHERE id = %s
            ON CONFLICT (idempotency_key, observed_at) DO NOTHING
            RETURNING id
            """,
            (
                quote.instrument_id,
                f"telegram:{source['id']}",
                quote.price,
                quote.currency,
                quote.weight_unit,
                quote.purity,
                parser_policy_version(source),
                quote.confidence_score,
                json.dumps(
                    {
                        "telegram_source_id": source["id"],
                        "source_role": source["role"],
                        "trust_score": str(source["trust_score"]),
                        "requires_multiple_sources": source["requires_multiple_sources"],
                        "origin_identity": source.get("_origin_identity"),
                    }
                ),
                identity_key,
                source["role"],
                telegram_message_id,
            ),
        )
        inserted = cursor.fetchone()
        provider_quote_id = inserted["id"] if inserted else None

    _require_source_rights(source)
    cursor.execute(
        """
        INSERT INTO telegram_parse_results (
            telegram_message_id, instrument_id, parsed_price, currency, weight_unit, purity,
            parser_version, confidence_score, validation_status, rejection_reason, provider_quote_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            telegram_message_id,
            quote.instrument_id,
            quote.price,
            quote.currency,
            quote.weight_unit,
            quote.purity,
            parser_policy_version(source),
            quote.confidence_score,
            quote.validation_status,
            quote.rejection_reason,
            provider_quote_id,
        ),
    )
    _require_source_rights(source)


def _invalidate_canonical(cursor, message_row_id: int) -> None:
    cursor.execute(
        """UPDATE canonical_quotes canonical
        SET status = 'stale', valid_until = LEAST(valid_until, now()),
            stale_at = LEAST(stale_at, now()), expires_at = LEAST(expires_at, now()),
            decision_reason = 'telegram_message_changed'
        FROM telegram_parse_results parsed
        WHERE parsed.telegram_message_id = %s AND parsed.provider_quote_id IS NOT NULL
          AND (canonical.primary_quote_id = parsed.provider_quote_id
               OR canonical.verification_quote_ids @> jsonb_build_array(parsed.provider_quote_id))""",
        (message_row_id,),
    )


def reconcile_ids(peer_id: str, limit: int = 200) -> list[int]:
    """Only fresh, already stored messages within this exact allowed peer."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            source = _source_for(cursor, peer_id, None)
            if not source or not source_rights.source_allowed(source["id"], "collect", "store", "history"):
                return []
            cursor.execute(
                """SELECT message_id FROM telegram_messages m
                WHERE m.source_id = %s AND m.channel_id = %s
                  AND m.message_date >= now() - make_interval(secs => %s)
                  AND m.message_id ~ '^[1-9][0-9]{0,9}$'
                  AND NOT EXISTS (SELECT 1 FROM telegram_parse_results p
                      WHERE p.telegram_message_id = m.id AND p.rejection_reason = 'message_deleted')
                ORDER BY m.message_date DESC LIMIT %s""",
                (source["id"], peer_id, source["maximum_message_age_seconds"], min(max(limit, 1), 500)),
            )
            return [int(row["message_id"]) for row in cursor.fetchall()]


def has_group_history(peer_id: str) -> bool:
    with _connect() as connection:
        with connection.cursor() as cursor:
            source = _source_for(cursor, peer_id, None)
            if not source:
                return False
            _require_source_rights(source)
            cursor.execute("SELECT EXISTS(SELECT 1 FROM telegram_messages WHERE channel_id = %s) AS present", (peer_id,))
            return bool(cursor.fetchone()["present"])


def delete_messages(peer_id: str, ids) -> str:
    if not source_rights.allowed_source_ids():
        return "rejected_rights"
    selected = sorted({int(value) for value in ids if type(value) is int and 0 < value <= 2**31-1})
    if len(selected) > 1000:
        raise ValueError("Deletion event exceeds its bound")
    try:
        with _connect() as connection:
            with connection.cursor() as cursor:
                source = _source_for(cursor, peer_id, None)
                if not source:
                    return "rejected_source"
                _require_source_rights(source)
                for message_id in selected:
                    _require_source_rights(source)
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                                   (f"telegram-message:{peer_id}:{message_id}",))
                    cursor.execute(
                        """INSERT INTO telegram_messages
                        (source_id, channel_id, chat_id, message_id, message_date, message_hash)
                        VALUES (%s, %s, %s, %s, now(), %s)
                        ON CONFLICT (channel_id, message_id) DO UPDATE SET sanitized_text = NULL
                        RETURNING id""",
                        (source["id"], peer_id, peer_id, str(message_id), message_hash("deleted")),
                    )
                    row_id = cursor.fetchone()["id"]
                    _require_source_rights(source)
                    _invalidate_canonical(cursor, row_id)
                    cursor.execute(
                        """UPDATE provider_quotes SET validation_status = 'rejected'
                        WHERE id IN (SELECT provider_quote_id FROM telegram_parse_results
                          WHERE telegram_message_id = %s AND provider_quote_id IS NOT NULL)""", (row_id,))
                    cursor.execute(
                        "UPDATE telegram_parse_results SET validation_status = 'rejected', "
                        "rejection_reason = 'message_deleted' WHERE telegram_message_id = %s", (row_id,))
                    cursor.execute(
                        """INSERT INTO telegram_parse_results
                        (telegram_message_id, parser_version, confidence_score, validation_status, rejection_reason)
                        SELECT %s, 'deleted-1', 0, 'rejected', 'message_deleted'
                        WHERE NOT EXISTS (SELECT 1 FROM telegram_parse_results WHERE telegram_message_id = %s)""",
                        (row_id, row_id),
                    )
                _require_source_rights(source)
        return "deleted"
    except SourceRightsRevoked:
        return "rejected_rights"


def _store_message(
    *,
    channel_id: str,
    username: str | None,
    chat_id: str,
    telegram_message_id: str,
    message_date: datetime,
    edited_at: datetime | None,
    text: str,
    source_type: str = "channel",
    origin_identity: str | None = None,
) -> str:
    channel_id = normalize_channel_id(channel_id, source_type=source_type)
    with _connect() as connection:
        with connection.cursor() as cursor:
            source = _source_for(cursor, channel_id, username)
            if not source:
                return "rejected_source"
            _require_source_rights(source)
            if source.get("source_type", "channel") != source_type:
                return "rejected_source"
            source["_origin_identity"] = origin_identity
            if message_date.tzinfo is None or message_date.utcoffset() is None:
                return "rejected_timestamp"
            # Multiple event/recovery writers must never interleave revisions.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           (f"telegram-message:{channel_id}:{telegram_message_id}",))
            digest = message_hash(text)

            now = datetime.now(UTC)
            maximum_age = int(source["maximum_message_age_seconds"])
            if message_date.tzinfo is None:
                message_date = message_date.replace(tzinfo=UTC)
            age_seconds = max(0, int((now - message_date).total_seconds()))

            cursor.execute(
                "SELECT id, message_hash, message_date, edited_at, "
                "EXISTS (SELECT 1 FROM telegram_parse_results p WHERE p.telegram_message_id = telegram_messages.id "
                "AND p.rejection_reason = 'message_deleted') AS deleted "
                ", EXISTS (SELECT 1 FROM telegram_parse_results p WHERE p.telegram_message_id = telegram_messages.id "
                "AND p.parser_version = %s) AS parser_policy_current "
                "FROM telegram_messages WHERE channel_id = %s AND message_id = %s",
                (parser_policy_version(source), channel_id, telegram_message_id),
            )
            existing = cursor.fetchone()
            if existing and existing.get("deleted"):
                return "deleted"
            revision = edited_at or message_date
            previous = (existing.get("edited_at") or existing.get("message_date")) if existing else None
            if revision.tzinfo is None:
                return "rejected_timestamp"
            if revision > now + timedelta(minutes=5):
                return "rejected_timestamp"
            if (existing and existing.get("message_date") and existing["message_hash"] != digest
                    and existing["message_date"] != message_date):
                return "rejected_message_clock"
            if previous and revision < previous:
                return "superseded_event"
            if previous and revision == previous and existing["message_hash"] != digest:
                return "conflicting_revision"
            if existing and existing["message_hash"] == digest and existing.get("parser_policy_current", True):
                if edited_at and (previous is None or edited_at > previous):
                    cursor.execute("UPDATE telegram_messages SET edited_at = %s WHERE id = %s", (edited_at, existing["id"]))
                _require_source_rights(source)
                return "duplicate"

            _require_source_rights(source)
            keep_text = os.getenv("TELEGRAM_STORE_SANITIZED_TEXT", "false").lower() == "true"
            sanitized = normalize_text(text)[:4000] if keep_text else None
            if existing:
                _invalidate_canonical(cursor, existing["id"])
                _require_source_rights(source)
                cursor.execute(
                    """
                    UPDATE provider_quotes SET validation_status = 'superseded_edit'
                    WHERE id IN (
                        SELECT provider_quote_id FROM telegram_parse_results
                        WHERE telegram_message_id = %s AND provider_quote_id IS NOT NULL
                    )
                    """,
                    (existing["id"],),
                )
                _require_source_rights(source)
                cursor.execute("DELETE FROM telegram_parse_results WHERE telegram_message_id = %s", (existing["id"],))
                _require_source_rights(source)
                cursor.execute(
                    """
                    UPDATE telegram_messages
                    SET source_id = %s, chat_id = %s, message_date = %s, edited_at = %s,
                        message_hash = %s, sanitized_text = %s, received_at = now()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (source["id"], chat_id, message_date, edited_at, digest, sanitized, existing["id"]),
                )
            else:
                _require_source_rights(source)
                cursor.execute(
                    """
                    INSERT INTO telegram_messages (
                        source_id, channel_id, chat_id, message_id, message_date,
                        edited_at, message_hash, sanitized_text
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (source["id"], channel_id, chat_id, telegram_message_id, message_date, edited_at, digest, sanitized),
                )
            stored = cursor.fetchone()
            row_id = stored["id"]

            _require_source_rights(source)
            allowed = set(source["allowed_instruments"] or [])
            if message_date > now + timedelta(minutes=5):
                results = [ParsedTelegramQuote(None, None, None, None, None, Decimal("0"), "rejected", "message_in_future")]
            elif age_seconds > maximum_age:
                results = [
                    ParsedTelegramQuote(
                        None, None, None, None, None, Decimal("0"), "rejected", "message_too_old"
                    )
                ]
            else:
                results = parse_message(
                    text,
                    allowed_instruments=allowed,
                    parser_type=source["parser_type"],
                    minimum_confidence=Decimal(str(source["minimum_confidence"])),
                )

            for index, result in enumerate(results):
                version_hash = message_hash(f"{digest}:{revision.isoformat()}:{parser_policy_version(source)}:{source.get('updated_at')}")
                identity_key = f"telegram:{source['id']}:{telegram_message_id}:{version_hash}:{index}"
                _store_parse_result(cursor, source, row_id, result, identity_key)
            _require_source_rights(source)
            return "accepted" if any(item.validation_status == "accepted" for item in results) else "rejected"


def store_message(
    *,
    channel_id: str,
    username: str | None,
    chat_id: str,
    telegram_message_id: str,
    message_date: datetime,
    edited_at: datetime | None,
    text: str,
    source_type: str = "channel",
    origin_identity: str | None = None,
) -> str:
    if not source_rights.allowed_source_ids():
        return "rejected_rights"
    try:
        return _store_message(
            channel_id=channel_id, username=username, chat_id=chat_id,
            telegram_message_id=telegram_message_id, message_date=message_date,
            edited_at=edited_at, text=text,
            source_type=source_type,
            origin_identity=origin_identity,
        )
    except SourceRightsRevoked:
        # Let the connection context roll back all staged rows before returning.
        return "rejected_rights"


async def _watch_source_rights(client: Any, sources: list[dict[str, Any]]) -> None:
    while any(source_rights.source_allowed(source["id"]) for source in sources):
        await asyncio.sleep(5)
    await client.disconnect()


async def main() -> None:
    sources = await asyncio.to_thread(_eligible_sources)
    channels = {}
    for source in sources:
        try:
            channels[normalize_channel_id(source["channel_id"], source_type=source.get("source_type", "channel"))] = source
        except (ValueError, TypeError):
            logger.warning("Configured source has an invalid channel identity; skipped")
    if not channels:
        logger.info("Telegram collection denied: no enabled source has collection and storage permission")
        return
    api_id = int(require_env("TELEGRAM_API_ID"))
    api_hash = require_env("TELEGRAM_API_HASH")
    session_string = require_env("TELEGRAM_SESSION_STRING")
    client = TelegramClient(StringSession(session_string), api_id, api_hash,
                            sequential_updates=True, flood_sleep_threshold=0,
                            request_retries=1, connection_retries=3)
    from .runtime import Collector
    from types import SimpleNamespace
    storage = SimpleNamespace(_eligible_sources=_eligible_sources, store_message=store_message,
                              delete_messages=delete_messages, reconcile_ids=reconcile_ids,
                              has_group_history=has_group_history)
    await Collector(client, storage, event_types=events).run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        logger.error("Collector stopped: error_type=%s", type(exc).__name__)
        raise SystemExit(1) from None
