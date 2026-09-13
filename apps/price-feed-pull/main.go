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
	"log"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

type quote struct {
	InstrumentID string `json:"instrument_id"`
	ProviderID   string `json:"provider_id"`
	Price        string `json:"price"`
	ObservedAt   string `json:"observed_at"`
	Historical   bool   `json:"historical"`
}

type feed struct {
	Version   int     `json:"feed_version"`
	Source    string  `json:"source"`
	UpdatedAt string  `json:"updated_at"`
	Quotes    []quote `json:"quotes"`
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
	payload, err := fetchFeed(cfg)
	if err != nil {
		return "", err
	}
	var current feed
	if err := json.Unmarshal(payload, &current); err != nil {
		return "", fmt.Errorf("decode feed: %w", err)
	}
	if err := validateFeed(current, time.Now().UTC()); err != nil {
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

func validateFeed(value feed, now time.Time) error {
	if value.Version != 1 || value.Source != "public-market-relay" {
		return errors.New("unsupported price feed contract")
	}
	updated, err := time.Parse(time.RFC3339Nano, value.UpdatedAt)
	if err != nil || updated.After(now.Add(5*time.Minute)) || now.Sub(updated) > maximumFeedAge {
		return errors.New("price feed timestamp is outside the safe window")
	}
	expected := map[string]string{
		"gold_api_free_xag": "XAG_USD_OZ",
		"coingecko_btc":     "BTC_USD",
		"coingecko_usdt":    "USDT_USD",
	}
	if len(value.Quotes) != len(expected) {
		return errors.New("price feed must contain exactly three quotes")
	}
	seen := map[string]bool{}
	for _, item := range value.Quotes {
		if expected[item.ProviderID] != item.InstrumentID || item.Historical {
			return errors.New("price feed contains an unauthorized route")
		}
		if seen[item.ProviderID] {
			return errors.New("price feed contains a duplicate provider")
		}
		seen[item.ProviderID] = true
		observed, err := time.Parse(time.RFC3339Nano, item.ObservedAt)
		if err != nil || observed.After(now.Add(5*time.Minute)) || now.Sub(observed) > maximumFeedAge {
			return errors.New("quote timestamp is outside the safe window")
		}
		price, err := strconv.ParseFloat(item.Price, 64)
		if err != nil || !safePrice(item.InstrumentID, price) {
			return errors.New("quote price is outside the safe range")
		}
	}
	return nil
}

func safePrice(instrument string, price float64) bool {
	switch instrument {
	case "XAG_USD_OZ":
		return price >= 5 && price <= 500
	case "BTC_USD":
		return price >= 1000 && price <= 1000000
	case "USDT_USD":
		return price >= 0.8 && price <= 1.2
	default:
		return false
	}
}

func send(client *http.Client, cfg config, body []byte) error {
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
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("send ingest request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusAccepted {
		return fmt.Errorf("ingest returned status %d", response.StatusCode)
	}
	return nil
}
