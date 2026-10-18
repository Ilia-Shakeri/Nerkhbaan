"""Durable reference observations with their original source and receipt clocks."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..db import SessionLocal
from . import rights
from .db_models import ReferenceRateRecord
from .freshness import DEFAULT_FUTURE_CLOCK_SKEW_SECONDS
from .models import utc_now
from .parsers.base import ParserError
from .parsers.nerkhsanj_history import _TEHRAN, _source_day
from .reference_rates import validate_reference_record

REFERENCE_IDS = frozenset({
    'GOLD_24K_REFERENCE_TOMAN_GRAM', 'BTC_USD_IRAN_REFERENCE', 'USDT_USD_IRAN_REFERENCE',
})
_SOURCE = {'snapshot': 'nerkhsanj_reference_snapshot', 'history': 'nerkhsanj_reference_history'}


def reference_allowed(reference_id: str, kind: str, *, store: bool = False) -> bool:
    if reference_id not in REFERENCE_IDS or kind not in _SOURCE:
        return False
    actions = ['display']
    if store:
        actions += ['collect', 'store']
    if kind == 'history':
        actions.append('history')
    if reference_id != 'GOLD_24K_REFERENCE_TOMAN_GRAM':
        actions.append('derive')
    return all(rights.provider_allowed(_SOURCE[kind], action) for action in actions)


def _clock(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Reference records require an explicit timezone')
    return parsed.astimezone(UTC)


class ReferenceRateRepository:
    def __init__(self, sessions=None):
        self.sessions = sessions or SessionLocal

    async def save_snapshot(self, references: list[dict], received_at: datetime) -> int:
        return await asyncio.to_thread(self._save, 'snapshot', references, received_at)

    async def save_history(self, histories: dict[str, list[dict]], received_at: datetime) -> int:
        rows = []
        for reference_id, points in histories.items():
            if reference_id not in REFERENCE_IDS:
                continue
            for row in points:
                if row.get('instrument_id') != reference_id:
                    raise ValueError('Reference history key must match its original contract')
                rows.append(row)
        return await asyncio.to_thread(self._save, 'history', rows, received_at)

    def _save(self, kind: str, rows: list[dict], received_at: datetime) -> int:
        if len(rows) > 12000:
            raise ValueError('Reference import is bounded')
        received = _clock(received_at)
        if received > utc_now() + timedelta(seconds=DEFAULT_FUTURE_CLOCK_SKEW_SECONDS):
            raise ValueError('Reference receipt cannot be in the future')
        revision = rights.revision()
        prepared = {}
        for source in rows:
            reference_id = source.get('instrument_id')
            if not reference_allowed(reference_id, kind, store=True):
                continue
            if (source.get('market') != 'reference' or source.get('region') != 'iran'
                    or source.get('physical_purity_confirmed') is not False or source.get('purity') is not None):
                raise ValueError('A reference record must not claim a physical or exchange contract')
            raw_price = source.get('price_decimal', source.get('price'))
            if raw_price is None:
                continue
            validate_reference_record(source, kind)
            try:
                price = Decimal(str(raw_price))
                if isinstance(raw_price, bool) or not price.is_finite() or price <= 0:
                    raise ValueError('Reference price must be finite and positive')
            except InvalidOperation as exc:
                raise ValueError('Reference price must be numeric') from exc
            stamp = _clock(source.get('observed_at') if kind == 'snapshot' else source.get('timestamp'))
            if stamp > received + timedelta(seconds=DEFAULT_FUTURE_CLOCK_SKEW_SECONDS):
                raise ValueError('Reference record cannot have a future source clock')
            slot = 'current' if kind == 'snapshot' else source.get('source_date')
            if kind == 'history' and (not isinstance(slot, str) or not re.fullmatch(r'\d{4}/\d{2}/\d{2}', slot)):
                raise ValueError('Reference history needs its exact source date')
            if kind == 'history':
                day = _source_day(slot)
                expected = datetime.combine(day, time.min, _TEHRAN).astimezone(UTC)
                closed_at = datetime.combine(day + timedelta(days=1), time.min, _TEHRAN).astimezone(UTC)
                if (stamp != expected or closed_at > received
                        or source.get('source_timezone') != 'Asia/Tehran'
                        or source.get('source_calendar') != 'jalali'
                        or source.get('timestamp_precision') != 'day'
                        or source.get('timestamp_role') != 'day_bucket_start'
                        or source.get('source_observation_time_known') is not False):
                    raise ValueError('Reference history requires a closed, correctly dated daily bucket')
            payload = deepcopy(source)
            encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
            if len(encoded.encode('utf-8')) > 32768:
                raise ValueError('Reference record exceeds its bound')
            identity = {key: value for key, value in payload.items()
                        if key not in {'age_seconds', 'status', 'received_at', 'checked_at', 'persistence_status'}}
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            key = (reference_id, slot)
            if key in prepared and prepared[key]['payload_hash'] != digest:
                raise ValueError('Reference import contains conflicting duplicate points')
            prepared[key] = dict(reference_id=reference_id, record_kind=kind, slot=slot,
                                 recorded_at=stamp, received_at=received, payload_hash=digest, payload=payload)
        written = 0
        prepared = list(prepared.values())
        with self.sessions() as db:
            for start in range(0, len(prepared), 200):
                chunk = prepared[start:start + 200]
                if revision != rights.revision() or any(
                    not reference_allowed(reference_id, kind, store=True)
                    for reference_id in {row['reference_id'] for row in chunk}
                ):
                    raise PermissionError('Reference permission changed during persistence')
                statement = insert(ReferenceRateRecord).values(chunk)
                excluded = statement.excluded
                statement = statement.on_conflict_do_update(
                    index_elements=['reference_id', 'record_kind', 'slot'],
                    set_={name: getattr(excluded, name) for name in ('recorded_at', 'received_at', 'payload_hash', 'payload')},
                    where=(ReferenceRateRecord.payload_hash != excluded.payload_hash)
                          & (ReferenceRateRecord.recorded_at <= excluded.recorded_at)
                          & (ReferenceRateRecord.received_at <= excluded.received_at),
                )
                written += len(db.execute(statement.returning(ReferenceRateRecord.reference_id)).all())
            if revision != rights.revision() or any(
                not reference_allowed(row['reference_id'], kind, store=True) for row in prepared
            ):
                raise PermissionError('Reference permission changed before commit')
            db.commit()
        return written

    async def load(self, range_start: datetime, range_end: datetime) -> dict:
        return await asyncio.to_thread(self._load, range_start, range_end)

    def _load(self, range_start, range_end) -> dict:
        start, end = _clock(range_start), _clock(range_end)
        if start >= end or end - start > timedelta(days=366):
            raise ValueError('Reference history range must be bounded')
        revision = rights.revision()
        output = {'snapshots': [], 'histories': {reference_id: [] for reference_id in sorted(REFERENCE_IDS)}}
        with self.sessions() as db:
            records = db.scalars(select(ReferenceRateRecord).where(
                (ReferenceRateRecord.record_kind == 'snapshot') |
                ((ReferenceRateRecord.recorded_at >= start) & (ReferenceRateRecord.recorded_at < end))
            ).order_by(ReferenceRateRecord.recorded_at, ReferenceRateRecord.reference_id).limit(12004)).all()
            for row in records:
                if not reference_allowed(row.reference_id, row.record_kind):
                    continue
                try:
                    if row.payload.get('instrument_id') != row.reference_id:
                        continue
                    validate_reference_record(row.payload, row.record_kind)
                except (ParserError, TypeError, ValueError, AttributeError):
                    continue
                if row.record_kind == 'snapshot':
                    output['snapshots'].append(deepcopy(row.payload))
                elif row.record_kind == 'history':
                    output['histories'][row.reference_id].append(deepcopy(row.payload))
        if rights.revision() != revision:
            return {'snapshots': [], 'histories': {}}
        output['snapshots'] = [row for row in output['snapshots']
                               if reference_allowed(row['instrument_id'], 'snapshot')]
        output['histories'] = {key: values for key, values in output['histories'].items()
                                if reference_allowed(key, 'history')}
        return output


reference_rate_repository = ReferenceRateRepository()
