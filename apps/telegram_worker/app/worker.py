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
from .parser import ParsedTelegramQuote, message_hash, normalize_channel_id, normalize_text, parse_message

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
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, channel_id, username FROM telegram_sources "
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
                quote.parser_version,
                quote.confidence_score,
                json.dumps(
                    {
                        "telegram_source_id": source["id"],
                        "source_role": source["role"],
                        "trust_score": str(source["trust_score"]),
                        "requires_multiple_sources": source["requires_multiple_sources"],
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
            quote.parser_version,
            quote.confidence_score,
            quote.validation_status,
            quote.rejection_reason,
            provider_quote_id,
        ),
    )
    _require_source_rights(source)


def _store_message(
    *,
    channel_id: str,
    username: str | None,
    chat_id: str,
    telegram_message_id: str,
    message_date: datetime,
    edited_at: datetime | None,
    text: str,
) -> str:
    channel_id = normalize_channel_id(channel_id)
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            source = _source_for(cursor, channel_id, username)
            if not source:
                return "rejected_source"
            _require_source_rights(source)
            digest = message_hash(text)

            now = datetime.now(UTC)
            maximum_age = int(source["maximum_message_age_seconds"])
            if message_date.tzinfo is None:
                message_date = message_date.replace(tzinfo=UTC)
            age_seconds = max(0, int((now - message_date).total_seconds()))

            cursor.execute(
                "SELECT id, message_hash FROM telegram_messages WHERE channel_id = %s AND message_id = %s",
                (channel_id, telegram_message_id),
            )
            existing = cursor.fetchone()
            if existing and existing["message_hash"] == digest:
                return "duplicate"

            _require_source_rights(source)
            keep_text = os.getenv("TELEGRAM_STORE_SANITIZED_TEXT", "false").lower() == "true"
            sanitized = normalize_text(text)[:4000] if keep_text else None
            if existing:
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
                    (source["id"], chat_id, message_date, edited_at or now, digest, sanitized, existing["id"]),
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
                identity_key = f"telegram:{source['id']}:{telegram_message_id}:{digest}:{index}"
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
) -> str:
    if not source_rights.allowed_source_ids():
        return "rejected_rights"
    try:
        return _store_message(
            channel_id=channel_id, username=username, chat_id=chat_id,
            telegram_message_id=telegram_message_id, message_date=message_date,
            edited_at=edited_at, text=text,
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
            channels[normalize_channel_id(source["channel_id"])] = source
        except (ValueError, TypeError):
            logger.warning("Configured source has an invalid channel identity; skipped")
    if not channels:
        logger.info("Telegram collection denied: no enabled source has collection and storage permission")
        return
    api_id = int(require_env("TELEGRAM_API_ID"))
    api_hash = require_env("TELEGRAM_API_HASH")
    session_string = require_env("TELEGRAM_SESSION_STRING")
    client = TelegramClient(StringSession(session_string), api_id, api_hash)

    async def handle(event: Any) -> None:
        if not event.is_channel:
            return
        # event.chat_id already uses Telegram's marked channel identity.
        channel_id = normalize_channel_id(event.chat_id)
        source = channels.get(channel_id)
        if not source or not source_rights.source_allowed(source["id"]):
            return
        outcome = await asyncio.to_thread(
            store_message,
            channel_id=channel_id,
            username=source.get("username"),
            chat_id=str(event.chat_id),
            telegram_message_id=str(event.message.id),
            message_date=event.message.date,
            edited_at=getattr(event.message, "edit_date", None),
            text=event.raw_text or "",
        )
        logger.info("Telegram message handled: result=%s", outcome)

    selected_channels = tuple(int(channel_id) for channel_id in channels)

    @client.on(events.NewMessage(chats=selected_channels))
    async def on_message(event: events.NewMessage.Event) -> None:
        await handle(event)

    @client.on(events.MessageEdited(chats=selected_channels))
    async def on_edit(event: events.MessageEdited.Event) -> None:
        await handle(event)

    if not any(source_rights.source_allowed(source["id"]) for source in channels.values()):
        logger.info("Telegram collection denied: source permission changed before connection")
        return
    watcher = None
    try:
        await client.start()
        watcher = asyncio.create_task(_watch_source_rights(client, list(channels.values())))
        logger.info("Telegram worker connected; current source permissions are enforced")
        await client.run_until_disconnected()
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
