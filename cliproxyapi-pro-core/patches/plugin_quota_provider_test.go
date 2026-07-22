package pluginhost

import (
	"context"
	"testing"

	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

type quotaProviderStub struct {
	identifier string
	fetch      func(context.Context, pluginapi.QuotaFetchRequest) (pluginapi.QuotaFetchResponse, error)
}

func (p quotaProviderStub) Identifier() string { return p.identifier }
func (p quotaProviderStub) FetchQuota(ctx context.Context, req pluginapi.QuotaFetchRequest) (pluginapi.QuotaFetchResponse, error) {
	return p.fetch(ctx, req)
}

func TestFetchQuotaNormalizesAndRetainsPreviousPlan(t *testing.T) {
	remaining := 1.2
	previous := &pluginapi.QuotaSnapshot{Plan: &pluginapi.QuotaPlan{ID: "g1-pro-tier", Kind: "pro", ObservedAtMS: 123}}
	provider := quotaProviderStub{identifier: "gemini-cli", fetch: func(ctx context.Context, req pluginapi.QuotaFetchRequest) (pluginapi.QuotaFetchResponse, error) {
		if req.AuthID != "auth-1" || req.AuthProvider != "gemini-cli" || req.Previous == nil || req.HTTPClient == nil {
			t.Fatalf("FetchQuota request = %#v", req)
		}
		return pluginapi.QuotaFetchResponse{
			Snapshot:        pluginapi.QuotaSnapshot{Items: []pluginapi.QuotaItem{{ID: " pro ", Label: " Pro ", RemainingFraction: &remaining}}},
			PlanUnavailable: true,
			PlanError:       "tier endpoint timed out",
		}, nil
	}}
	host := newHostWithRecords(capabilityRecord{
		id: "geminicli",
		meta: pluginapi.Metadata{Name: "Gemini CLI", Version: "1.0.0"},
		plugin: pluginapi.Plugin{Capabilities: pluginapi.Capabilities{QuotaProvider: provider}},
	})
	result := host.FetchQuota(context.Background(), &coreauth.Auth{ID: "auth-1", Provider: "gemini-cli", FileName: "gemini.json"}, previous)
	if !result.Handled || result.Err != nil || result.PluginID != "geminicli" {
		t.Fatalf("FetchQuota() = %#v", result)
	}
	if result.Snapshot.SchemaVersion != pluginapi.QuotaSnapshotSchemaVersion || result.Snapshot.Provider != "gemini-cli" || result.Snapshot.ObservedAtMS <= 0 {
		t.Fatalf("normalized snapshot = %#v", result.Snapshot)
	}
	if got := *result.Snapshot.Items[0].RemainingFraction; got != 1 {
		t.Fatalf("remaining fraction = %v, want 1", got)
	}
	if result.Snapshot.Plan == nil || result.Snapshot.Plan.ID != "g1-pro-tier" || !result.Snapshot.Plan.Stale || result.Snapshot.Plan.Error == "" {
		t.Fatalf("retained plan = %#v", result.Snapshot.Plan)
	}
	if previous.Plan.Stale || previous.Plan.Error != "" {
		t.Fatalf("previous plan was mutated: %#v", previous.Plan)
	}
}

func TestHasQuotaProviderMatchesIdentifier(t *testing.T) {
	host := newHostWithRecords(capabilityRecord{id: "geminicli", plugin: pluginapi.Plugin{Capabilities: pluginapi.Capabilities{
		QuotaProvider: quotaProviderStub{identifier: " Gemini-CLI ", fetch: func(context.Context, pluginapi.QuotaFetchRequest) (pluginapi.QuotaFetchResponse, error) {
			return pluginapi.QuotaFetchResponse{}, nil
		}},
	}}})
	if !host.HasQuotaProvider("gemini-cli") || host.HasQuotaProvider("codex") {
		t.Fatal("quota provider matching failed")
	}
	plugins := host.RegisteredPlugins()
	if len(plugins) != 1 || !plugins[0].SupportsQuota || plugins[0].QuotaProvider != "Gemini-CLI" || plugins[0].QuotaMode != "native" {
		t.Fatalf("registered quota capability = %#v", plugins)
	}
	if caps := rpcCapabilitiesFromPlugin(host.activeRecords()[0].plugin); !caps.QuotaProvider {
		t.Fatal("RPC registration omitted quota_provider capability")
	}
}

func TestFetchQuotaRejectsNewerSnapshotSchema(t *testing.T) {
	host := newHostWithRecords(capabilityRecord{id: "future", plugin: pluginapi.Plugin{Capabilities: pluginapi.Capabilities{
		QuotaProvider: quotaProviderStub{identifier: "gemini-cli", fetch: func(context.Context, pluginapi.QuotaFetchRequest) (pluginapi.QuotaFetchResponse, error) {
			return pluginapi.QuotaFetchResponse{Snapshot: pluginapi.QuotaSnapshot{SchemaVersion: pluginapi.QuotaSnapshotSchemaVersion + 1}}, nil
		}},
	}}})
	result := host.FetchQuota(context.Background(), &coreauth.Auth{ID: "auth-1", Provider: "gemini-cli"}, nil)
	if !result.Handled || result.Err == nil {
		t.Fatalf("FetchQuota() = %#v, want handled schema error", result)
	}
}
