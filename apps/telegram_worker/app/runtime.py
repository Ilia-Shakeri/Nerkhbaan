"""Bounded allowlisted MTProto collection with overlapping recovery and reconciliation."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from . import source_rights
from .parser import message_hash, normalize_channel_id
from .state import CollectorState

logger = logging.getLogger("telegram_worker")


def bounded_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside its bounds")
    return value


class Collector:
    def __init__(self, client: Any, storage: Any, *, event_types=None):
        self.client, self.storage = client, storage
        self.sources: dict[str, dict] = {}
        self.peers: dict[str, Any] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.retry_at: dict[str, float] = {}
        self.account_retry_at = 0.0
        self.next_poll: dict[str, float] = {}
        self.jobs: dict[str, asyncio.Task] = {}
        self.slots = asyncio.Semaphore(4)
        self.queue = asyncio.Queue(maxsize=256)
        self.state = None
        self.ready = False
        self.event_types = event_types
        self.interval = bounded_setting("TELEGRAM_POLL_SECONDS", 30, 15, 300)
        self.limit = bounded_setting("TELEGRAM_RECOVERY_LIMIT", 200, 1, 500)

    async def refresh_sources(self) -> None:
        rows = await asyncio.to_thread(self.storage._eligible_sources)
        if len(rows) > 128:
            raise ValueError("Collector source count exceeds its configured bound")
        selected = {}
        for source in rows[:128]:
            try:
                peer_id = normalize_channel_id(source["channel_id"], source_type=source.get("source_type", "channel"))
                if peer_id != source["channel_id"]:
                    continue
                selected[peer_id] = source
                self.locks.setdefault(peer_id, asyncio.Lock())
            except (ValueError, TypeError):
                logger.warning("Configured source has an invalid peer identity")
        self.sources = selected
        self.peers = {key: value for key, value in self.peers.items() if key in selected}
        if self.state:
            current_ids = {str(row["id"]) for row in selected.values()}
            self.state.data["sources"] = {key: value for key, value in self.state.data["sources"].items() if key in current_ids}
            self.state.save()

    async def peer(self, peer_id: str, source: dict):
        from telethon import utils
        from telethon.tl.types import InputPeerChannel, InputPeerChat
        # Re-resolve names on every recovery cycle; never trust a reused public username.
        username = source.get("username")
        if username:
            entity = await self.client.get_entity(username)
        elif source.get("source_type") == "group" and int(peer_id) > -1_000_000_000_000:
            entity = await self.client.get_entity(InputPeerChat(abs(int(peer_id))))
        else:
            hashes = json.loads(os.environ.get("TELEGRAM_PEER_ACCESS_HASHES", "{}"))
            if not isinstance(hashes, dict) or peer_id not in hashes:
                raise ValueError("Private channel requires its account-bound access hash")
            entity = await self.client.get_entity(InputPeerChannel(int(peer_id[4:]), int(hashes[peer_id])))
        if str(utils.get_peer_id(entity)) != peer_id:
            raise ValueError("Resolved source differs from its numeric peer identity")
        is_group = bool(getattr(entity, "megagroup", False)) or type(entity).__name__ == "Chat"
        if (source.get("source_type", "channel") == "group") != is_group:
            raise ValueError("Resolved source kind differs")
        return entity

    def allowed(self, peer_id: str, *, history: bool = False) -> dict | None:
        source = self.sources.get(peer_id)
        actions = ("collect", "store", "history") if history else ("collect", "store")
        return source if source and source_rights.source_allowed(source["id"], *actions) else None

    async def message(self, event) -> None:
        if not self.ready:
            return
        peer_id = str(event.chat_id)
        source = self.allowed(peer_id)
        if source is None or not (event.is_channel or getattr(event, "is_group", False)):
            return
        async with self.locks[peer_id]:
            source = self.allowed(peer_id)
            if source is None:
                return
            try:
                await self.store(source, event.message)
            except Exception as exc:
                logger.warning("Message storage failed: error_type=%s", type(exc).__name__)

    async def store(self, source: dict, message) -> str:
        peer_id = source["channel_id"]
        if not self.allowed(peer_id):
            return "rejected_rights"
        observed = message.date
        origin_peer = peer_id
        forwarded = getattr(message, "fwd_from", None)
        if forwarded:
            from telethon import utils
            origin = getattr(forwarded, "from_id", None)
            original_date = getattr(forwarded, "date", None)
            if origin is None or original_date is None or original_date.tzinfo is None:
                return "rejected_forward_identity"
            origin_peer = str(utils.get_peer_id(origin))
            if int(origin_peer) >= 0:
                return "rejected_forward_identity"
            observed = min(observed, original_date)
        # Never fetch sender profiles, media, replies or unlisted chat history.
        return await asyncio.to_thread(
            self.storage.store_message, channel_id=peer_id, username=source.get("username"),
            chat_id=peer_id, telegram_message_id=str(message.id), message_date=observed,
            edited_at=getattr(message, "edit_date", None), text=getattr(message, "message", "") or "",
            source_type=source.get("source_type", "channel"),
            origin_identity=message_hash(origin_peer)[:32],
        )

    async def deleted(self, event) -> None:
        if not self.ready:
            return
        # A deletion without a peer cannot safely identify a basic group. Polling
        # reconciles known fresh IDs within each explicitly allowed peer instead.
        peer_id = str(event.chat_id)
        if self.allowed(peer_id) is None:
            return
        ids = getattr(event, "deleted_ids", ())
        async with self.locks[peer_id]:
            if self.allowed(peer_id):
                await asyncio.to_thread(self.storage.delete_messages, peer_id, ids)

    async def recover(self, source: dict) -> None:
        peer_id = source["channel_id"]
        if not self.allowed(peer_id, history=True) or time.monotonic() < max(self.account_retry_at, self.retry_at.get(peer_id, 0)):
            return
        peer = await self.peer(peer_id, source)
        self.peers[peer_id] = peer
        count, capped = 0, False
        # Overlap is intentional: SQL deduplication and version checks repair edits
        # and interrupted writes without trusting a volatile high-water mark.
        async for message in self.client.iter_messages(peer, limit=self.limit + 1, wait_time=1):
            if not self.allowed(peer_id, history=True) or time.monotonic() < self.account_retry_at:
                return
            if message.date is None:
                continue
            age = (datetime.now(UTC) - message.date).total_seconds()
            if age > int(source["maximum_message_age_seconds"]):
                break
            if count == self.limit:
                capped = True
                break
            await self.store(source, message)
            count += 1
        # Only an explicit lookup of known IDs can prove an absent message;
        # absence from a limited history page is never a deletion signal.
        ids = await asyncio.to_thread(self.storage.reconcile_ids, peer_id, self.limit)
        if ids and self.allowed(peer_id, history=True) and time.monotonic() >= self.account_retry_at:
            fetched = await self.client.get_messages(peer, ids=ids)
            if len(fetched) != len(ids):
                raise ValueError("Reconciliation response length differs")
            from telethon import utils
            for expected, message in zip(ids, fetched):
                if message is not None and type(message).__name__ != "MessageEmpty" and (
                    message.id != expected or str(utils.get_peer_id(message.peer_id)) != peer_id
                ):
                    raise ValueError("Reconciliation message identity differs")
            for expected, message in zip(ids, fetched):
                if not self.allowed(peer_id, history=True):
                    return
                if message is None or type(message).__name__ == "MessageEmpty":
                    await asyncio.to_thread(self.storage.delete_messages, peer_id, [expected])
                else:
                    await self.store(source, message)
        if not self.allowed(peer_id, history=True) or time.monotonic() < self.account_retry_at:
            return
        self.state.receipt(source["id"], peer_id=peer_id, checked_at=datetime.now(UTC).isoformat(),
                           result="recovery_limit_reached" if capped else "reconciled", processed=count)
        if capped:
            logger.warning("Source recovery reached its limit; complete history is not accepted")

    async def cycle(self) -> None:
        await self.refresh_sources()
        current_ids = {str(row["id"]) for row in self.sources.values()}
        self.state.data["sources"] = {key: value for key, value in self.state.data["sources"].items() if key in current_ids}
        self.state.save()
        await asyncio.gather(*(self.run_source(source) for source in tuple(self.sources.values())))

    async def run_source(self, source: dict) -> None:
        peer_id = source["channel_id"]
        if not self.allowed(peer_id, history=True) or time.monotonic() < max(self.account_retry_at, self.retry_at.get(peer_id, 0)):
            return
        async with self.slots:
            if time.monotonic() < self.account_retry_at:
                return
            try:
                await asyncio.wait_for(self.recover(source), timeout=90)
            except Exception as exc:
                seconds = getattr(exc, "seconds", 0)
                # Honor a provider wait, never rotate accounts or evade a restriction.
                delay = max(self.interval, int(seconds)) if isinstance(seconds, (int, float)) else self.interval
                self.retry_at[source["channel_id"]] = time.monotonic() + delay
                if type(seconds) is int and seconds > 0:
                    self.account_retry_at = max(self.account_retry_at, time.monotonic()+seconds)
                self.state.receipt(source["id"], peer_id=source["channel_id"],
                                   checked_at=datetime.now(UTC).isoformat(), result=type(exc).__name__)
                logger.warning("Source reconciliation failed: error_type=%s", type(exc).__name__)
            finally:
                self.next_poll[peer_id] = time.monotonic() + self.interval

    async def poll(self) -> None:
        try:
            while self.client.is_connected():
                await self.refresh_sources()
                if not self.sources:
                    await self.client.disconnect()
                    return
                for key, task in tuple(self.jobs.items()):
                    if task.done():
                        task.result()
                        del self.jobs[key]
                for peer_id, source in tuple(self.sources.items()):
                    if self.allowed(peer_id, history=True) and peer_id not in self.jobs and time.monotonic() >= self.next_poll.get(peer_id, 0):
                        self.jobs[peer_id] = asyncio.create_task(self.run_source(source))
                await asyncio.sleep(5)
        finally:
            for task in self.jobs.values():
                task.cancel()
            await asyncio.gather(*self.jobs.values(), return_exceptions=True)

    async def enqueue_message(self, event) -> None:
        self.enqueue("message", event)

    async def enqueue_deleted(self, event) -> None:
        self.enqueue("deleted", event)

    def enqueue(self, kind: str, event) -> None:
        source = self.allowed(str(event.chat_id)) if self.ready else None
        if source is None:
            return
        try:
            self.queue.put_nowait((kind, event))
        except asyncio.QueueFull:
            self.state.receipt(source["id"], result="event_queue_full", checked_at=datetime.now(UTC).isoformat())
            logger.warning("Collector event queue full; recovery required")

    async def consume(self) -> None:
        while True:
            kind, event = await self.queue.get()
            try:
                await (self.message(event) if kind == "message" else self.deleted(event))
            except Exception as exc:
                logger.warning("Collector event failed: error_type=%s", type(exc).__name__)
            finally:
                self.queue.task_done()

    async def run(self) -> None:
        self.ready = False
        events = self.event_types
        if events is None:
            from telethon import events
        await self.refresh_sources()
        if not self.sources:
            return
        self.client.on(events.NewMessage())(self.enqueue_message)
        self.client.on(events.MessageEdited())(self.enqueue_message)
        self.client.on(events.MessageDeleted())(self.enqueue_deleted)
        task = None
        consumers = []
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                raise RuntimeError("Telegram session is not authorized; use private owner login")
            me = await self.client.get_me()
            if getattr(me, "bot", False):
                raise RuntimeError("Price collector requires the authorized reading account")
            state_path = os.environ["TELEGRAM_STATE_PATH"]
            if not Path(state_path).exists():
                for source in self.sources.values():
                    peer_id = source["channel_id"]
                    if source.get("source_type") == "group" and int(peer_id) > -1_000_000_000_000:
                        if await asyncio.to_thread(self.storage.has_group_history, peer_id):
                            raise RuntimeError("Restore the existing basic-group account binding before collection")
            self.state = CollectorState(state_path, int(me.id))
            self.state.data["sources"] = {}
            self.state.save()
            await self.refresh_sources()
            if not self.sources:
                return
            self.ready = True
            consumers = [asyncio.create_task(self.consume()) for _ in range(4)]
            task = asyncio.create_task(self.poll())
            disconnected = asyncio.ensure_future(self.client.disconnected)
            done, _ = await asyncio.wait((task, disconnected), return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                finished.result()
        finally:
            if self.ready:
                try:
                    await asyncio.wait_for(self.queue.join(), timeout=10)
                except TimeoutError:
                    logger.warning("Collector stopped with pending events; recovery required")
            self.ready = False
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            for consumer in consumers:
                consumer.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)
            await self.client.disconnect()
            if self.state:
                self.state.close()
