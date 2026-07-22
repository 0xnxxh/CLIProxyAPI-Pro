package pluginhost

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"

	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

const (
	legacyGeminiCLIProvider      = "gemini-cli"
	legacyGeminiCLICodeAssistURL = "https://cloudcode-pa.googleapis.com/v1internal:"
	legacyGeminiCLIMaxBodyBytes  = 4 << 20
	legacyGeminiCLIGoogleOneAI   = "GOOGLE_ONE_AI"
)

func (h *Host) legacyQuotaProviderForRecord(record capabilityRecord) (string, bool) {
	if h == nil || record.plugin.Capabilities.QuotaProvider != nil {
		return "", false
	}
	executor := record.plugin.Capabilities.Executor
	if executor == nil || h.isPluginFused(record.id) {
		return "", false
	}
	provider, okProvider := h.executorProvider(record, executor)
	if !okProvider || provider != legacyGeminiCLIProvider {
		return "", false
	}
	return provider, true
}

func (h *Host) legacyQuotaAdapter(provider string) (capabilityRecord, bool) {
	if h == nil || normalizeProviderID(provider) != legacyGeminiCLIProvider {
		return capabilityRecord{}, false
	}
	for _, record := range h.activeRecords() {
		if candidate, okCandidate := h.legacyQuotaProviderForRecord(record); okCandidate && candidate == legacyGeminiCLIProvider {
			return record, true
		}
	}
	return capabilityRecord{}, false
}

func (h *Host) fetchLegacyGeminiCLIQuota(ctx context.Context, auth *coreauth.Auth) (pluginapi.QuotaFetchResponse, error) {
	projectID := legacyGeminiCLIProjectID(auth)
	if projectID == "" {
		return pluginapi.QuotaFetchResponse{}, fmt.Errorf("gemini-cli project_id is required")
	}

	var quotaPayload map[string]any
	if errQuota := h.callLegacyGeminiCLIEndpoint(ctx, auth, "retrieveUserQuota", map[string]any{"project": projectID}, &quotaPayload); errQuota != nil {
		return pluginapi.QuotaFetchResponse{}, fmt.Errorf("retrieve user quota: %w", errQuota)
	}
	observedAt := time.Now().UnixMilli()
	items := legacyGeminiCLIQuotaItems(quotaPayload)
	if len(items) == 0 {
		return pluginapi.QuotaFetchResponse{}, fmt.Errorf("retrieve user quota returned no supported buckets")
	}
	response := pluginapi.QuotaFetchResponse{Snapshot: pluginapi.QuotaSnapshot{
		SchemaVersion: pluginapi.QuotaSnapshotSchemaVersion,
		Provider:      legacyGeminiCLIProvider,
		ObservedAtMS:  observedAt,
		Items:         items,
		Metadata:      map[string]any{"project_id": projectID, "quota_mode": "legacy-adapter"},
	}}

	planRequest := map[string]any{
		"cloudaicompanionProject": projectID,
		"metadata": map[string]any{
			"ideType": "IDE_UNSPECIFIED", "platform": "PLATFORM_UNSPECIFIED",
			"pluginType": "GEMINI", "duetProject": projectID,
		},
	}
	var planPayload map[string]any
	if errPlan := h.callLegacyGeminiCLIEndpoint(ctx, auth, "loadCodeAssist", planRequest, &planPayload); errPlan != nil {
		response.PlanUnavailable = true
		response.PlanError = errPlan.Error()
		return response, nil
	}
	response.Snapshot.Plan = legacyGeminiCLIQuotaPlan(planPayload, observedAt)
	return response, nil
}

func (h *Host) callLegacyGeminiCLIEndpoint(ctx context.Context, auth *coreauth.Auth, endpoint string, body any, out any) error {
	manager := h.currentAuthManager()
	if manager == nil {
		return fmt.Errorf("core auth manager is unavailable")
	}
	raw, errMarshal := json.Marshal(body)
	if errMarshal != nil {
		return fmt.Errorf("marshal request: %w", errMarshal)
	}
	req, errRequest := http.NewRequestWithContext(ctx, http.MethodPost, legacyGeminiCLICodeAssistURL+endpoint, strings.NewReader(string(raw)))
	if errRequest != nil {
		return fmt.Errorf("build request: %w", errRequest)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")
	resp, errDo := manager.HttpRequest(ctx, auth, req)
	if errDo != nil {
		return errDo
	}
	defer resp.Body.Close()
	responseBody, errRead := io.ReadAll(io.LimitReader(resp.Body, legacyGeminiCLIMaxBodyBytes+1))
	if errRead != nil {
		return fmt.Errorf("read response: %w", errRead)
	}
	if len(responseBody) > legacyGeminiCLIMaxBodyBytes {
		return fmt.Errorf("response exceeds %d bytes", legacyGeminiCLIMaxBodyBytes)
	}
	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	if errDecode := json.Unmarshal(responseBody, out); errDecode != nil {
		return fmt.Errorf("decode response: %w", errDecode)
	}
	return nil
}

func legacyGeminiCLIProjectID(auth *coreauth.Auth) string {
	if auth == nil {
		return ""
	}
	if value := strings.TrimSpace(auth.Attributes["project_id"]); value != "" {
		return value
	}
	if value, _ := auth.Metadata["project_id"].(string); strings.TrimSpace(value) != "" {
		return strings.TrimSpace(value)
	}
	var storage map[string]any
	if json.Unmarshal(storageJSONFromAuth(auth), &storage) == nil {
		if value, _ := storage["project_id"].(string); strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return ""
}

type legacyGeminiCLIBucket struct {
	modelID, tokenType, resetAt        string
	remainingFraction, remainingAmount *float64
}

type legacyGeminiCLIGroup struct {
	id, label, preferred string
	models               []string
}

var legacyGeminiCLIGroups = []legacyGeminiCLIGroup{
	{id: "gemini-flash-lite-series", label: "Gemini Flash Lite Series", preferred: "gemini-2.5-flash-lite", models: []string{"gemini-2.5-flash-lite"}},
	{id: "gemini-flash-series", label: "Gemini Flash Series", preferred: "gemini-3-flash-preview", models: []string{"gemini-3-flash-preview", "gemini-2.5-flash"}},
	{id: "gemini-pro-series", label: "Gemini Pro Series", preferred: "gemini-3.1-pro-preview", models: []string{"gemini-3.1-pro-preview", "gemini-3-pro-preview", "gemini-2.5-pro"}},
}

func legacyGeminiCLIQuotaItems(payload map[string]any) []pluginapi.QuotaItem {
	lookup := make(map[string]legacyGeminiCLIGroup)
	order := make(map[string]int)
	for index, group := range legacyGeminiCLIGroups {
		order[group.id] = index
		for _, model := range group.models {
			lookup[model] = group
		}
	}
	type aggregate struct {
		group   legacyGeminiCLIGroup
		token   string
		buckets []legacyGeminiCLIBucket
	}
	aggregates := make(map[string]*aggregate)
	for _, bucket := range legacyGeminiCLIParseBuckets(payload["buckets"]) {
		if bucket.modelID == "gemini-2.0-flash" || strings.HasPrefix(bucket.modelID, "gemini-2.0-flash-") {
			continue
		}
		group, okGroup := lookup[bucket.modelID]
		if !okGroup {
			group = legacyGeminiCLIGroup{id: bucket.modelID, label: bucket.modelID, preferred: bucket.modelID, models: []string{bucket.modelID}}
		}
		key := group.id + "\x00" + bucket.tokenType
		if aggregates[key] == nil {
			aggregates[key] = &aggregate{group: group, token: bucket.tokenType}
		}
		aggregates[key].buckets = append(aggregates[key].buckets, bucket)
	}

	items := make([]pluginapi.QuotaItem, 0, len(aggregates))
	for _, aggregate := range aggregates {
		chosen := aggregate.buckets[0]
		foundPreferred := false
		for _, bucket := range aggregate.buckets {
			if bucket.modelID == aggregate.group.preferred {
				chosen, foundPreferred = bucket, true
				break
			}
		}
		if !foundPreferred {
			for _, bucket := range aggregate.buckets[1:] {
				if legacyGeminiCLILessNullable(bucket.remainingFraction, chosen.remainingFraction) {
					chosen = bucket
				}
			}
		}
		modelIDs := make([]string, 0, len(aggregate.buckets))
		for _, bucket := range aggregate.buckets {
			modelIDs = append(modelIDs, bucket.modelID)
		}
		sort.Strings(modelIDs)
		id := aggregate.group.id
		if aggregate.token != "" {
			id += "-" + aggregate.token
		}
		items = append(items, pluginapi.QuotaItem{
			ID: id, Label: aggregate.group.label, Kind: "model",
			RemainingFraction: chosen.remainingFraction, RemainingAmount: chosen.remainingAmount,
			ResetAt: chosen.resetAt, ModelIDs: modelIDs,
			Metadata: map[string]any{"token_type": aggregate.token},
		})
	}
	sort.SliceStable(items, func(i, j int) bool {
		leftID := strings.TrimSuffix(items[i].ID, "-"+legacyGeminiCLIString(items[i].Metadata["token_type"]))
		rightID := strings.TrimSuffix(items[j].ID, "-"+legacyGeminiCLIString(items[j].Metadata["token_type"]))
		left, leftKnown := order[leftID]
		right, rightKnown := order[rightID]
		if leftKnown != rightKnown {
			return leftKnown
		}
		if leftKnown && left != right {
			return left < right
		}
		return items[i].ID < items[j].ID
	})
	return items
}

func legacyGeminiCLIParseBuckets(value any) []legacyGeminiCLIBucket {
	rows, _ := value.([]any)
	out := make([]legacyGeminiCLIBucket, 0, len(rows))
	for _, value := range rows {
		row, okRow := value.(map[string]any)
		if !okRow {
			continue
		}
		modelID := strings.TrimSuffix(legacyGeminiCLIFirstString(row, "modelId", "model_id"), "_vertex")
		if modelID == "" {
			continue
		}
		out = append(out, legacyGeminiCLIBucket{
			modelID: modelID, tokenType: legacyGeminiCLIFirstString(row, "tokenType", "token_type"),
			resetAt: legacyGeminiCLIFirstString(row, "resetTime", "reset_time"),
			remainingFraction: legacyGeminiCLIFirstNumber(row, "remainingFraction", "remaining_fraction"),
			remainingAmount: legacyGeminiCLIFirstNumber(row, "remainingAmount", "remaining_amount"),
		})
	}
	return out
}

func legacyGeminiCLIQuotaPlan(payload map[string]any, observedAt int64) *pluginapi.QuotaPlan {
	tier := legacyGeminiCLIFirstRecord(payload, "paidTier", "paid_tier")
	if strings.TrimSpace(legacyGeminiCLIString(tier["id"])) == "" {
		tier = legacyGeminiCLIFirstRecord(payload, "currentTier", "current_tier")
	}
	if tier == nil {
		return nil
	}
	id := strings.TrimSpace(legacyGeminiCLIString(tier["id"]))
	label := strings.TrimSpace(legacyGeminiCLIString(tier["name"]))
	if label == "" {
		label = id
	}
	plan := &pluginapi.QuotaPlan{ID: id, Label: label, Kind: legacyGeminiCLIPlanKind(id), ObservedAtMS: observedAt}
	if credits, okCredits := legacyGeminiCLIFirstValue(tier, "availableCredits", "available_credits").([]any); okCredits {
		for _, value := range credits {
			row, _ := value.(map[string]any)
			if legacyGeminiCLIFirstString(row, "creditType", "credit_type") == legacyGeminiCLIGoogleOneAI {
				plan.CreditBalance = legacyGeminiCLIFirstNumber(row, "creditAmount", "credit_amount")
				break
			}
		}
	}
	return plan
}

func legacyGeminiCLIPlanKind(id string) string {
	return map[string]string{"free-tier": "free", "legacy-tier": "legacy", "standard-tier": "standard", "g1-pro-tier": "pro", "g1-ultra-tier": "ultra"}[strings.ToLower(id)]
}
func legacyGeminiCLIString(value any) string { text, _ := value.(string); return text }
func legacyGeminiCLIFirstString(row map[string]any, keys ...string) string {
	for _, key := range keys {
		if value := strings.TrimSpace(legacyGeminiCLIString(row[key])); value != "" {
			return value
		}
	}
	return ""
}
func legacyGeminiCLIFirstNumber(row map[string]any, keys ...string) *float64 {
	for _, key := range keys {
		if value, okValue := row[key].(float64); okValue {
			return &value
		}
	}
	return nil
}
func legacyGeminiCLIFirstValue(row map[string]any, keys ...string) any {
	for _, key := range keys {
		if value := row[key]; value != nil {
			return value
		}
	}
	return nil
}
func legacyGeminiCLIFirstRecord(row map[string]any, keys ...string) map[string]any {
	value, _ := legacyGeminiCLIFirstValue(row, keys...).(map[string]any)
	return value
}
func legacyGeminiCLILessNullable(left, right *float64) bool {
	return left != nil && (right == nil || *left < *right)
}
