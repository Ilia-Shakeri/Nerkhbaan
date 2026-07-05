from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime

import psycopg
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from .parser import extract_prices

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("telegram_worker")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def channel_list() -> list[str]:
    raw = os.getenv("TELEGRAM_CHANNELS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def store_price(asset: str, region: str, price_toman: int, source: str) -> None:
    database_url = require_env("DATABASE_URL")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_prices (time, asset, region, source, price_usd, price_toman, volume, metadata)
                VALUES (%s, %s, %s, %s, NULL, %s, NULL, '{}'::jsonb)
                """,
                (datetime.now(UTC), asset, region, source, price_toman),
            )


async def main() -> None:
    api_id = int(require_env("TELEGRAM_API_ID"))
    api_hash = require_env("TELEGRAM_API_HASH")
    session_string = require_env("TELEGRAM_SESSION_STRING")
    channels = channel_list()
    if not channels:
        raise RuntimeError("TELEGRAM_CHANNELS must include at least one public channel")

    client = TelegramClient(StringSession(session_string), api_id, api_hash)

    @client.on(events.NewMessage(chats=channels))
    async def on_message(event: events.NewMessage.Event) -> None:
        text = event.raw_text or ""
        parsed_prices = extract_prices(text)
        if not parsed_prices:
            return

        source = f"telegram:{getattr(event.chat, 'username', None) or event.chat_id}"
        for price in parsed_prices:
            try:
                await asyncio.to_thread(
                    store_price,
                    price.asset,
                    price.region,
                    price.price_toman,
                    source,
                )
                logger.info("Stored %s %s from %s", price.asset, price.price_toman, price.hashtag)
            except Exception as exc:
                logger.warning("Telegram price persistence failed: %s", exc)

    await client.start()
    logger.info("Telegram worker connected to %s", ", ".join(channels))
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
