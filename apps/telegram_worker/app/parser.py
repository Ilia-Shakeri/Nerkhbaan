from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

DIGIT_MAP = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)
MAX_MESSAGE_CHARS = 4000


@dataclass(frozen=True)
class InstrumentRule:
    instrument_id: str
    currency: str
    weight_unit: str | None
    purity: str | None
    labels: tuple[str, ...]
    required_terms: tuple[str, ...]
    minimum: Decimal
    maximum: Decimal


@dataclass(frozen=True)
class ParsedTelegramQuote:
    instrument_id: str | None
    price: Decimal | None
    currency: str | None
    weight_unit: str | None
    purity: str | None
    confidence_score: Decimal
    validation_status: str
    rejection_reason: str | None
    parser_version: str = "strict-explicit-2"


RULES = (
    InstrumentRule(
        "GOLD_18K_TOMAN_GRAM",
        "TOMAN",
        "gram",
        "750",
        ("طلای ۱۸ عیار", "طلای 18 عیار", "#طلای18", "#طلا_18"),
        ("گرم",),
        Decimal("100000"),
        Decimal("100000000"),
    ),
    InstrumentRule(
        "SILVER_999_TOMAN_GRAM",
        "TOMAN",
        "gram",
        "999",
        ("نقره ۹۹۹", "نقره 999", "#نقره999", "#نقره_999"),
        ("گرم",),
        Decimal("1000"),
        Decimal("10000000"),
    ),
    InstrumentRule(
        "SILVER_925_TOMAN_GRAM",
        "TOMAN",
        "gram",
        "925",
        ("نقره ۹۲۵", "نقره 925", "#نقره925", "#نقره_925"),
        ("گرم",),
        Decimal("1000"),
        Decimal("10000000"),
    ),
    InstrumentRule(
        "USDT_TOMAN",
        "TOMAN",
        None,
        None,
        ("#تتر", "تتر", "USDT"),
        ("تومان",),
        Decimal("1000"),
        Decimal("10000000"),
    ),
    InstrumentRule(
        "BTC_TOMAN",
        "TOMAN",
        None,
        None,
        ("#بیتکوین", "#بیت_کوین", "بیت کوین", "BTC"),
        ("تومان",),
        Decimal("1000000"),
        Decimal("100000000000"),
    ),
)

NUMBER_PATTERN = re.compile(r"(?<![\d])([\d][\d,._\s]{1,28}[\d]|[\d]{2,30})(?![\d])")


def normalize_text(text: str) -> str:
    value = (text or "")[:MAX_MESSAGE_CHARS].translate(DIGIT_MAP)
    return value.replace("ي", "ی").replace("ك", "ک")


def message_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _number(raw: str) -> Decimal | None:
    compact = re.sub(r"[^\d]", "", raw)
    if not compact:
        return None
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def _rule_matches(text: str, rule: InstrumentRule) -> list[Decimal]:
    label_positions = [text.find(label) for label in rule.labels if text.find(label) >= 0]
    if not label_positions or any(term not in text for term in rule.required_terms):
        return []
    values: list[Decimal] = []
    for position in label_positions:
        window = text[max(0, position - 20) : position + 180]
        for match in NUMBER_PATTERN.finditer(window):
            value = _number(match.group(1))
            if value is not None and rule.minimum <= value <= rule.maximum:
                values.append(value)
    return sorted(set(values))


def parse_message(
    text: str,
    *,
    allowed_instruments: set[str],
    parser_type: str,
    minimum_confidence: Decimal,
) -> list[ParsedTelegramQuote]:
    normalized = normalize_text(text)
    if parser_type not in {"strict_explicit", "strict_hashtag"}:
        return [
            ParsedTelegramQuote(
                None, None, None, None, None, Decimal("0"), "rejected", "unsupported_parser"
            )
        ]

    output: list[ParsedTelegramQuote] = []
    for rule in RULES:
        if rule.instrument_id not in allowed_instruments:
            continue
        values = _rule_matches(normalized, rule)
        if len(values) > 1:
            output.append(
                ParsedTelegramQuote(
                    rule.instrument_id,
                    None,
                    rule.currency,
                    rule.weight_unit,
                    rule.purity,
                    Decimal("0.25"),
                    "rejected",
                    "ambiguous_price",
                )
            )
        elif len(values) == 1:
            confidence = Decimal("0.95") if parser_type == "strict_hashtag" else Decimal("0.90")
            status = "accepted" if confidence >= minimum_confidence else "rejected"
            output.append(
                ParsedTelegramQuote(
                    rule.instrument_id,
                    values[0],
                    rule.currency,
                    rule.weight_unit,
                    rule.purity,
                    confidence,
                    status,
                    None if status == "accepted" else "confidence_below_threshold",
                )
            )

    if output:
        return output
    return [
        ParsedTelegramQuote(
            None,
            None,
            None,
            None,
            None,
            Decimal("0"),
            "rejected",
            "no_explicit_instrument_match",
        )
    ]
