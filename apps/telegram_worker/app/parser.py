from __future__ import annotations

import re
from dataclasses import dataclass

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

HASHTAG_ASSETS = {
    "#دلار": ("usdt", "iran"),
    "#تتر": ("usdt", "iran"),
    "#آبشده": ("melted_gold", "iran"),
    "#ابشده": ("melted_gold", "iran"),
    "#طلا": ("gold", "iran"),
    "#سکه": ("coin", "iran"),
    "#بیتکوین": ("btc", "iran"),
    "#بیت_کوین": ("btc", "iran"),
}

PRICE_PATTERN = re.compile(r"(?<!\d)([۰-۹٠-٩\d][۰-۹٠-٩\d,\.\s_]{2,})(?!\d)")


@dataclass(frozen=True)
class ParsedTelegramPrice:
    asset: str
    region: str
    price_toman: int
    hashtag: str


def normalize_price(raw: str) -> int | None:
    normalized = raw.translate(PERSIAN_DIGITS)
    normalized = re.sub(r"[^\d]", "", normalized)
    if not normalized:
        return None
    value = int(normalized)
    if value <= 0:
        return None
    return value


def extract_prices(text: str) -> list[ParsedTelegramPrice]:
    if not text:
        return []

    matches: list[ParsedTelegramPrice] = []
    for hashtag, (asset, region) in HASHTAG_ASSETS.items():
        tag_index = text.find(hashtag)
        if tag_index < 0:
            continue

        window = text[tag_index : tag_index + 180]
        price_match = PRICE_PATTERN.search(window)
        if not price_match:
            continue

        price = normalize_price(price_match.group(1))
        if price is None:
            continue

        matches.append(
            ParsedTelegramPrice(asset=asset, region=region, price_toman=price, hashtag=hashtag)
        )

    return matches
