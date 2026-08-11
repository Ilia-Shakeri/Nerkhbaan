from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .registry import PROVIDERS, ProviderDefinition


@dataclass(frozen=True, slots=True)
class ProviderContract:
    provider_id: str
    tier: str
    endpoint_version: str
    credential_placement: str
    unit_contract: str
    source_timestamp: str
    redistribution_status: str
    commercial_status: str
    owner: str
    docs: tuple[str, ...]
    attribution_required: bool
    enabled_acceptance: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "tier": self.tier,
            "endpoint_version": self.endpoint_version,
            "credential_placement": self.credential_placement,
            "unit_contract": self.unit_contract,
            "source_timestamp": self.source_timestamp,
            "redistribution_status": self.redistribution_status,
            "commercial_status": self.commercial_status,
            "owner": self.owner,
            "docs": list(self.docs),
            "attribution_required": self.attribution_required,
            "enabled_acceptance": list(self.enabled_acceptance),
        }


_DOCS = {
    "coinbase": ("https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductticker",),
    "coingecko": ("https://docs.coingecko.com/reference/simple-price",),
    "goldapi": ("https://www.goldapi.io/",),
    "gold_api_free": ("https://api.gold-api.com/",),
    "metals_dev": ("https://metals.dev/",),
    "nobitex": ("https://apidocs.nobitex.ir/",),
    "wallex": ("https://api-docs.wallex.ir/",),
    "servix": ("https://servix.cc/docs", "https://servix.cc/terms"),
    "tala": ("https://api.tala.ir/document", "https://api.tala.ir/terms"),
    "ticaro": ("https://ticaro.ir/docs", "https://ticaro.ir/terms"),
    "arzbin": ("https://www.arzbin.com/developers/api",),
    "navasan": ("https://www.navasan.tech/webserviceguide/", "https://www.navasan.tech/en/api"),
    "nerkh_io": ("https://docs.nerkh.io/openapi.yaml",),
}

_TIER_B = ("servix", "tala", "ticaro", "arzbin", "navasan", "nerkh_io")
_DIRECT = ("coinbase", "nobitex", "wallex")
_REFERENCE = ("goldapi", "gold_api_free", "metals_dev")

PENDING_PROVIDER_CANDIDATES = (
    "BRSAPI gold/currency",
    "BRSAPI/TSETMC equities and funds",
    "SourceArena",
    "api.ir",
    "IranMarketData.ir",
    "Oanor Iran Rial Market API",
    "legacy nerkh-api.ir",
    "TGJU paid API",
    "NovinAPI",
    "TabanGohar",
)


def provider_contract(provider: ProviderDefinition) -> ProviderContract:
    family = provider.source_family
    if family in _TIER_B:
        tier = "B"
        commercial_status = "disabled_until_operator_rights_confirmed"
        redistribution_status = "pending_operator_review"
    elif family in _DIRECT or family in _REFERENCE or family == "coingecko":
        tier = "A"
        commercial_status = "operator_must_confirm_plan"
        redistribution_status = "operator_must_confirm_terms"
    else:
        tier = "legacy_or_internal"
        commercial_status = "internal_or_deprecated"
        redistribution_status = "not_for_consensus_without_review"
    attribution_required = family in {"servix", "arzbin", "coingecko"}
    unit_contract = "parser_strict_allowlist"
    if family == "navasan":
        unit_contract = "documented_rial_to_toman_0.1"
    if family == "nerkh_io":
        unit_contract = "operator_configured_category_unit"
    if family in {"coinbase", "coingecko", "goldapi", "gold_api_free", "metals_dev"}:
        unit_contract = "documented_usd"
    endpoint = urlparse(provider.url)
    endpoint_version = endpoint.path.split("/")[1] if endpoint.path.count("/") > 1 else "root"
    return ProviderContract(
        provider_id=provider.provider_id,
        tier=tier,
        endpoint_version=endpoint_version,
        credential_placement=provider.credential_placement,
        unit_contract=unit_contract,
        source_timestamp="provider_timestamp_or_receive_time",
        redistribution_status=redistribution_status,
        commercial_status=commercial_status,
        owner="pricing-ops",
        docs=_DOCS.get(family, ()),
        attribution_required=attribution_required,
        enabled_acceptance=(
            "official_endpoint_docs_present",
            "representative_fixture_tests_pass",
            "unit_mapping_is_explicit",
            "license_or_operator_rights_confirmed",
            "source_timestamp_rule_defined",
            "credentials_not_in_url_path",
        ),
    )


def provider_contract_inventory() -> dict[str, Any]:
    return {
        "providers": {
            provider_id: provider_contract(provider).to_dict()
            for provider_id, provider in sorted(PROVIDERS.items())
        },
        "pending_candidates": list(PENDING_PROVIDER_CANDIDATES),
        "separate_domains": {
            "tsetmc_equities_and_funds": {
                "status": "future_domain",
                "current_pricing_instruments_allowed": False,
                "acceptance": [
                    "separate_instruments",
                    "separate_schema",
                    "separate_retention",
                    "separate_licensing_review",
                ],
            }
        },
    }
