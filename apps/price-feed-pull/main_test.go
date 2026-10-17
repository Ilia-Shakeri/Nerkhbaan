package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func ownedFeed(now time.Time, symbols ...string) feed {
	value := feed{Version: 3, Source: "own-app-market-feed", Audience: "nerkhbaan-own-app", UpdatedAt: now.Format(time.RFC3339Nano), Attributions: []credit{{Label: "Gold API", URL: "https://gold-api.com/"}}}
	for _, symbol := range symbols {
		instrument, provider, unit, price := "", "", "troy_ounce", ""
		switch symbol {
		case "XAU":
			instrument, provider, price = "XAU_USD_OZ", "gold_api_free_xau", "4000"
		case "XAG":
			instrument, provider, price = "XAG_USD_OZ", "gold_api_free_xag", "50"
		case "BTC":
			instrument, provider, unit, price = "BTC_USD", "gold_api_free_btc", "unit", "90000"
		}
		value.Quotes = append(value.Quotes, quote{InstrumentID: instrument, ProviderID: provider, Price: price, ObservedAt: now.Format(time.RFC3339Nano), Currency: "USD", WeightUnit: unit, SourceURL: "https://api.gold-api.com/price/" + symbol, Attributions: value.Attributions})
	}
	return value
}

func TestVersionThreeAcceptsOnlyThreeApprovedRoutes(t *testing.T) {
	now := time.Now().UTC()
	value := ownedFeed(now, "XAU", "XAG", "BTC")
	if err := validateFeed(&value, now); err != nil {
		t.Fatal(err)
	}
	for _, version := range []int{1, 2} {
		value = ownedFeed(now, "BTC")
		value.Version = version
		if validateFeed(&value, now) == nil {
			t.Fatalf("legacy version %d accepted", version)
		}
	}
}

func TestRestrictedOrUnknownRoutesCannotEnterFeed(t *testing.T) {
	now := time.Now().UTC()
	for _, provider := range []string{"coingecko_btc", "coingecko_usdt", "coinbase_btc_usd", "xaus_xag", "unknown"} {
		value := ownedFeed(now, "BTC")
		value.Quotes[0].ProviderID = provider
		if validateFeed(&value, now) == nil {
			t.Fatalf("restricted route %s accepted", provider)
		}
	}
	value := ownedFeed(now, "BTC")
	value.Quotes[0].InstrumentID = "USDT_USD"
	value.Quotes[0].Price = "1"
	if validateFeed(&value, now) == nil {
		t.Fatal("fabricated stablecoin route accepted")
	}
}

func TestCurrencyUnitsAttributionAndAudienceAreRequired(t *testing.T) {
	now := time.Now().UTC()
	changes := []func(*feed){
		func(v *feed) { v.Quotes[0].Currency = "EUR" },
		func(v *feed) { v.Quotes[0].WeightUnit = "gram" },
		func(v *feed) { v.Quotes[0].SourceURL = "https://example.invalid/" },
		func(v *feed) { v.Quotes[0].Attributions = nil },
		func(v *feed) { v.Attributions = nil },
		func(v *feed) { v.Audience = "public-resale" },
		func(v *feed) { v.Quotes[0].Historical = true },
		func(v *feed) { v.Quotes = append(v.Quotes, v.Quotes[0]) },
	}
	for index, change := range changes {
		value := ownedFeed(now, "XAU")
		change(&value)
		if validateFeed(&value, now) == nil {
			t.Fatalf("invalid metadata %d accepted", index)
		}
	}
}

func TestFiniteBoundsAndSourceClockAreRequired(t *testing.T) {
	now := time.Now().UTC()
	for _, price := range []string{"NaN", "+Inf", "-Inf", "0", "-1", "999999999", "no-price"} {
		value := ownedFeed(now, "BTC")
		value.Quotes[0].Price = price
		if validateFeed(&value, now) == nil {
			t.Fatalf("invalid price %s accepted", price)
		}
	}
	for _, stamp := range []string{"", now.Format("2006-01-02T15:04:05"), now.Add(6 * time.Minute).Format(time.RFC3339), now.Add(-11 * time.Minute).Format(time.RFC3339)} {
		value := ownedFeed(now, "BTC")
		value.Quotes[0].ObservedAt = stamp
		if validateFeed(&value, now) == nil {
			t.Fatalf("invalid timestamp %s accepted", stamp)
		}
	}
}

func TestExpiredSiblingIsRemovedWithoutInventingReplacement(t *testing.T) {
	now := time.Now().UTC()
	value := ownedFeed(now, "XAU", "BTC")
	value.Quotes[0].ObservedAt = now.Add(-11 * time.Minute).Format(time.RFC3339)
	if err := validateFeed(&value, now); err != nil {
		t.Fatal(err)
	}
	if len(value.Quotes) != 1 || value.Quotes[0].InstrumentID != "BTC_USD" {
		t.Fatal("wrong fresh selection")
	}
}

func TestManifestRevocationAndInvalidFileAreImmediate(t *testing.T) {
	now := time.Now().UTC()
	path := filepath.Join(t.TempDir(), "rights.json")
	t.Setenv("PRICING_RIGHTS_MANIFEST_PATH", path)
	grant := map[string]any{"permissions": []string{"collect", "store", "own_app_transport"}, "checked_at": now.Add(-time.Hour).Format(time.RFC3339), "expires_at": now.Add(time.Hour).Format(time.RFC3339), "evidence_ref": "https://gold-api.com/terms", "hosts": []string{"api.gold-api.com"}}
	manifest := map[string]any{"schema_version": 1, "environment": "production", "providers": map[string]any{"gold_api_free_btc": grant}}
	body, _ := json.Marshal(manifest)
	if err := os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	if !sourceAllowed("gold_api_free_btc", now) {
		t.Fatal("reviewed grant denied")
	}
	grant["permissions"] = []string{"collect", "store"}
	body, _ = json.Marshal(manifest)
	os.WriteFile(path, body, 0600)
	if sourceAllowed("gold_api_free_btc", now) {
		t.Fatal("revoked transport accepted")
	}
	os.WriteFile(path, []byte("{"), 0600)
	if sourceAllowed("gold_api_free_btc", now) {
		t.Fatal("invalid manifest accepted")
	}
}

func TestMissingPermissionStopsBeforeRepositoryFetch(t *testing.T) {
	t.Setenv("PRICING_RIGHTS_MANIFEST_PATH", filepath.Join(t.TempDir(), "missing.json"))
	_, err := runOnce(&http.Client{}, config{repository: "not-an-authorized-repository"}, "")
	if err == nil || !strings.Contains(err.Error(), "permission") {
		t.Fatalf("expected permission failure before git: %v", err)
	}
}

func TestSendSignsTrustedHostAndRequiresPublishedAcknowledgement(t *testing.T) {
	now := time.Now().UTC()
	value := ownedFeed(now, "BTC")
	body, _ := json.Marshal(ingest{Quotes: value.Quotes})
	secret := strings.Repeat("x", 32)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != "nerkhbaan.ir" {
			t.Errorf("unexpected host %s", r.Host)
		}
		received, _ := io.ReadAll(r.Body)
		timestamp := r.Header.Get("X-Pricing-Worker-Timestamp")
		mac := hmac.New(sha256.New, []byte(secret))
		mac.Write([]byte(timestamp))
		mac.Write([]byte("."))
		mac.Write(received)
		if !hmac.Equal([]byte(r.Header.Get("X-Pricing-Worker-Signature")), []byte(hex.EncodeToString(mac.Sum(nil)))) {
			t.Error("invalid signature")
		}
		w.WriteHeader(http.StatusAccepted)
		w.Write([]byte("{\"accepted\":1,\"published\":1}"))
	}))
	defer server.Close()
	if err := send(server.Client(), config{endpoint: server.URL, secret: secret}, body); err != nil {
		t.Fatal(err)
	}
}

func TestIgnoredAcknowledgementIsNotSuccess(t *testing.T) {
	value := ownedFeed(time.Now().UTC(), "BTC")
	body, _ := json.Marshal(ingest{Quotes: value.Quotes})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
		w.Write([]byte("{\"accepted\":1,\"published\":0}"))
	}))
	defer server.Close()
	if send(server.Client(), config{endpoint: server.URL, secret: strings.Repeat("x", 32)}, body) == nil {
		t.Fatal("ignored quote acknowledged as published")
	}
}

func TestIngestRedirectNeverForwardsPrivateBody(t *testing.T) {
	value := ownedFeed(time.Now().UTC(), "BTC")
	body, _ := json.Marshal(ingest{Quotes: value.Quotes})
	calls := 0
	destination := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++ }))
	defer destination.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, destination.URL, http.StatusTemporaryRedirect)
	}))
	defer server.Close()
	if send(server.Client(), config{endpoint: server.URL, secret: strings.Repeat("x", 32)}, body) == nil || calls != 0 {
		t.Fatal("redirect forwarded private ingest")
	}
}

func TestRunOnceForwardsOnlyFreshApprovedQuotesFromOwnedRepository(t *testing.T) {
	now := time.Now().UTC()
	value := ownedFeed(now, "XAU", "BTC")
	value.Quotes[0].ObservedAt = now.Add(-11 * time.Minute).Format(time.RFC3339Nano)
	body, _ := json.Marshal(value)
	repository := t.TempDir()
	if err := os.WriteFile(filepath.Join(repository, "prices.json"), body, 0600); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"init", "--quiet", repository}, {"-C", repository, "add", "prices.json"}, {"-C", repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture"}} {
		if err := runGit(context.Background(), args...); err != nil {
			t.Fatal(err)
		}
	}
	receivedQuotes := make(chan ingest, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var received ingest
		json.NewDecoder(r.Body).Decode(&received)
		receivedQuotes <- received
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(map[string]int{"accepted": len(received.Quotes), "published": len(received.Quotes)})
	}))
	defer server.Close()
	updated, err := runOnce(server.Client(), config{repository: repository, ref: "HEAD", endpoint: server.URL, secret: strings.Repeat("x", 32)}, "")
	if err != nil {
		t.Fatal(err)
	}
	received := <-receivedQuotes
	if updated != value.UpdatedAt || len(received.Quotes) != 1 || received.Quotes[0].InstrumentID != "BTC_USD" {
		t.Fatal("wrong ingest selection")
	}
}
