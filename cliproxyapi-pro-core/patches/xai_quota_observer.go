package executor

import (
	"context"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v6/internal/embeddedusage"
	cliproxyauth "github.com/router-for-me/CLIProxyAPI/v6/sdk/cliproxy/auth"
)

func observeXAIQuotaResponse(ctx context.Context, auth *cliproxyauth.Auth, model string, status int, header http.Header, body []byte) {
	if auth == nil || !strings.EqualFold(strings.TrimSpace(auth.Provider), "xai") {
		return
	}
	fileName := filepath.Base(strings.TrimSpace(auth.FileName))
	if fileName == "." || fileName == "" {
		fileName = filepath.Base(strings.TrimSpace(auth.ID))
	}
	_ = embeddedusage.ObserveXAIQuotaResponse(ctx, embeddedusage.XAIQuotaObservation{
		FileName:   fileName,
		AuthIndex:  auth.Index,
		Email:      firstXAIQuotaMetadataString(auth.Metadata, "email", "subject", "sub", "user_id", "userId"),
		Label:      auth.Label,
		Model:      model,
		Status:     status,
		Header:     header,
		Body:       body,
		ObservedAt: time.Now(),
	})
}

func firstXAIQuotaMetadataString(metadata map[string]any, keys ...string) string {
	for _, key := range keys {
		if value := xaiMetadataString(metadata, key); value != "" {
			return value
		}
	}
	return ""
}
