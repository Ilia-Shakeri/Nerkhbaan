package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
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
	if err := validateFeed(&value, now); err != nil {
		t.Fatalf("fresh exact feed rejected: %v", err)
	}
	value.Quotes[0].InstrumentID = "GOLD_24K_TOMAN_GRAM"
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("unauthorized provider/instrument pair accepted")
	}
}

func TestValidateFeedAcceptsXausSilverFallback(t *testing.T) {
	now := time.Date(2026, 9, 19, 12, 0, 0, 0, time.UTC)
	value := feed{
		Version:   1,
		Source:    "public-market-relay",
		UpdatedAt: now.Format(time.RFC3339),
		Quotes: []quote{
			{InstrumentID: "XAG_USD_OZ", ProviderID: "xaus_xag", Price: "66.37", ObservedAt: now.Format(time.RFC3339)},
			{InstrumentID: "BTC_USD", ProviderID: "coingecko_btc", Price: "77000", ObservedAt: now.Format(time.RFC3339)},
			{InstrumentID: "USDT_USD", ProviderID: "coingecko_usdt", Price: "0.999", ObservedAt: now.Format(time.RFC3339)},
		},
	}
	if err := validateFeed(&value, now); err != nil {
		t.Fatalf("fresh XAUS fallback rejected: %v", err)
	}
	value.Quotes[1] = quote{InstrumentID: "XAG_USD_OZ", ProviderID: "gold_api_free_xag", Price: "66.4", ObservedAt: now.Format(time.RFC3339)}
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("duplicate silver route accepted")
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
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("stale feed accepted")
	}
}

func TestValidateFeedRejectsQuoteOlderThanTenMinutes(t *testing.T) {
	now := time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)
	value := feed{
		Version:   1,
		Source:    "public-market-relay",
		UpdatedAt: now.Format(time.RFC3339),
		Quotes: []quote{
			{InstrumentID: "XAG_USD_OZ", ProviderID: "gold_api_free_xag", Price: "64.6", ObservedAt: now.Add(-11 * time.Minute).Format(time.RFC3339)},
			{InstrumentID: "BTC_USD", ProviderID: "coingecko_btc", Price: "77000", ObservedAt: now.Format(time.RFC3339)},
			{InstrumentID: "USDT_USD", ProviderID: "coingecko_usdt", Price: "0.999", ObservedAt: now.Format(time.RFC3339)},
		},
	}
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("stale quote accepted")
	}
}

func TestSendUsesTrustedPublicHost(t *testing.T) {
	seenHost := ""
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		seenHost = request.Host
		response.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()

	err := send(server.Client(), config{
		endpoint: server.URL,
		secret:   strings.Repeat("x", 32),
	}, []byte(`{"quotes":[]}`))
	if err != nil {
		t.Fatalf("signed request failed: %v", err)
	}
	if seenHost != "nerkhbaan.ir" {
		t.Fatalf("unexpected trusted host: %q", seenHost)
	}
}

func TestVersionTwoPartialFeedKeepsFreshCryptoWithoutMetal(t *testing.T) {
	now := time.Date(2026, 10, 11, 12, 0, 0, 0, time.UTC)
	value := feed{Version: 2, Source: "public-market-relay", UpdatedAt: now.Format(time.RFC3339),
		Quotes: []quote{{InstrumentID: "USDT_USD", ProviderID: "coingecko_usdt", Price: "1", ObservedAt: now.Format(time.RFC3339)}}}
	if err := validateFeed(&value, now); err != nil {
		t.Fatalf("healthy partial quote rejected: %v", err)
	}
	value.Version = 1
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("legacy incomplete contract accepted")
	}
}

func TestVersionTwoAllowsExactGoldSpotPairButNoGoldKarat(t *testing.T) {
	now := time.Date(2026, 10, 11, 12, 0, 0, 0, time.UTC)
	value := feed{Version: 2, Source: "public-market-relay", UpdatedAt: now.Format(time.RFC3339),
		Quotes: []quote{{InstrumentID: "XAU_USD_OZ", ProviderID: "gold_api_free_xau", Price: "4000", ObservedAt: now.Format(time.RFC3339)}}}
	if err := validateFeed(&value, now); err != nil {
		t.Fatalf("gold spot pair rejected: %v", err)
	}
	value.Quotes[0].InstrumentID = "GOLD_24K_TOMAN_GRAM"
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("gold karat substitution accepted")
	}
}

func TestVersionTwoRejectsEmptyStaleAndDuplicate(t *testing.T) {
	now := time.Date(2026, 10, 11, 12, 0, 0, 0, time.UTC)
	value := feed{Version: 2, Source: "public-market-relay", UpdatedAt: now.Format(time.RFC3339)}
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("empty feed accepted")
	}
	item := quote{InstrumentID: "XAU_USD_OZ", ProviderID: "gold_api_free_xau", Price: "4000", ObservedAt: now.Add(-11 * time.Minute).Format(time.RFC3339)}
	value.Quotes = []quote{item}
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("stale quote accepted")
	}
	item.ObservedAt = now.Format(time.RFC3339)
	value.Quotes = []quote{item, item}
	if err := validateFeed(&value, now); err == nil {
		t.Fatal("duplicate quote accepted")
	}
}

func TestVersionTwoDropsOnlyExpiredQuoteAndKeepsFreshSibling(t *testing.T) {
	now := time.Date(2026, 10, 16, 12, 0, 0, 0, time.UTC)
	value := feed{Version: 2, Source: "public-market-relay", UpdatedAt: now.Format(time.RFC3339), Quotes: []quote{
		{InstrumentID: "XAU_USD_OZ", ProviderID: "gold_api_free_xau", Price: "4000", ObservedAt: now.Add(-11 * time.Minute).Format(time.RFC3339)},
		{InstrumentID: "USDT_USD", ProviderID: "coingecko_usdt", Price: "1", ObservedAt: now.Format(time.RFC3339)},
	}}
	if err := validateFeed(&value, now); err != nil {
		t.Fatalf("fresh sibling blocked by expired quote: %v", err)
	}
	if len(value.Quotes) != 1 || value.Quotes[0].InstrumentID != "USDT_USD" {
		t.Fatalf("ingest selection contains expired quote: %+v", value.Quotes)
	}
}

func TestRunOnceForwardsOnlyFreshVersionTwoQuotes(t *testing.T) {
	now := time.Now().UTC()
	value := feed{Version: 2, Source: "public-market-relay", UpdatedAt: now.Format(time.RFC3339Nano), Quotes: []quote{
		{InstrumentID: "XAU_USD_OZ", ProviderID: "gold_api_free_xau", Price: "4000", ObservedAt: now.Add(-11 * time.Minute).Format(time.RFC3339Nano)},
		{InstrumentID: "USDT_USD", ProviderID: "coingecko_usdt", Price: "1", ObservedAt: now.Format(time.RFC3339Nano)},
	}}
	body, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	repository := t.TempDir()
	if err := os.WriteFile(filepath.Join(repository, "prices.json"), body, 0600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{
		{"init", "--quiet", repository},
		{"-C", repository, "add", "prices.json"},
		{"-C", repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture"},
	} {
		if err := runGit(context.Background(), args...); err != nil {
			t.Fatal(err)
		}
	}
	receivedQuotes := make(chan ingest, 1)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		var received ingest
		if err := json.NewDecoder(request.Body).Decode(&received); err != nil {
			t.Error(err)
		}
		receivedQuotes <- received
		response.WriteHeader(http.StatusAccepted)
	}))
	defer server.Close()
	updated, err := runOnce(server.Client(), config{repository: repository, ref: "HEAD", endpoint: server.URL, secret: strings.Repeat("x", 32)}, "")
	if err != nil {
		t.Fatalf("fresh sibling was not forwarded: %v", err)
	}
	received := <-receivedQuotes
	if updated != value.UpdatedAt || len(received.Quotes) != 1 || received.Quotes[0].InstrumentID != "USDT_USD" {
		t.Fatalf("wrong ingest selection: update=%s quotes=%+v", updated, received.Quotes)
	}
}
