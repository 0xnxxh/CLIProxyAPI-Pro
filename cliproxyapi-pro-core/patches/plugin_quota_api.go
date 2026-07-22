const (
	// QuotaSnapshotSchemaVersion is the normalized quota snapshot schema understood by this host.
	QuotaSnapshotSchemaVersion = 1
)

// QuotaProvider fetches normalized quota data for one plugin-owned auth record.
type QuotaProvider interface {
	Identifier() string
	FetchQuota(context.Context, QuotaFetchRequest) (QuotaFetchResponse, error)
}

// QuotaFetchRequest carries one concrete auth and the previous persisted snapshot.
type QuotaFetchRequest struct {
	Plugin       Metadata          `json:"plugin"`
	AuthID       string            `json:"auth_id"`
	AuthProvider string            `json:"auth_provider"`
	StorageJSON  []byte            `json:"storage_json"`
	Metadata     map[string]any    `json:"metadata,omitempty"`
	Attributes   map[string]string `json:"attributes,omitempty"`
	Previous     *QuotaSnapshot    `json:"previous,omitempty"`
	Host         HostConfigSummary `json:"host"`
	HTTPClient   HostHTTPClient `json:"-"`
}

// QuotaFetchResponse returns the normalized snapshot and an optional auth update.
type QuotaFetchResponse struct {
	Snapshot        QuotaSnapshot `json:"snapshot"`
	PlanUnavailable bool          `json:"plan_unavailable,omitempty"`
	PlanError       string        `json:"plan_error,omitempty"`
	AuthUpdate      AuthData      `json:"auth_update,omitempty"`
}

// QuotaSnapshot is a provider-neutral quota and subscription snapshot.
type QuotaSnapshot struct {
	SchemaVersion int            `json:"schema_version"`
	Provider      string         `json:"provider"`
	ObservedAtMS  int64          `json:"observed_at_ms"`
	Items         []QuotaItem    `json:"items"`
	Plan          *QuotaPlan     `json:"plan,omitempty"`
	Warnings      []QuotaWarning `json:"warnings,omitempty"`
	Metadata      map[string]any `json:"metadata,omitempty"`
}

// QuotaItem describes one normalized quota window or bucket.
type QuotaItem struct {
	ID                string         `json:"id"`
	Label             string         `json:"label"`
	Kind              string         `json:"kind,omitempty"`
	RemainingFraction *float64       `json:"remaining_fraction,omitempty"`
	UsedPercent       *float64       `json:"used_percent,omitempty"`
	RemainingAmount   *float64       `json:"remaining_amount,omitempty"`
	Limit             *float64       `json:"limit,omitempty"`
	Unit              string         `json:"unit,omitempty"`
	ResetAt           string         `json:"reset_at,omitempty"`
	ModelIDs          []string       `json:"model_ids,omitempty"`
	Metadata          map[string]any `json:"metadata,omitempty"`
}

// QuotaPlan describes subscription or account tier information.
type QuotaPlan struct {
	ID             string         `json:"id,omitempty"`
	Label          string         `json:"label,omitempty"`
	Kind           string         `json:"kind,omitempty"`
	CreditBalance  *float64       `json:"credit_balance,omitempty"`
	ObservedAtMS   int64          `json:"observed_at_ms,omitempty"`
	Stale          bool           `json:"stale,omitempty"`
	Error          string         `json:"error,omitempty"`
	Metadata       map[string]any `json:"metadata,omitempty"`
}

// QuotaWarning describes a non-fatal quota probe issue.
type QuotaWarning struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	Retryable bool   `json:"retryable,omitempty"`
}
