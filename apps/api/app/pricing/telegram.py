from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import text

from ..db import SessionLocal
from .models import (
    Currency,
    InstrumentDefinition,
    PersistenceStatus,
    ProviderQuote,
    SourceType,
    ValidationStatus,
    WeightUnit,
    ensure_utc,
    utc_now,
)


class StoredTelegramQuoteRepository:
    async def latest(
        self,
        instrument: InstrumentDefinition,
        *,
        roles: Iterable[str],
        now: datetime | None = None,
    ) -> list[ProviderQuote]:
        current = ensure_utc(now or utc_now())
        allowed_roles = {role for role in roles if role in {"verifier", "fallback"}}
        if not allowed_roles:
            return []
        rows = await asyncio.to_thread(
            self._rows,
            instrument.instrument_id,
            current - timedelta(seconds=instrument.operational_ttl_seconds),
            current,
        )
        quotes: list[ProviderQuote] = []
        for row in rows:
            quote = self._quote_from_row(row, instrument, allowed_roles, current)
            if quote is not None:
                quotes.append(quote)
        return quotes

    @staticmethod
    def _rows(
        instrument_id: str,
        earliest: datetime,
        current: datetime,
    ) -> list[Any]:
        db = SessionLocal()
        try:
            return db.execute(
                text(
                    """
                    SELECT DISTINCT ON (source.id)
                        quote.id, quote.instrument_id, quote.provider_id,
                        quote.price, quote.currency, quote.weight_unit,
                        quote.purity, quote.observed_at, quote.received_at,
                        quote.parser_version, quote.validation_status,
                        quote.confidence_score, quote.is_direct,
                        quote.is_derived, quote.is_suspicious,
                        quote.idempotency_key,
                        parsed.validation_status AS parse_validation_status,
                        message.message_date, message.channel_id,
                        source.id AS telegram_source_id,
                        source.allowed_instruments, source.role,
                        source.trust_score, source.minimum_confidence,
                        source.maximum_message_age_seconds,
                        source.maximum_deviation_percent,
                        source.requires_multiple_sources
                    FROM provider_quotes AS quote
                    JOIN telegram_parse_results AS parsed
                      ON parsed.provider_quote_id = quote.id
                    JOIN telegram_messages AS message
                      ON message.id = parsed.telegram_message_id
                    JOIN telegram_sources AS source
                      ON source.id = message.source_id
                     AND source.channel_id = message.channel_id
                    WHERE quote.instrument_id = :instrument_id
                      AND quote.source_type = 'telegram'
                      AND quote.validation_status = 'accepted'
                      AND parsed.validation_status = 'accepted'
                      AND source.enabled = TRUE
                      AND source.role IN ('verifier', 'fallback')
                      AND quote.observed_at >= :earliest
                      AND quote.observed_at <= :current
                    ORDER BY source.id, quote.observed_at DESC
                    """
                ),
                {
                    "instrument_id": instrument_id,
                    "earliest": earliest,
                    "current": current,
                },
            ).mappings().all()
        finally:
            db.close()

    @staticmethod
    def _quote_from_row(
        row: Any,
        instrument: InstrumentDefinition,
        allowed_roles: set[str],
        current: datetime,
    ) -> ProviderQuote | None:
        role = str(row["role"] or "")
        allowed_instruments = row["allowed_instruments"]
        if (
            role not in allowed_roles
            or not isinstance(allowed_instruments, list)
            or instrument.instrument_id not in allowed_instruments
            or str(row["provider_id"]) != f"telegram:{row['telegram_source_id']}"
            or str(row["validation_status"]) != ValidationStatus.ACCEPTED.value
            or str(row["parse_validation_status"]) != ValidationStatus.ACCEPTED.value
            or not bool(row["is_direct"])
            or bool(row["is_derived"])
            or bool(row["is_suspicious"])
        ):
            return None
        try:
            observed_at = ensure_utc(row["observed_at"])
            message_date = ensure_utc(row["message_date"])
            maximum_age = int(row["maximum_message_age_seconds"] or 0)
        except (OverflowError, TypeError, ValueError):
            return None
        if (
            maximum_age <= 0
            or abs((observed_at - message_date).total_seconds()) > 1
            or (current - observed_at).total_seconds()
            > min(maximum_age, instrument.operational_ttl_seconds)
        ):
            return None
        try:
            price = Decimal(str(row["price"]))
            purity = Decimal(str(row["purity"])) if row["purity"] is not None else None
            if purity is not None and purity > 1:
                purity /= Decimal(1000)
            trust_score = Decimal(str(row["trust_score"]))
            minimum_confidence = Decimal(str(row["minimum_confidence"]))
            maximum_deviation = Decimal(str(row["maximum_deviation_percent"]))
            currency = Currency(str(row["currency"]))
            weight_unit = (
                WeightUnit(str(row["weight_unit"]))
                if row["weight_unit"] is not None
                else WeightUnit.UNIT
            )
        except (InvalidOperation, TypeError, ValueError):
            return None
        if (
            not instrument.accepts(price)
            or currency is not instrument.quote_currency
            or weight_unit is not instrument.weight_unit
            or purity != instrument.purity
            or not trust_score.is_finite()
            or not Decimal(0) <= trust_score <= Decimal(1)
            or not minimum_confidence.is_finite()
            or not Decimal(0) <= minimum_confidence <= Decimal(1)
            or not maximum_deviation.is_finite()
            or maximum_deviation <= 0
        ):
            return None
        try:
            return ProviderQuote.create(
                id=int(row["id"]),
                instrument_id=instrument.instrument_id,
                provider_id=str(row["provider_id"]),
                source_type=SourceType.TELEGRAM,
                price=price,
                currency=currency,
                weight_unit=weight_unit,
                purity=purity,
                observed_at=observed_at,
                received_at=ensure_utc(row["received_at"]),
                parser_version=str(row["parser_version"]),
                validation_status=ValidationStatus.ACCEPTED,
                confidence_score=Decimal(str(row["confidence_score"])),
                is_direct=True,
                is_derived=False,
                is_suspicious=False,
                metadata={
                    "whitelisted": True,
                    "source_identity": str(row["telegram_source_id"]),
                    "source_role": role,
                    "approved_verifier": role == "verifier",
                    "approved_fallback": role == "fallback",
                    "trust_score": str(trust_score),
                    "minimum_confidence": str(minimum_confidence),
                    "maximum_message_age_seconds": maximum_age,
                    "maximum_deviation_percent": str(maximum_deviation),
                    "requires_multiple_sources": bool(
                        row["requires_multiple_sources"]
                    ),
                },
                persistence_status=PersistenceStatus.PERSISTED,
                idempotency_key=str(row["idempotency_key"]),
            )
        except (TypeError, ValueError):
            return None


stored_telegram_quotes = StoredTelegramQuoteRepository()
