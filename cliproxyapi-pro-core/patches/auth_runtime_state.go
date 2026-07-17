package auth

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"path/filepath"
	"strings"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v6/internal/embeddedusage"
)

func authRuntimeIdentityFingerprint(auth *Auth) string {
	if auth == nil {
		return ""
	}
	parts := []string{
		strings.ToLower(strings.TrimSpace(auth.Provider)),
		strings.ToLower(filepath.Base(strings.TrimSpace(auth.FileName))),
	}
	for _, key := range []string{"email", "account_id", "accountId", "subject", "sub", "user_id", "userId"} {
		if auth.Metadata == nil {
			break
		}
		if value, ok := auth.Metadata[key].(string); ok && strings.TrimSpace(value) != "" {
			parts = append(parts, strings.ToLower(strings.TrimSpace(value)))
		}
	}
	if len(parts) == 2 {
		parts = append(parts, strings.TrimSpace(auth.Index))
	}
	sum := sha256.Sum256([]byte(strings.Join(parts, "|")))
	return hex.EncodeToString(sum[:])
}

func restoreAuthRuntimeStats(auth *Auth) {
	if auth == nil {
		return
	}
	auth.EnsureIndex()
	stored, ok, err := embeddedusage.GetAuthRuntimeStats(context.Background(), auth.Index, auth.ID)
	if err != nil || !ok {
		return
	}
	fingerprint := authRuntimeIdentityFingerprint(auth)
	if stored.IdentityFingerprint != "" && fingerprint != "" && stored.IdentityFingerprint != fingerprint {
		return
	}
	auth.Selected = stored.SelectedCount
	auth.Success = stored.SuccessCount
	auth.Failed = stored.FailureCount
	auth.recentRequests = recentRequestRing{}
	for _, item := range stored.RecentBuckets {
		if item.BucketID <= 0 {
			continue
		}
		index := recentRequestBucketIndex(item.BucketID)
		auth.recentRequests.buckets[index] = recentRequestBucket{
			bucketID: item.BucketID,
			success:  item.Success,
			failed:   item.Failed,
		}
	}
}

func authRuntimeStatsSnapshot(auth *Auth, now time.Time) embeddedusage.AuthRuntimeStats {
	fileName := auth.FileName
	if auth.Attributes != nil {
		if source := strings.TrimSpace(auth.Attributes[AttributeVirtualSource]); source != "" {
			fileName = filepath.Base(source)
		}
	}
	stats := embeddedusage.AuthRuntimeStats{
		AuthIndex:           auth.Index,
		AuthID:              auth.ID,
		FileName:            fileName,
		IdentityFingerprint: authRuntimeIdentityFingerprint(auth),
		SelectedCount:       auth.Selected,
		SuccessCount:        auth.Success,
		FailureCount:        auth.Failed,
		UpdatedAtMS:         now.UnixMilli(),
	}
	for _, bucket := range auth.recentRequests.buckets {
		if bucket.bucketID <= 0 {
			continue
		}
		stats.RecentBuckets = append(stats.RecentBuckets, embeddedusage.RuntimeRequestBucket{
			BucketID: bucket.bucketID,
			Success:  bucket.success,
			Failed:   bucket.failed,
		})
	}
	return stats
}

func queueAuthRuntimeStats(auth *Auth) {
	if auth == nil {
		return
	}
	embeddedusage.QueueAuthRuntimeStats(authRuntimeStatsSnapshot(auth, time.Now()))
}

func (m *Manager) recordAuthSelected(authID string) {
	if m == nil || strings.TrimSpace(authID) == "" {
		return
	}
	var snapshot *Auth
	m.mu.Lock()
	if auth := m.auths[authID]; auth != nil {
		auth.Selected++
		snapshot = auth.Clone()
	}
	m.mu.Unlock()
	queueAuthRuntimeStats(snapshot)
}
