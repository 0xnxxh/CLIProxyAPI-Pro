package pluginhost

import (
	"context"
	"encoding/json"
	"testing"

	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

func TestParseAuthNormalizesGeminiCLIStringToken(t *testing.T) {
	var seen map[string]any
	host := newHostWithRecords(capabilityRecord{
		id: "geminicli",
		plugin: pluginapi.Plugin{
			Capabilities: pluginapi.Capabilities{
				AuthProvider: fakeAuthProvider{
					identifier: "gemini-cli",
					parseAuth: func(ctx context.Context, req pluginapi.AuthParseRequest) (pluginapi.AuthParseResponse, error) {
						if err := json.Unmarshal(req.RawJSON, &seen); err != nil {
							t.Fatalf("normalized RawJSON is invalid: %v", err)
						}
						return pluginapi.AuthParseResponse{
							Handled: true,
							Auth: pluginapi.AuthData{
								Provider:    "gemini-cli",
								ID:          "gemini.json",
								StorageJSON: req.RawJSON,
							},
						}, nil
					},
				},
			},
		},
	})
	_, handled, errParse := host.ParseAuth(context.Background(), pluginapi.AuthParseRequest{
		Provider: "gemini-cli",
		RawJSON:  []byte(`{"type":"gemini-cli","token":"{\"access_token\":\"access-token\",\"refresh_token\":\"refresh-token\"}","project_id":"project-id"}`),
	})
	if errParse != nil {
		t.Fatalf("ParseAuth() error = %v", errParse)
	}
	if !handled {
		t.Fatal("ParseAuth() handled = false")
	}
	token, ok := seen["token"].(map[string]any)
	if !ok {
		t.Fatalf("token = %#v, want object", seen["token"])
	}
	if token["access_token"] != "access-token" || seen["access_token"] != "access-token" || seen["refresh_token"] != "refresh-token" {
		t.Fatalf("normalized storage = %#v", seen)
	}
}

func TestStorageJSONFromAuthNormalizesGeminiCLIRawStringToken(t *testing.T) {
	auth := &coreauth.Auth{
		Provider: "gemini-cli",
		Storage: &pluginTokenStorage{
			provider: "gemini-cli",
			rawJSON:  []byte(`{"type":"gemini-cli","token":"plain-access-token","project_id":"project-id"}`),
		},
	}
	var data map[string]any
	if err := json.Unmarshal(storageJSONFromAuth(auth), &data); err != nil {
		t.Fatalf("storageJSONFromAuth() invalid JSON: %v", err)
	}
	token, ok := data["token"].(map[string]any)
	if !ok {
		t.Fatalf("token = %#v, want object", data["token"])
	}
	if token["access_token"] != "plain-access-token" || data["access_token"] != "plain-access-token" {
		t.Fatalf("normalized storage = %#v", data)
	}
}

func TestParseAuthRestoresDisabledFromPluginMetadata(t *testing.T) {
	host := newHostWithRecords(capabilityRecord{
		id: "geminicli",
		plugin: pluginapi.Plugin{
			Capabilities: pluginapi.Capabilities{
				AuthProvider: fakeAuthProvider{
					identifier: "gemini-cli",
					parseAuth: func(ctx context.Context, req pluginapi.AuthParseRequest) (pluginapi.AuthParseResponse, error) {
						return pluginapi.AuthParseResponse{
							Handled: true,
							Auth: pluginapi.AuthData{
								Provider:    "gemini-cli",
								ID:          "disabled.json",
								Metadata:    map[string]any{"disabled": true},
								StorageJSON: []byte(`{"type":"gemini-cli","disabled":true}`),
							},
						}, nil
					},
				},
			},
		},
	})
	auth, handled, errParse := host.ParseAuth(context.Background(), pluginapi.AuthParseRequest{
		Provider: "gemini-cli",
		RawJSON:  []byte(`{"type":"gemini-cli","disabled":true}`),
	})
	if errParse != nil {
		t.Fatalf("ParseAuth() error = %v", errParse)
	}
	if !handled || auth == nil {
		t.Fatalf("ParseAuth() handled=%t auth=%#v, want auth", handled, auth)
	}
	if !auth.Disabled || auth.Status != coreauth.StatusDisabled || auth.Metadata["disabled"] != true {
		t.Fatalf("auth disabled/status/metadata = %v/%v/%#v, want disabled", auth.Disabled, auth.Status, auth.Metadata["disabled"])
	}
}
