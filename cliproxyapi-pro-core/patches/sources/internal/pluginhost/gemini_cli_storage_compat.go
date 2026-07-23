package pluginhost

import (
	"bytes"
	"encoding/json"
	"strings"
)

func normalizePluginStorageJSON(provider string, raw []byte) []byte {
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 {
		return nil
	}
	provider = normalizeProviderID(provider)
	if provider != "gemini-cli" && provider != "gemini" {
		return raw
	}
	var data map[string]any
	if err := json.Unmarshal(trimmed, &data); err != nil || data == nil {
		return raw
	}
	normalizeGeminiCLIStorageMap(data)
	out, err := json.Marshal(data)
	if err != nil {
		return raw
	}
	return out
}

func pluginAuthDisabledFromMetadata(metadata map[string]any) bool {
	if metadata == nil {
		return false
	}
	switch value := metadata["disabled"].(type) {
	case bool:
		return value
	case string:
		value = strings.ToLower(strings.TrimSpace(value))
		return value == "true" || value == "1" || value == "yes" || value == "on"
	case float64:
		return value != 0
	case int:
		return value != 0
	case int64:
		return value != 0
	case json.Number:
		parsed, err := value.Int64()
		return err == nil && parsed != 0
	default:
		return false
	}
}

func normalizeGeminiCLIStorageMap(data map[string]any) {
	if data == nil {
		return
	}
	if rawType := strings.TrimSpace(stringValue(data["type"])); rawType != "" {
		providerType := normalizeProviderID(rawType)
		if providerType != "gemini-cli" && providerType != "gemini" {
			return
		}
	}
	rawToken, ok := data["token"]
	if !ok {
		return
	}
	switch token := rawToken.(type) {
	case map[string]any:
		return
	case string:
		token = strings.TrimSpace(token)
		if token == "" {
			delete(data, "token")
			return
		}
		var parsed map[string]any
		if err := json.Unmarshal([]byte(token), &parsed); err == nil && parsed != nil {
			data["token"] = parsed
			copyGeminiCLITokenFields(data, parsed)
			return
		}
		data["token"] = map[string]any{"access_token": token}
		if strings.TrimSpace(stringValue(data["access_token"])) == "" {
			data["access_token"] = token
		}
	default:
		delete(data, "token")
	}
}

func copyGeminiCLITokenFields(data map[string]any, token map[string]any) {
	for _, key := range []string{"access_token", "refresh_token", "token_type", "expiry", "expires_in", "scope"} {
		if _, exists := data[key]; exists {
			continue
		}
		if value, ok := token[key]; ok {
			data[key] = value
		}
	}
}

func stringValue(value any) string {
	switch typed := value.(type) {
	case string:
		return typed
	case interface{ String() string }:
		return typed.String()
	default:
		return ""
	}
}
