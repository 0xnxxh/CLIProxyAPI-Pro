package management

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/embeddedusage"
	"github.com/router-for-me/CLIProxyAPI/v7/internal/pluginhost"
	coreauth "github.com/router-for-me/CLIProxyAPI/v7/sdk/cliproxy/auth"
	"github.com/router-for-me/CLIProxyAPI/v7/sdk/pluginapi"
)

// RegisterPluginQuotaRoutes registers the host-owned normalized quota endpoint.
func (h *Handler) RegisterPluginQuotaRoutes(group *gin.RouterGroup) {
	if h == nil || group == nil {
		return
	}
	group.POST("/quota/fetch", h.FetchPluginQuota)
}

// FetchPluginQuota asks the provider plugin for one auth's current quota and persists it.
func (h *Handler) FetchPluginQuota(c *gin.Context) {
	var req struct {
		AuthIndex string `json:"auth_index"`
	}
	if errBind := c.ShouldBindJSON(&req); errBind != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	authIndex := strings.TrimSpace(req.AuthIndex)
	if authIndex == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "auth_index is required"})
		return
	}

	auth := h.authByIndex(authIndex)
	if auth == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "auth not found"})
		return
	}
	result, statusCode, errorLabel, errFetch := h.fetchAndPersistPluginQuota(c.Request.Context(), auth)
	if errFetch != nil {
		c.JSON(statusCode, gin.H{"error": errorLabel, "message": errFetch.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"auth_index": auth.Index,
		"plugin_id":  result.PluginID,
		"snapshot":   result.Snapshot,
	})
}

func (h *Handler) fetchAndPersistPluginQuota(ctx context.Context, auth *coreauth.Auth) (pluginhost.QuotaResult, int, string, error) {
	if h == nil || auth == nil {
		return pluginhost.QuotaResult{}, http.StatusServiceUnavailable, "plugin quota service unavailable", fmt.Errorf("plugin quota service unavailable")
	}
	h.mu.Lock()
	host := h.pluginHost
	manager := h.authManager
	h.mu.Unlock()
	if host == nil || manager == nil {
		return pluginhost.QuotaResult{}, http.StatusServiceUnavailable, "plugin quota service unavailable", fmt.Errorf("plugin quota service unavailable")
	}
	previous := loadPluginQuotaSnapshot(ctx, auth.Provider, auth.FileName, auth.Index)
	result := host.FetchQuota(ctx, auth, previous)
	if !result.Handled {
		return result, http.StatusNotFound, "quota provider not found", fmt.Errorf("quota provider not found")
	}
	if result.Err != nil {
		return result, http.StatusBadGateway, "quota fetch failed", result.Err
	}
	if result.Auth != nil {
		updated, errUpdate := manager.Update(ctx, result.Auth)
		if errUpdate != nil {
			return result, http.StatusInternalServerError, "auth update failed", fmt.Errorf("auth update failed: %w", errUpdate)
		}
		if updated == nil {
			return result, http.StatusConflict, "auth update target no longer exists", fmt.Errorf("auth update target no longer exists")
		}
	}
	if errPersist := persistPluginQuotaSnapshot(ctx, auth.Provider, auth.FileName, auth.Index, result.Snapshot); errPersist != nil {
		return result, http.StatusInternalServerError, "quota persistence failed", fmt.Errorf("quota persistence failed: %w", errPersist)
	}
	return result, http.StatusOK, "", nil
}

func loadPluginQuotaSnapshot(ctx context.Context, provider, fileName, authIndex string) *pluginapi.QuotaSnapshot {
	entries, errGet := embeddedusage.GetQuotaCache(ctx, provider, quotaFileName(fileName, authIndex))
	if errGet != nil {
		return nil
	}
	for _, entry := range entries {
		if entry.AuthIndex != "" && entry.AuthIndex != authIndex {
			continue
		}
		var snapshot pluginapi.QuotaSnapshot
		if json.Unmarshal(entry.Data, &snapshot) == nil && snapshot.SchemaVersion > 0 {
			return &snapshot
		}
	}
	return nil
}

func persistPluginQuotaSnapshot(ctx context.Context, provider, fileName, authIndex string, snapshot pluginapi.QuotaSnapshot) error {
	raw, errMarshal := json.Marshal(snapshot)
	if errMarshal != nil {
		return fmt.Errorf("marshal quota snapshot: %w", errMarshal)
	}
	now := time.Now().UnixMilli()
	observedAt := snapshot.ObservedAtMS
	if observedAt <= 0 {
		observedAt = now
	}
	provider = strings.TrimSpace(provider)
	fileName = quotaFileName(fileName, authIndex)
	fingerprint := sha256.Sum256([]byte(strings.ToLower(provider + "|" + authIndex)))
	return embeddedusage.SetQuotaCache(ctx, embeddedusage.QuotaCacheEntry{
		ID:                  "quota-provider:" + provider + ":" + authIndex,
		Provider:            provider,
		FileName:            fileName,
		AuthIndex:           authIndex,
		IdentityFingerprint: hex.EncodeToString(fingerprint[:]),
		Data:                raw,
		CachedAt:            observedAt,
		ObservedAt:          observedAt,
		AccessedAt:          now,
		Version:             snapshot.SchemaVersion,
	})
}

func quotaFileName(fileName, authIndex string) string {
	if fileName = strings.TrimSpace(fileName); fileName != "" {
		return fileName
	}
	return strings.TrimSpace(authIndex)
}
