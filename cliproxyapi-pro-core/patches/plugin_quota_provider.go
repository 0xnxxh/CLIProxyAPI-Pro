package pluginhost

import (
	"context"
	"fmt"
	"strings"
	"time"

	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

type QuotaResult struct {
	Handled  bool
	PluginID string
	Snapshot pluginapi.QuotaSnapshot
	Auth     *coreauth.Auth
	Err      error
}

func (h *Host) HasQuotaProvider(provider string) bool {
	provider = normalizeProviderID(provider)
	if h == nil || provider == "" {
		return false
	}
	for _, record := range h.activeRecords() {
		quotaProvider := record.plugin.Capabilities.QuotaProvider
		if quotaProvider == nil || h.isPluginFused(record.id) {
			continue
		}
		identifier, okIdentifier := h.callQuotaProviderIdentifier(record.id, quotaProvider)
		if okIdentifier && normalizeProviderID(identifier) == provider {
			return true
		}
	}
	return false
}

func (h *Host) FetchQuota(ctx context.Context, auth *coreauth.Auth, previous *pluginapi.QuotaSnapshot) QuotaResult {
	if h == nil || auth == nil {
		return QuotaResult{}
	}
	provider := normalizeProviderID(auth.Provider)
	if provider == "" {
		return QuotaResult{}
	}
	for _, record := range h.activeRecords() {
		quotaProvider := record.plugin.Capabilities.QuotaProvider
		if quotaProvider == nil || h.isPluginFused(record.id) {
			continue
		}
		identifier, okIdentifier := h.callQuotaProviderIdentifier(record.id, quotaProvider)
		if !okIdentifier || normalizeProviderID(identifier) != provider {
			continue
		}
		resp, errFetch := h.callFetchQuota(ctx, record, quotaProvider, auth, previous)
		if errFetch != nil {
			return QuotaResult{Handled: true, PluginID: record.id, Err: errFetch}
		}
		return h.quotaResultFromResponse(record.id, provider, auth, previous, resp)
	}
	if record, okLegacy := h.legacyQuotaAdapter(provider); okLegacy {
		resp, errFetch := h.fetchLegacyGeminiCLIQuota(ctx, auth)
		if errFetch != nil {
			return QuotaResult{Handled: true, PluginID: record.id, Err: errFetch}
		}
		return h.quotaResultFromResponse(record.id, provider, auth, previous, resp)
	}
	return QuotaResult{}
}

func (h *Host) quotaResultFromResponse(pluginID, provider string, auth *coreauth.Auth, previous *pluginapi.QuotaSnapshot, resp pluginapi.QuotaFetchResponse) QuotaResult {
	if resp.Snapshot.SchemaVersion > pluginapi.QuotaSnapshotSchemaVersion {
		return QuotaResult{Handled: true, PluginID: pluginID, Err: fmt.Errorf(
			"quota snapshot schema %d is newer than host schema %d",
			resp.Snapshot.SchemaVersion, pluginapi.QuotaSnapshotSchemaVersion,
		)}
	}
	snapshot := normalizeQuotaSnapshot(resp.Snapshot, provider, previous, resp.PlanUnavailable, resp.PlanError)
	path := ""
	if auth.Attributes != nil {
		path = auth.Attributes["path"]
	}
	var updated *coreauth.Auth
	if authDataHasValue(resp.AuthUpdate) {
		updated = h.AuthDataToCoreAuth(authDataWithDefaults(resp.AuthUpdate, auth), path, auth.FileName)
	}
	return QuotaResult{Handled: true, PluginID: pluginID, Snapshot: snapshot, Auth: updated}
}

func (h *Host) callQuotaProviderIdentifier(pluginID string, provider pluginapi.QuotaProvider) (identifier string, ok bool) {
	if h == nil || provider == nil || h.isPluginFused(pluginID) {
		return "", false
	}
	defer func() {
		if recovered := recover(); recovered != nil {
			h.fusePlugin(pluginID, "QuotaProvider.Identifier", recovered)
			identifier, ok = "", false
		}
	}()
	return strings.TrimSpace(provider.Identifier()), true
}

func (h *Host) callFetchQuota(ctx context.Context, record capabilityRecord, provider pluginapi.QuotaProvider, auth *coreauth.Auth, previous *pluginapi.QuotaSnapshot) (resp pluginapi.QuotaFetchResponse, err error) {
	if h == nil || provider == nil || auth == nil || h.isPluginFused(record.id) || !h.recordCurrent(record) {
		return pluginapi.QuotaFetchResponse{}, fmt.Errorf("quota provider is unavailable")
	}
	defer func() {
		if recovered := recover(); recovered != nil {
			h.fusePlugin(record.id, "QuotaProvider.FetchQuota", recovered)
			resp = pluginapi.QuotaFetchResponse{}
			err = fmt.Errorf("quota provider panic: %v", recovered)
		}
	}()
	return provider.FetchQuota(ctx, pluginapi.QuotaFetchRequest{
		Plugin:       clonePluginMetadata(record.meta),
		AuthID:       auth.ID,
		AuthProvider: auth.Provider,
		StorageJSON:  storageJSONFromAuth(auth),
		Metadata:     cloneAnyMap(auth.Metadata),
		Attributes:   cloneStringMap(auth.Attributes),
		Previous:     cloneQuotaSnapshot(previous),
		Host:         h.hostConfigSummary(),
		HTTPClient:   h.newHTTPClient(auth, auth.Provider),
	})
}

func normalizeQuotaSnapshot(snapshot pluginapi.QuotaSnapshot, provider string, previous *pluginapi.QuotaSnapshot, planUnavailable bool, planError string) pluginapi.QuotaSnapshot {
	if snapshot.SchemaVersion <= 0 {
		snapshot.SchemaVersion = pluginapi.QuotaSnapshotSchemaVersion
	}
	snapshot.Provider = provider
	if snapshot.ObservedAtMS <= 0 {
		snapshot.ObservedAtMS = time.Now().UnixMilli()
	}
	if snapshot.Items == nil {
		snapshot.Items = []pluginapi.QuotaItem{}
	}
	for index := range snapshot.Items {
		item := &snapshot.Items[index]
		item.ID = strings.TrimSpace(item.ID)
		item.Label = strings.TrimSpace(item.Label)
		item.RemainingFraction = clampFloatPointer(item.RemainingFraction, 0, 1)
		item.UsedPercent = clampFloatPointer(item.UsedPercent, 0, 100)
	}
	planError = strings.TrimSpace(planError)
	if planUnavailable && snapshot.Plan == nil && previous != nil && previous.Plan != nil {
		retained := *previous.Plan
		retained.Metadata = cloneAnyMap(previous.Plan.Metadata)
		retained.Stale = true
		retained.Error = planError
		snapshot.Plan = &retained
	}
	if planUnavailable && planError != "" {
		snapshot.Warnings = append(snapshot.Warnings, pluginapi.QuotaWarning{Code: "plan_unavailable", Message: planError, Retryable: true})
	}
	return snapshot
}

func cloneQuotaSnapshot(snapshot *pluginapi.QuotaSnapshot) *pluginapi.QuotaSnapshot {
	if snapshot == nil {
		return nil
	}
	clone := *snapshot
	clone.Items = append([]pluginapi.QuotaItem(nil), snapshot.Items...)
	for index := range clone.Items {
		clone.Items[index].ModelIDs = append([]string(nil), snapshot.Items[index].ModelIDs...)
		clone.Items[index].Metadata = cloneAnyMap(snapshot.Items[index].Metadata)
	}
	clone.Warnings = append([]pluginapi.QuotaWarning(nil), snapshot.Warnings...)
	clone.Metadata = cloneAnyMap(snapshot.Metadata)
	if snapshot.Plan != nil {
		plan := *snapshot.Plan
		plan.Metadata = cloneAnyMap(snapshot.Plan.Metadata)
		clone.Plan = &plan
	}
	return &clone
}

func clampFloatPointer(value *float64, min, max float64) *float64 {
	if value == nil {
		return nil
	}
	clamped := *value
	if clamped < min {
		clamped = min
	}
	if clamped > max {
		clamped = max
	}
	return &clamped
}
