from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import text

from ..db import SessionLocal
from . import rights
from ..admin.telegram_parser import parser_policy_version
from .operational import operational_pricing_settings
from .models import (
    Currency,
    InstrumentDefinition,
    PersistenceStatus,
    PriceSemantic,
    ProviderQuote,
    SourceSemantic,
    SourceType,
    ValidationStatus,
    WeightUnit,
    ensure_utc,
    utc_now,
)


class StoredTelegramQuoteRepository:
    async def canonical_inputs_valid(self, quote, instrument: InstrumentDefinition) -> bool:
        """Never let a Redis snapshot revive an edited/deleted Telegram input."""
        leaves = rights._leaves(quote.source_summary) or set()
        if not any(name.startswith("telegram:") for name in leaves):
            return True
        ids = [value for value in (quote.primary_quote_id, *quote.verification_quote_ids)
               if isinstance(value, int) and value > 0]
        if not ids:
            return False
        try:
            rows = await asyncio.to_thread(self._input_rows, ids)
            if {int(row["id"]) for row in rows} != set(ids):
                return False
            telegram_ids = {int(row["id"]) for row in rows if row["source_type"] == "telegram"}
            if not telegram_ids:
                return False
            valid_ids = set()
            identities: set[tuple[str, str]] = set()
            for instrument_id in {row["instrument_id"] for row in rows if row["source_type"] == "telegram"}:
                definition = instrument if instrument_id == instrument.instrument_id else await operational_pricing_settings.instrument(instrument_id)
                fresh = await self.latest(definition, roles=("verifier", "fallback"))
                selected = [item for item in fresh if item.id in telegram_ids]
                role_map = self._canonical_roles(quote.source_summary)
                for item in selected:
                    roles = role_map.get(item.provider_id, set())
                    if roles != {item.metadata.get("source_role")}:
                        return False
                    identity = (instrument_id, str(item.metadata.get("source_identity")))
                    if identity in identities:
                        return False
                    identities.add(identity)
                fallback = [item for item in selected if item.metadata.get("source_role") == "fallback"]
                if any(item.metadata.get("requires_multiple_sources") for item in fallback) and len(fallback) < 2:
                    return False
                valid_ids.update(item.id for item in selected)
            return telegram_ids <= valid_ids
        except Exception:
            # Unavailable verification storage cannot certify a cached social quote.
            return False

    @staticmethod
    def _canonical_roles(summary: dict, depth: int = 0) -> dict[str, set[str]]:
        if not isinstance(summary, dict) or depth > 6:
            return {}
        result: dict[str, set[str]] = {}
        if summary.get("derived"):
            for item in summary.get("inputs", []):
                for provider, roles in StoredTelegramQuoteRepository._canonical_roles(item.get("source_summary", {}), depth+1).items():
                    result.setdefault(provider, set()).update(roles)
        else:
            providers = summary.get("provider_ids", [])
            role = "fallback" if providers and all(name.startswith("telegram:") for name in providers) else "verifier"
            for provider in providers:
                if provider.startswith("telegram:"):
                    result[provider] = {role}
        return result

    @staticmethod
    def _input_rows(ids: list[int]):
        db = SessionLocal()
        try:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            return db.execute(text("SELECT id, source_type, instrument_id FROM provider_quotes WHERE id = ANY(:ids)"),
                              {"ids": ids}).mappings().all()
        finally:
            db.close()

    async def latest(
        self,
        instrument: InstrumentDefinition,
        *,
        roles: Iterable[str],
        now: datetime | None = None,
    ) -> list[ProviderQuote]:
        if rights.enforced() and not any(name.startswith("telegram:") for name in rights.allowed_provider_ids("display")):
            return []
        if not await operational_pricing_settings.feature_enabled("telegram_source_enabled", scope_id=instrument.instrument_id):
            return []
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
            if quote is not None and rights.provider_allowed(quote.provider_id, "display"):
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
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET LOCAL statement_timeout = '2000ms'"))
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
                        quote.metadata AS telegram_metadata,
                        parsed.validation_status AS parse_validation_status,
                        message.message_date, message.channel_id,
                        source.id AS telegram_source_id,
                        source.allowed_instruments, source.role,
                        source.trust_score, source.minimum_confidence,
                        source.maximum_message_age_seconds,
                        source.maximum_deviation_percent,
                        source.requires_multiple_sources
                        , source.parser_type, source.parser_version AS source_parser_version
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
                      AND parsed.parser_version = quote.parser_version
                      AND source.enabled = TRUE
                      AND source.role IN ('verifier', 'fallback')
                      AND (:rights_enforced = FALSE OR quote.provider_id = ANY(:rights_provider_ids))
                      AND quote.observed_at >= :earliest
                      AND quote.observed_at <= :current
                    ORDER BY source.id, quote.observed_at DESC
                    """
                ),
                {
                    "instrument_id": instrument_id,
                    "earliest": earliest,
                    "current": current,
                    "rights_enforced": rights.enforced(),
                    "rights_provider_ids": list(rights.allowed_provider_ids("display")),
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
        if row.get("source_parser_version") is not None:
            policy = {"parser_type": row["parser_type"], "parser_version": row["source_parser_version"],
                      "allowed_instruments": row["allowed_instruments"], "minimum_confidence": row["minimum_confidence"]}
            if row["parser_version"] != parser_policy_version(policy):
                return None
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
            confidence = Decimal(str(row["confidence_score"]))
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
            or not confidence.is_finite() or confidence < minimum_confidence
            or trust_score < (Decimal("0.8") if role == "fallback" else Decimal("0.5"))
            or not maximum_deviation.is_finite()
            or maximum_deviation <= 0
        ):
            return None
        try:
            import re
            metadata = row.get("telegram_metadata") or {}
            origin = metadata.get("origin_identity") if isinstance(metadata, dict) else None
            identity = f"origin:{origin}" if isinstance(origin, str) and re.fullmatch(r"[0-9a-f]{32}", origin) else str(row["telegram_source_id"])
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
                source_semantic=SourceSemantic.TELEGRAM_OBSERVATION,
                source_family=f"telegram:{identity}",
                venue="telegram",
                selected_price_semantic=PriceSemantic.PROVIDER_SELECTED,
                original_currency=currency.value,
                original_value=price,
                conversion_factor=Decimal(1),
                route_id="telegram_ingestion",
                derivation_depth=0,
                provenance=(f"telegram:{row['telegram_source_id']}",),
                metadata={
                    "whitelisted": True,
                    "source_identity": identity,
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
