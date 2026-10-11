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
    parser_version: str = "strict-explicit-3"


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
        (),
        Decimal("1000"),
        Decimal("10000000"),
    ),
    InstrumentRule(
        "BTC_TOMAN",
        "TOMAN",
        None,
        None,
        ("#بیتکوین", "#بیت_کوین", "بیت کوین", "BTC"),
        (),
        Decimal("1000000"),
        Decimal("100000000000"),
    ),
)

NUMBER_PATTERN = re.compile(r"(?<![\d.])([\d]+(?:[,٬_][\d]{3})*(?:[.٫][\d]+)?)(?![\d.])")
PARSER_TYPES = frozenset({"strict_explicit", "strict_hashtag"})


def normalize_channel_id(value: str | int) -> str:
    """Store Telegram channel IDs in the marked -100 form."""
    raw = str(value).strip()
    if not raw.lstrip("-").isdigit():
        raise ValueError("Channel ID must be numeric")
    if raw.startswith("-100") and len(raw) > 4:
        return raw
    if raw.startswith("-"):
        raise ValueError("Expected a channel ID, not a group ID")
    if int(raw) <= 0:
        raise ValueError("Channel ID must be positive or marked -100")
    return f"-100{int(raw)}"


def normalize_text(text: str) -> str:
    value = (text or "")[:MAX_MESSAGE_CHARS].translate(DIGIT_MAP)
    return value.replace("ي", "ی").replace("ك", "ک")


def message_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _number(raw: str) -> Decimal | None:
    compact = raw.replace(",", "").replace("٬", "").replace("_", "").replace("٫", ".")
    if not compact:
        return None
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def _rule_matches(text: str, rule: InstrumentRule, *, hashtag: bool = False) -> list[Decimal]:
    values: list[Decimal] = []
    for line in text.splitlines():
        labels = [label for label in rule.labels if label in line and (not hashtag or label.startswith("#") or f"#{label}" in line)]
        if not labels or any(term not in line for term in rule.required_terms):
            continue
        has_toman = bool(re.search(r"تومان|\bTOMAN\b", line, re.IGNORECASE))
        has_rial = bool(re.search(r"ریال|\bRIAL\b|\bIRR\b", line, re.IGNORECASE))
        if has_toman == has_rial:
            continue
        position = min(line.find(label) for label in labels)
        window = line[max(0, position - 20) : position + 180]
        for match in NUMBER_PATTERN.finditer(window):
            value = _number(match.group(1))
            if value is not None:
                value = value / 10 if has_rial else value
                if rule.minimum <= value <= rule.maximum:
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
    if parser_type not in PARSER_TYPES:
        return [
            ParsedTelegramQuote(
                None, None, None, None, None, Decimal("0"), "rejected", "unsupported_parser"
            )
        ]

    output: list[ParsedTelegramQuote] = []
    for rule in RULES:
        if rule.instrument_id not in allowed_instruments:
            continue
        values = _rule_matches(normalized, rule, hashtag=parser_type == "strict_hashtag")
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
