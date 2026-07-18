from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from .parser import ParsedTelegramQuote, message_hash, normalize_text, parse_message

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("telegram_worker")


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
        WHERE enabled = TRUE
          AND (channel_id = %s OR (%s IS NOT NULL AND lower(username) = lower(%s)))
        LIMIT 1
        """,
        (channel_id, username, username),
    )
    return cursor.fetchone()


def _record_unknown_source(cursor: psycopg.Cursor, channel_id: str) -> None:
    cursor.execute(
        """
        INSERT INTO provider_runtime_events (
            provider_id, instrument_id, event_type, status, sanitized_error, detail
        ) VALUES (%s, NULL, 'telegram_message', 'rejected', 'source_not_whitelisted', %s::jsonb)
        """,
        ("telegram:unknown", json.dumps({"channel_hash": message_hash(channel_id)})),
    )


def _store_parse_result(
    cursor: psycopg.Cursor,
    source: dict[str, Any],
    telegram_message_id: int,
    quote: ParsedTelegramQuote,
    identity_key: str,
) -> None:
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
    digest = message_hash(text)
    with psycopg.connect(_database_url(), row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            source = _source_for(cursor, channel_id, username)
            if not source:
                _record_unknown_source(cursor, channel_id)
                return "rejected_source"

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

            keep_text = os.getenv("TELEGRAM_STORE_SANITIZED_TEXT", "false").lower() == "true"
            sanitized = normalize_text(text)[:4000] if keep_text else None
            if existing:
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
                cursor.execute("DELETE FROM telegram_parse_results WHERE telegram_message_id = %s", (existing["id"],))
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

            allowed = set(source["allowed_instruments"] or [])
            if age_seconds > maximum_age:
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
            return "accepted" if any(item.validation_status == "accepted" for item in results) else "rejected"


async def main() -> None:
    api_id = int(require_env("TELEGRAM_API_ID"))
    api_hash = require_env("TELEGRAM_API_HASH")
    session_string = require_env("TELEGRAM_SESSION_STRING")
    client = TelegramClient(StringSession(session_string), api_id, api_hash)

    async def handle(event: Any) -> None:
        chat = await event.get_chat()
        username = getattr(chat, "username", None)
        channel_id = str(getattr(chat, "id", event.chat_id))
        outcome = await asyncio.to_thread(
            store_message,
            channel_id=channel_id,
            username=username,
            chat_id=str(event.chat_id),
            telegram_message_id=str(event.message.id),
            message_date=event.message.date,
            edited_at=getattr(event.message, "edit_date", None),
            text=event.raw_text or "",
        )
        logger.info("Telegram message handled: channel=%s result=%s", channel_id, outcome)

    @client.on(events.NewMessage())
    async def on_message(event: events.NewMessage.Event) -> None:
        await handle(event)

    @client.on(events.MessageEdited())
    async def on_edit(event: events.MessageEdited.Event) -> None:
        await handle(event)

    await client.start()
    logger.info("Telegram worker connected; database source whitelist is active")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
