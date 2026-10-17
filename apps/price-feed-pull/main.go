package main

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type quote struct {
	InstrumentID string   `json:"instrument_id"`
	ProviderID   string   `json:"provider_id"`
	Price        string   `json:"price"`
	ObservedAt   string   `json:"observed_at"`
	Historical   bool     `json:"historical"`
	Currency     string   `json:"currency"`
	WeightUnit   string   `json:"weight_unit"`
	SourceURL    string   `json:"source_url"`
	Attributions []credit `json:"attributions"`
}

type credit struct {
	Label string `json:"label"`
	URL   string `json:"url"`
}

type feed struct {
	Version      int      `json:"feed_version"`
	Source       string   `json:"source"`
	UpdatedAt    string   `json:"updated_at"`
	Quotes       []quote  `json:"quotes"`
	Audience     string   `json:"audience"`
	Attributions []credit `json:"attributions"`
}

type ingest struct {
	Quotes []quote `json:"quotes"`
}

type config struct {
	repository string
	ref        string
	endpoint   string
	secret     string
	interval   time.Duration
}

const gitCommandTimeout = 60 * time.Second
const maximumFeedAge = 10 * time.Minute

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatal(err)
	}
	client := &http.Client{Timeout: 20 * time.Second}
	lastUpdate := ""
	log.Printf("price feed pull started")
	for {
		update, err := runOnce(client, cfg, lastUpdate)
		if err != nil {
			log.Printf("price feed pull failed: %v", err)
		} else if update != "" {
			lastUpdate = update
			log.Printf("price feed accepted at %s", update)
		}
		time.Sleep(cfg.interval)
	}
}

func loadConfig() (config, error) {
	seconds, err := strconv.Atoi(env("PRICE_FEED_POLL_SECONDS", "60"))
	if err != nil || seconds < 30 || seconds > 3600 {
		return config{}, errors.New("PRICE_FEED_POLL_SECONDS must be between 30 and 3600")
	}
	cfg := config{
		repository: env("PRICE_FEED_REPOSITORY", "https://github.com/Ilia-Shakeri/Nerkhbaan.git"),
		ref:        env("PRICE_FEED_REF", "price-feed"),
		endpoint:   env("PRICE_FEED_INGEST_ENDPOINT", "http://backend:8000/api/internal/pricing-worker/ingest"),
		secret:     strings.TrimSpace(os.Getenv("NERKHBAAN_WORKER_SECRET")),
		interval:   time.Duration(seconds) * time.Second,
	}
	if len(cfg.secret) < 32 {
		return config{}, errors.New("NERKHBAAN_WORKER_SECRET must be at least 32 characters")
	}
	return cfg, nil
}

func env(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func runOnce(client *http.Client, cfg config, lastUpdate string) (string, error) {
	for _, provider := range []string{"gold_api_free_xau", "gold_api_free_xag", "gold_api_free_btc"} {
		if !sourceAllowed(provider, time.Now().UTC()) {
			return "", errors.New("application feed transport permission unavailable")
		}
	}
	payload, err := fetchFeed(cfg)
	if err != nil {
		return "", err
	}
	var current feed
	if err := json.Unmarshal(payload, &current); err != nil {
		return "", fmt.Errorf("decode feed: %w", err)
	}
	if err := validateFeed(&current, time.Now().UTC()); err != nil {
		return "", err
	}
	if current.UpdatedAt == lastUpdate {
		return "", nil
	}
	body, err := json.Marshal(ingest{Quotes: current.Quotes})
	if err != nil {
		return "", fmt.Errorf("encode ingest: %w", err)
	}
	if err := send(client, cfg, body); err != nil {
		return "", err
	}
	return current.UpdatedAt, nil
}

func fetchFeed(cfg config) ([]byte, error) {
	directory, err := os.MkdirTemp("", "nerkhbaan-price-feed-")
	if err != nil {
		return nil, fmt.Errorf("make temp repository: %w", err)
	}
	defer os.RemoveAll(directory)
	ctx, cancel := context.WithTimeout(context.Background(), gitCommandTimeout)
	defer cancel()
	if err := runGit(ctx, "init", "--quiet", directory); err != nil {
		return nil, err
	}
	if err := runGit(
		ctx,
		"-C", directory, "-c", "http.version=HTTP/1.1", "fetch", "--quiet",
		"--depth=1", cfg.repository, cfg.ref,
	); err != nil {
		return nil, err
	}
	command := exec.CommandContext(ctx, "git", "-C", directory, "show", "FETCH_HEAD:prices.json")
	command.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
	output, err := command.Output()
	if err != nil {
		return nil, fmt.Errorf("read price feed from git: %w", err)
	}
	return output, nil
}

func runGit(ctx context.Context, args ...string) error {
	command := exec.CommandContext(ctx, "git", args...)
	command.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
	if err := command.Run(); err != nil {
		return fmt.Errorf("git %s failed: %w", args[0], err)
	}
	return nil
}

func validateFeed(value *feed, now time.Time) error {
	if value.Version != 3 || value.Source != "own-app-market-feed" || value.Audience != "nerkhbaan-own-app" || !validCredit(value.Attributions) {
		return errors.New("unsupported price feed contract")
	}
	updated, err := time.Parse(time.RFC3339Nano, value.UpdatedAt)
	if err != nil || updated.After(now.Add(5*time.Minute)) || now.Sub(updated) > maximumFeedAge {
		return errors.New("price feed timestamp is outside the safe window")
	}
	allowed := map[string]string{
		"gold_api_free_xag": "XAG_USD_OZ",
		"gold_api_free_xau": "XAU_USD_OZ",
		"gold_api_free_btc": "BTC_USD",
	}
	if len(value.Quotes) < 1 || len(value.Quotes) > 3 {
		return errors.New("application feed must contain one to three quotes")
	}
	seenProviders := map[string]bool{}
	seenInstruments := map[string]bool{}
	fresh := make([]quote, 0, len(value.Quotes))
	for _, item := range value.Quotes {
		if allowed[item.ProviderID] != item.InstrumentID || item.Historical {
			return errors.New("price feed contains an unauthorized route")
		}
		if !sourceAllowed(item.ProviderID, now) {
			return errors.New("source transport permission unavailable")
		}
		symbol, unit := "", "troy_ounce"
		switch item.ProviderID {
		case "gold_api_free_xau":
			symbol = "XAU"
		case "gold_api_free_xag":
			symbol = "XAG"
		case "gold_api_free_btc":
			symbol, unit = "BTC", "unit"
		}
		if item.Currency != "USD" || item.WeightUnit != unit || item.SourceURL != "https://api.gold-api.com/price/"+symbol || !validCredit(item.Attributions) {
			return errors.New("source currency, unit or attribution changed")
		}
		if seenProviders[item.ProviderID] || seenInstruments[item.InstrumentID] {
			return errors.New("price feed contains a duplicate route")
		}
		seenProviders[item.ProviderID] = true
		seenInstruments[item.InstrumentID] = true
		observed, err := time.Parse(time.RFC3339Nano, item.ObservedAt)
		if err != nil || observed.After(now.Add(5*time.Minute)) {
			return errors.New("quote timestamp is outside the safe window")
		}
		price, err := strconv.ParseFloat(item.Price, 64)
		if err != nil || !safePrice(item.InstrumentID, price) {
			return errors.New("quote price is outside the safe range")
		}
		if now.Sub(observed) > maximumFeedAge {
			continue
		}
		fresh = append(fresh, item)
	}
	if len(fresh) == 0 {
		return errors.New("price feed contains no fresh quotes")
	}
	value.Quotes = fresh
	return nil
}

func safePrice(instrument string, price float64) bool {
	switch instrument {
	case "XAG_USD_OZ":
		return price >= 5 && price <= 500
	case "XAU_USD_OZ":
		return price >= 500 && price <= 10000
	case "BTC_USD":
		return price >= 1000 && price <= 1000000
	default:
		return false
	}
}

func validCredit(values []credit) bool {
	return len(values) == 1 && values[0].Label == "Gold API" && values[0].URL == "https://gold-api.com/"
}

func sourceAllowed(provider string, now time.Time) bool {
	if provider != "gold_api_free_xau" && provider != "gold_api_free_xag" && provider != "gold_api_free_btc" {
		return false
	}
	path := os.Getenv("PRICING_RIGHTS_MANIFEST_PATH")
	if path == "" {
		return !now.Before(time.Date(2026, 10, 17, 0, 0, 0, 0, time.UTC)) && now.Before(time.Date(2027, 1, 15, 0, 0, 0, 0, time.UTC))
	}
	if !filepath.IsAbs(path) {
		return false
	}
	file, err := os.Open(path)
	if err != nil {
		return false
	}
	defer file.Close()
	body, err := io.ReadAll(io.LimitReader(file, 262145))
	if err != nil || len(body) > 262144 {
		return false
	}
	var manifest struct {
		Version     int    `json:"schema_version"`
		Environment string `json:"environment"`
		Providers   map[string]struct {
			Permissions []string `json:"permissions"`
			Checked     string   `json:"checked_at"`
			Expires     string   `json:"expires_at"`
			Evidence    string   `json:"evidence_ref"`
			Hosts       []string `json:"hosts"`
		} `json:"providers"`
	}
	if json.Unmarshal(body, &manifest) != nil || manifest.Version != 1 || manifest.Environment != "production" {
		return false
	}
	grant, ok := manifest.Providers[provider]
	if !ok {
		return false
	}
	checked, err := time.Parse(time.RFC3339Nano, grant.Checked)
	if err != nil {
		return false
	}
	expires, err := time.Parse(time.RFC3339Nano, grant.Expires)
	if err != nil || now.Before(checked) || !now.Before(expires) || expires.Sub(checked) > 366*24*time.Hour {
		return false
	}
	evidence, err := url.Parse(grant.Evidence)
	if err != nil || evidence.Scheme != "https" || evidence.Hostname() == "" || evidence.User != nil {
		return false
	}
	allowedActions := map[string]bool{"collect": true, "store": true, "display": true, "history": true, "derive": true, "own_app_transport": true, "external_processing": true, "relay": true}
	permissions := map[string]bool{}
	for _, action := range grant.Permissions {
		if !allowedActions[action] {
			return false
		}
		permissions[action] = true
	}
	hostAllowed := false
	for _, host := range grant.Hosts {
		if host == "api.gold-api.com" {
			hostAllowed = true
		}
	}
	return hostAllowed && permissions["collect"] && permissions["store"] && permissions["own_app_transport"]
}

func send(client *http.Client, cfg config, body []byte) error {
	var contents ingest
	if json.Unmarshal(body, &contents) != nil {
		return errors.New("invalid ingest payload")
	}
	current := feed{Version: 3, Source: "own-app-market-feed", Audience: "nerkhbaan-own-app", UpdatedAt: time.Now().UTC().Format(time.RFC3339Nano), Quotes: contents.Quotes, Attributions: []credit{{Label: "Gold API", URL: "https://gold-api.com/"}}}
	if err := validateFeed(&current, time.Now().UTC()); err != nil {
		return err
	}
	if len(current.Quotes) != len(contents.Quotes) {
		return errors.New("ingest contains expired observations")
	}
	timestamp := strconv.FormatInt(time.Now().Unix(), 10)
	mac := hmac.New(sha256.New, []byte(cfg.secret))
	mac.Write([]byte(timestamp))
	mac.Write([]byte("."))
	mac.Write(body)
	signature := hex.EncodeToString(mac.Sum(nil))
	request, err := http.NewRequestWithContext(context.Background(), http.MethodPost, cfg.endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("create ingest request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Pricing-Worker-Timestamp", timestamp)
	request.Header.Set("X-Pricing-Worker-Signature", signature)
	request.Host = "nerkhbaan.ir"
	boundedClient := *client
	boundedClient.CheckRedirect = func(_ *http.Request, _ []*http.Request) error { return errors.New("ingest redirect refused") }
	response, err := boundedClient.Do(request)
	if err != nil {
		return fmt.Errorf("send ingest request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusAccepted {
		return fmt.Errorf("ingest returned status %d", response.StatusCode)
	}
	var result struct {
		Accepted  int `json:"accepted"`
		Published int `json:"published"`
	}
	if json.NewDecoder(io.LimitReader(response.Body, 4096)).Decode(&result) != nil || result.Accepted != len(contents.Quotes) || result.Published != len(contents.Quotes) {
		return errors.New("ingest did not acknowledge every published observation")
	}
	return nil
}
