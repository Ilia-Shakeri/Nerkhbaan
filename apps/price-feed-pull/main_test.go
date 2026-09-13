package main

import (
	"testing"
	"time"
)

func TestValidateFeedAcceptsOnlyExactFreshRoutes(t *testing.T) {
	now := time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)
	value := feed{
		Version:   1,
		Source:    "public-market-relay",
		UpdatedAt: now.Format(time.RFC3339),
		Quotes: []quote{
			{InstrumentID: "XAG_USD_OZ", ProviderID: "gold_api_free_xag", Price: "64.6", ObservedAt: now.Format(time.RFC3339)},
			{InstrumentID: "BTC_USD", ProviderID: "coingecko_btc", Price: "77000", ObservedAt: now.Format(time.RFC3339)},
			{InstrumentID: "USDT_USD", ProviderID: "coingecko_usdt", Price: "0.999", ObservedAt: now.Format(time.RFC3339)},
		},
	}
	if err := validateFeed(value, now); err != nil {
		t.Fatalf("fresh exact feed rejected: %v", err)
	}
	value.Quotes[0].InstrumentID = "GOLD_24K_TOMAN_GRAM"
	if err := validateFeed(value, now); err == nil {
		t.Fatal("unauthorized provider/instrument pair accepted")
	}
}

func TestValidateFeedRejectsStaleFeed(t *testing.T) {
	now := time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)
	value := feed{
		Version:   1,
		Source:    "public-market-relay",
		UpdatedAt: now.Add(-3 * time.Hour).Format(time.RFC3339),
		Quotes:    make([]quote, 3),
	}
	if err := validateFeed(value, now); err == nil {
		t.Fatal("stale feed accepted")
	}
}
