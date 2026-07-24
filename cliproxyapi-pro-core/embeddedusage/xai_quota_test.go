package embeddedusage

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"
	"time"
)

func TestXAIRateLimitSnapshotRequiresCompleteTokenPair(t *testing.T) {
	now := time.Unix(100, 0)
	if got := xaiRateLimitSnapshot(http.Header{"X-Ratelimit-Limit-Tokens": {"100"}}, "grok", now); got != nil {
		t.Fatalf("partial snapshot = %#v, want nil", got)
	}
	header := http.Header{
		"X-Ratelimit-Limit-Tokens":       {"100"},
		"X-Ratelimit-Remaining-Tokens":   {"40"},
		"X-Ratelimit-Limit-Requests":     {"12"},
		"X-Ratelimit-Remaining-Requests": {"7"},
	}
	got := xaiRateLimitSnapshot(header, "grok-free", now)
	if got["usedTokens"] != int64(60) || got["remainingTokens"] != int64(40) || got["model"] != "grok-free" {
		t.Fatalf("snapshot = %#v", got)
	}
}

func TestObserveXAIQuotaAcceptsWebsocketHandshakeHeaders(t *testing.T) {
	if !xaiQuotaHeadersStatus(http.StatusSwitchingProtocols) {
		t.Fatal("websocket switching-protocols status should allow rate-limit headers")
	}
	header := http.Header{
		"X-Ratelimit-Limit-Tokens":     {"100"},
		"X-Ratelimit-Remaining-Tokens": {"40"},
	}
	if got := xaiRateLimitSnapshot(header, "grok-free", time.Unix(100, 0)); got == nil {
		t.Fatal("websocket handshake rate-limit headers should produce a snapshot")
	}
}

func TestXAIExhaustedQuotaSnapshotParsesUsageAndModel(t *testing.T) {
	body := []byte(`{"code":"subscription:free-usage-exhausted","error":"You've used all the included free usage for model grok-4.5-build-free. tokens (actual/limit): 1003617/1000000."}`)
	if !xaiFreeQuotaExhausted(body) {
		t.Fatal("free quota exhaustion not detected")
	}
	got := xaiExhaustedQuotaSnapshot(body, "", time.Unix(200, 0))
	if got["usedTokens"] != int64(1003617) || got["limitTokens"] != int64(1000000) || got["model"] != "grok-4.5-build-free" {
		t.Fatalf("snapshot = %#v", got)
	}
}

func TestMergeXAIQuotaStatePreservesNewerFreeQuotaAndBilling(t *testing.T) {
	existing := map[string]any{
		"status": "success",
		"billing": map[string]any{
			"monthlyLimitCents": float64(20000),
			"freeQuota":         map[string]any{"observedAt": float64(200), "remainingTokens": float64(10)},
		},
	}
	incoming := map[string]any{
		"status": "success",
		"billing": map[string]any{
			"usagePercent": float64(25),
			"freeQuota":    map[string]any{"observedAt": float64(100), "remainingTokens": float64(80)},
		},
	}
	merged := mergeXAIQuotaState(existing, incoming)
	billing := merged["billing"].(map[string]any)
	freeQuota := billing["freeQuota"].(map[string]any)
	if billing["monthlyLimitCents"] != float64(20000) || billing["usagePercent"] != float64(25) {
		t.Fatalf("billing = %#v", billing)
	}
	if freeQuota["remainingTokens"] != float64(10) {
		t.Fatalf("freeQuota = %#v, want newer existing observation", freeQuota)
	}
}

func TestMergeXAIQuotaStatePreservesFreeQuotaWhenBillingRefreshOmitsIt(t *testing.T) {
	existing := map[string]any{
		"billing": map[string]any{
			"freeQuota": map[string]any{"observedAt": float64(200), "remainingTokens": float64(10)},
		},
	}
	incoming := map[string]any{
		"billing": map[string]any{"monthlyLimitCents": float64(15000)},
	}
	merged := mergeXAIQuotaState(existing, incoming)
	billing := merged["billing"].(map[string]any)
	if billing["monthlyLimitCents"] != float64(15000) {
		t.Fatalf("billing = %#v", billing)
	}
	freeQuota := billing["freeQuota"].(map[string]any)
	if freeQuota["remainingTokens"] != float64(10) {
		t.Fatalf("freeQuota = %#v", freeQuota)
	}
}

func TestStoreMergeXAIQuotaCachePreservesRequestObservation(t *testing.T) {
	store := openTestStore(t)
	ctx := context.Background()
	freeState := json.RawMessage(`{"status":"success","billing":{"freeQuota":{"observedAt":200,"remainingTokens":10}}}`)
	if err := store.MergeXAIQuotaCache(ctx, QuotaCacheEntry{
		Provider: "xai", FileName: "free.json", Data: freeState, CachedAt: 200, ObservedAt: 200,
	}); err != nil {
		t.Fatalf("MergeXAIQuotaCache(free) error = %v", err)
	}
	billingState := json.RawMessage(`{"status":"success","billing":{"planType":"free","monthlyLimitCents":null}}`)
	if err := store.MergeXAIQuotaCache(ctx, QuotaCacheEntry{
		Provider: "xai", FileName: "free.json", Data: billingState, CachedAt: 300, ObservedAt: 300,
	}); err != nil {
		t.Fatalf("MergeXAIQuotaCache(billing) error = %v", err)
	}
	entries, err := store.GetQuotaCache(ctx, "xai", "free.json")
	if err != nil || len(entries) != 1 {
		t.Fatalf("GetQuotaCache() = %+v, %v", entries, err)
	}
	state := map[string]any{}
	if err := json.Unmarshal(entries[0].Data, &state); err != nil {
		t.Fatalf("json.Unmarshal() error = %v", err)
	}
	billing := state["billing"].(map[string]any)
	if billing["planType"] != "free" || billing["freeQuota"].(map[string]any)["remainingTokens"] != float64(10) {
		t.Fatalf("merged billing = %#v", billing)
	}
}
