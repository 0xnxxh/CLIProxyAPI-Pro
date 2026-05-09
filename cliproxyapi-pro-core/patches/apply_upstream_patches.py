#!/usr/bin/env python3
import os
from pathlib import Path

ROOT = Path(os.environ.get('SRC_ROOT', '/src/CLIProxyAPI'))
PRO_PANEL_REPOSITORY = 'https://github.com/ssfun/CLIProxyAPI-Pro'
PRO_PANEL_RELEASE_API = 'https://api.github.com/repos/ssfun/CLIProxyAPI-Pro/releases/latest'


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f'pattern not found in {path}: {old[:120]!r}')
    path.write_text(text.replace(old, new, 1))


config_go = ROOT / 'internal/config/config.go'
replace_once(
    config_go,
    'DefaultPanelGitHubRepository = "https://github.com/router-for-me/Cli-Proxy-API-Management-Center"',
    f'DefaultPanelGitHubRepository = "{PRO_PANEL_REPOSITORY}"',
)

config_example = ROOT / 'config.example.yaml'
replace_once(
    config_example,
    '  panel-github-repository: "https://github.com/router-for-me/Cli-Proxy-API-Management-Center"',
    f'  panel-github-repository: "{PRO_PANEL_REPOSITORY}"',
)

updater = ROOT / 'internal/managementasset/updater.go'
replace_once(
    updater,
    'defaultManagementReleaseURL  = "https://api.github.com/repos/router-for-me/Cli-Proxy-API-Management-Center/releases/latest"',
    f'defaultManagementReleaseURL  = "{PRO_PANEL_RELEASE_API}"',
)

replace_once(
    updater,
    '''\treq.Header.Set("Accept", "application/vnd.github+json")
\treq.Header.Set("User-Agent", httpUserAgent)
\tgitURL := strings.ToLower(strings.TrimSpace(os.Getenv("GITSTORE_GIT_URL")))
\tif tok := strings.TrimSpace(os.Getenv("GITSTORE_GIT_TOKEN")); tok != "" && strings.Contains(gitURL, "github.com") {
\t\treq.Header.Set("Authorization", "Bearer "+tok)
\t}
''',
    '''\treq.Header.Set("Accept", "application/vnd.github+json")
\treq.Header.Set("User-Agent", httpUserAgent)
\tif tok := strings.TrimSpace(os.Getenv("GITSTORE_GIT_TOKEN")); tok != "" && isGitHubReleaseURL(releaseURL) {
\t\treq.Header.Set("Authorization", "Bearer "+tok)
\t}
''',
)

replace_once(
    updater,
    '''func fetchLatestAsset(ctx context.Context, client *http.Client, releaseURL string) (*releaseAsset, string, error) {
''',
    '''func isGitHubReleaseURL(releaseURL string) bool {
\tparsed, err := url.Parse(strings.TrimSpace(releaseURL))
\tif err != nil || parsed.Host == "" {
\t\treturn false
\t}
\treturn strings.Contains(strings.ToLower(parsed.Host), "github.com")
}

func fetchLatestAsset(ctx context.Context, client *http.Client, releaseURL string) (*releaseAsset, string, error) {
''',
)

server = ROOT / 'internal/api/server.go'
management_scheduler = ROOT / 'internal/api/handlers/management/account_inspection_scheduler.go'
scheduler_source = Path('/tmp/account_inspection_scheduler.go')
if not scheduler_source.is_file():
    scheduler_source = Path(__file__).resolve().parent / 'account_inspection_scheduler.go'
management_scheduler.write_text(scheduler_source.read_text())

text = server.read_text()
if 'internal/embeddedusage' not in text:
    text = text.replace(
        '"github.com/router-for-me/CLIProxyAPI/v6/internal/config"\n',
        '"github.com/router-for-me/CLIProxyAPI/v6/internal/config"\n\t"github.com/router-for-me/CLIProxyAPI/v6/internal/embeddedusage"\n',
        1,
    )
server.write_text(text)

replace_once(
    server,
    '''\thealthzHandler := func(c *gin.Context) {
\t\tif c.Request.Method == http.MethodHead {
\t\t\tc.Status(http.StatusOK)
\t\t\treturn
\t\t}

\t\tc.JSON(http.StatusOK, gin.H{"status": "ok"})
\t}
\ts.engine.GET("/healthz", healthzHandler)
\ts.engine.HEAD("/healthz", healthzHandler)
''',
    '''\thealthzHandler := func(c *gin.Context) {
\t\tif c.Request.Method == http.MethodHead {
\t\t\tc.Status(http.StatusOK)
\t\t\treturn
\t\t}

\t\tc.JSON(http.StatusOK, gin.H{
\t\t\t"status":  "ok",
\t\t\t"message": "CLI Proxy API Server",
\t\t\t"endpoints": []string{
\t\t\t\t"POST /v1/chat/completions",
\t\t\t\t"POST /v1/completions",
\t\t\t\t"GET /v1/models",
\t\t\t},
\t\t})
\t}
\ts.engine.GET("/healthz", healthzHandler)
\ts.engine.HEAD("/healthz", healthzHandler)
''',
)

replace_once(
    server,
    '''\t// Root endpoint
\ts.engine.GET("/", func(c *gin.Context) {
\t\tc.JSON(http.StatusOK, gin.H{
\t\t\t"message": "CLI Proxy API Server",
\t\t\t"endpoints": []string{
\t\t\t\t"POST /v1/chat/completions",
\t\t\t\t"POST /v1/completions",
\t\t\t\t"GET /v1/models",
\t\t\t},
\t\t})
\t})
''',
    '''\t// Root endpoint
\ts.engine.GET("/", func(c *gin.Context) {
\t\tc.Redirect(http.StatusTemporaryRedirect, "/management.html")
\t})
''',
)

replace_once(
    server,
    '''\t{
\t\tmgmt.GET("/config", s.mgmt.GetConfig)
''',
    '''\t{
\t\tembeddedusage.RegisterGinRoutes(mgmt.Group("/usage"))

\t\tmgmt.GET("/config", s.mgmt.GetConfig)
''',
)

replace_once(
    server,
    '''\t\tmgmt.POST("/api-call", s.mgmt.APICall)\n''',
    '''\t\tmgmt.POST("/api-call", s.mgmt.APICall)\n\t\ts.mgmt.RegisterAccountInspectionRoutes(mgmt)\n''',
)

handler = ROOT / 'internal/api/handlers/management/handler.go'
replace_once(
    handler,
    '''\th.startAttemptCleanup()\n\treturn h\n''',
    '''\th.startAccountInspectionScheduler()\n\th.startAttemptCleanup()\n\treturn h\n''',
)

run = ROOT / 'internal/cmd/run.go'
text = run.read_text()
if 'internal/embeddedusage' not in text:
    text = text.replace(
        '"github.com/router-for-me/CLIProxyAPI/v6/internal/config"\n',
        '"github.com/router-for-me/CLIProxyAPI/v6/internal/config"\n\t"github.com/router-for-me/CLIProxyAPI/v6/internal/embeddedusage"\n',
        1,
    )
run.write_text(text)

replace_once(
    run,
    '''\tservice, err := builder.Build()
''',
    '''\tusageService, err := embeddedusage.Start(runCtx)
\tif err != nil {
\t\tlog.Errorf("failed to start embedded usage service: %v", err)
\t\treturn
\t}
\tembeddedusage.SetDefaultService(usageService)
\tif usageService != nil {
\t\tcfg.UsageStatisticsEnabled = true
\t}

\tservice, err := builder.Build()
''',
)

replace_once(
    run,
    '''\tservice, err := builder.Build()
\tif err != nil {
\t\tlog.Errorf("failed to build proxy service: %v", err)
\t\tclose(doneCh)
\t\treturn cancelFn, doneCh
\t}
''',
    '''\tusageService, err := embeddedusage.Start(ctx)
\tif err != nil {
\t\tlog.Errorf("failed to start embedded usage service: %v", err)
\t\tclose(doneCh)
\t\treturn cancelFn, doneCh
\t}
\tembeddedusage.SetDefaultService(usageService)
\tif usageService != nil {
\t\tcfg.UsageStatisticsEnabled = true
\t}

\tservice, err := builder.Build()
\tif err != nil {
\t\tlog.Errorf("failed to build proxy service: %v", err)
\t\tclose(doneCh)
\t\treturn cancelFn, doneCh
\t}
''',
)

auth_conductor = ROOT / 'sdk/cliproxy/auth/conductor.go'
replace_once(
    auth_conductor,
    '''func (m *Manager) shouldRefresh(a *Auth, now time.Time) bool {
\tif a == nil || a.Disabled {
\t\treturn false
\t}
\tif !a.NextRefreshAfter.IsZero() && now.Before(a.NextRefreshAfter) {
\t\treturn false
\t}
\tif evaluator, ok := a.Runtime.(RefreshEvaluator); ok && evaluator != nil {
\t\treturn evaluator.ShouldRefresh(now, a)
\t}

\tlastRefresh := a.LastRefreshedAt
\tif lastRefresh.IsZero() {
\t\tif ts, ok := authLastRefreshTimestamp(a); ok {
\t\t\tlastRefresh = ts
\t\t}
\t}

\texpiry, hasExpiry := a.ExpirationTime()

\tif interval := authPreferredInterval(a); interval > 0 {
\t\tif hasExpiry && !expiry.IsZero() {
\t\t\tif !expiry.After(now) {
\t\t\t\treturn true
\t\t\t}
\t\t\tif expiry.Sub(now) <= interval {
\t\t\t\treturn true
\t\t\t}
\t\t}
\t\tif lastRefresh.IsZero() {
\t\t\treturn true
\t\t}
\t\treturn now.Sub(lastRefresh) >= interval
\t}

\tprovider := strings.ToLower(a.Provider)
\tlead := ProviderRefreshLead(provider, a.Runtime)
\tif lead == nil {
\t\treturn false
\t}
\tif *lead <= 0 {
\t\tif hasExpiry && !expiry.IsZero() {
\t\t\treturn now.After(expiry)
\t\t}
\t\treturn false
\t}
\tif hasExpiry && !expiry.IsZero() {
\t\treturn time.Until(expiry) <= *lead
\t}
\tif !lastRefresh.IsZero() {
\t\treturn now.Sub(lastRefresh) >= *lead
\t}
\treturn true
}
''',
    '''func (m *Manager) shouldRefresh(a *Auth, now time.Time) bool {
\tif a == nil || a.Disabled {
\t\treturn false
\t}
\treturn m.shouldRefreshForInspection(a, now)
}

func (m *Manager) shouldRefreshForInspection(a *Auth, now time.Time) bool {
\tif a == nil {
\t\treturn false
\t}
\tif !a.NextRefreshAfter.IsZero() && now.Before(a.NextRefreshAfter) {
\t\treturn false
\t}
\tif evaluator, ok := a.Runtime.(RefreshEvaluator); ok && evaluator != nil {
\t\treturn evaluator.ShouldRefresh(now, a)
\t}

\tlastRefresh := a.LastRefreshedAt
\tif lastRefresh.IsZero() {
\t\tif ts, ok := authLastRefreshTimestamp(a); ok {
\t\t\tlastRefresh = ts
\t\t}
\t}

\texpiry, hasExpiry := a.ExpirationTime()

\tif interval := authPreferredInterval(a); interval > 0 {
\t\tif hasExpiry && !expiry.IsZero() {
\t\t\tif !expiry.After(now) {
\t\t\t\treturn true
\t\t\t}
\t\t\tif expiry.Sub(now) <= interval {
\t\t\t\treturn true
\t\t\t}
\t\t}
\t\tif lastRefresh.IsZero() {
\t\t\treturn true
\t\t}
\t\treturn now.Sub(lastRefresh) >= interval
\t}

\tprovider := strings.ToLower(a.Provider)
\tlead := ProviderRefreshLead(provider, a.Runtime)
\tif lead == nil {
\t\treturn false
\t}
\tif *lead <= 0 {
\t\tif hasExpiry && !expiry.IsZero() {
\t\t\treturn now.After(expiry)
\t\t}
\t\treturn false
\t}
\tif hasExpiry && !expiry.IsZero() {
\t\treturn time.Until(expiry) <= *lead
\t}
\tif !lastRefresh.IsZero() {
\t\treturn now.Sub(lastRefresh) >= *lead
\t}
\treturn true
}
''',
)

replace_once(
    auth_conductor,
    '''func (m *Manager) markRefreshPending(id string, now time.Time) bool {
\tm.mu.Lock()
\tauth, ok := m.auths[id]
\tif !ok || auth == nil || auth.Disabled {
\t\tm.mu.Unlock()
\t\treturn false
\t}
\tif !auth.NextRefreshAfter.IsZero() && now.Before(auth.NextRefreshAfter) {
\t\tm.mu.Unlock()
\t\treturn false
\t}
\tauth.NextRefreshAfter = now.Add(refreshPendingBackoff)
\tm.auths[id] = auth
\tm.mu.Unlock()

\tm.queueRefreshReschedule(id)
\treturn true
}
''',
    '''func (m *Manager) markRefreshPending(id string, now time.Time) bool {
\treturn m.markRefreshPendingWithDisabled(id, now, false)
}

func (m *Manager) markRefreshPendingForInspection(id string, now time.Time) bool {
\treturn m.markRefreshPendingWithDisabled(id, now, true)
}

func (m *Manager) markRefreshPendingWithDisabled(id string, now time.Time, allowDisabled bool) bool {
\tm.mu.Lock()
\tauth, ok := m.auths[id]
\tif !ok || auth == nil || (!allowDisabled && auth.Disabled) {
\t\tm.mu.Unlock()
\t\treturn false
\t}
\tif !auth.NextRefreshAfter.IsZero() && now.Before(auth.NextRefreshAfter) {
\t\tm.mu.Unlock()
\t\treturn false
\t}
\tauth.NextRefreshAfter = now.Add(refreshPendingBackoff)
\tm.auths[id] = auth
\tm.mu.Unlock()

\tm.queueRefreshReschedule(id)
\treturn true
}
''',
)

replace_once(
    auth_conductor,
    '''func (m *Manager) refreshAuth(ctx context.Context, id string) {
''',
    '''func (m *Manager) RefreshIfDueForInspection(ctx context.Context, id string) (*Auth, bool, error) {
\tif ctx == nil {
\t\tctx = context.Background()
\t}
\tnow := time.Now()
\tm.mu.RLock()
\tauth := m.auths[id]
\tif auth == nil {
\t\tm.mu.RUnlock()
\t\treturn nil, false, nil
\t}
\tcurrent := auth.Clone()
\taccountType, _ := auth.AccountInfo()
\tif accountType == "api_key" || !m.shouldRefreshForInspection(auth, now) {
\t\tm.mu.RUnlock()
\t\treturn current, false, nil
\t}
\texec := m.executors[auth.Provider]
\tm.mu.RUnlock()
\tif exec == nil {
\t\treturn current, false, nil
\t}
\tif !m.markRefreshPendingForInspection(id, now) {
\t\tm.mu.RLock()
\t\tdefer m.mu.RUnlock()
\t\tif latest := m.auths[id]; latest != nil {
\t\t\treturn latest.Clone(), false, nil
\t\t}
\t\treturn nil, false, nil
\t}

\tm.mu.RLock()
\tauth = m.auths[id]
\tif auth == nil {
\t\tm.mu.RUnlock()
\t\treturn nil, false, nil
\t}
\texec = m.executors[auth.Provider]
\tcloned := auth.Clone()
\tpreservedDisabled := auth.Disabled
\tpreservedStatus := auth.Status
\tpreservedStatusMessage := auth.StatusMessage
\tm.mu.RUnlock()
\tif exec == nil {
\t\treturn cloned, false, nil
\t}

\tupdated, err := exec.Refresh(ctx, cloned)
\tif err != nil && errors.Is(err, context.Canceled) {
\t\treturn cloned, false, err
\t}
\tnow = time.Now()
\tif err != nil {
\t\tm.mu.Lock()
\t\tif current := m.auths[id]; current != nil {
\t\t\tcurrent.NextRefreshAfter = now.Add(refreshFailureBackoff)
\t\t\tcurrent.LastError = &Error{Message: err.Error()}
\t\t\tm.auths[id] = current
\t\t\tif m.scheduler != nil {
\t\t\t\tm.scheduler.upsertAuth(current.Clone())
\t\t\t}
\t\t}
\t\tm.mu.Unlock()
\t\tm.queueRefreshReschedule(id)
\t\treturn cloned, false, err
\t}
\tif updated == nil {
\t\tupdated = cloned
\t}
\tif updated.Runtime == nil {
\t\tupdated.Runtime = auth.Runtime
\t}
\tupdated.Disabled = preservedDisabled
\tif preservedDisabled {
\t\tupdated.Status = preservedStatus
\t\tupdated.StatusMessage = preservedStatusMessage
\t}
\tupdated.LastRefreshedAt = now
\tupdated.NextRefreshAfter = time.Time{}
\tupdated.LastError = nil
\tupdated.UpdatedAt = now
\tif m.shouldRefreshForInspection(updated, now) {
\t\tupdated.NextRefreshAfter = now.Add(refreshIneffectiveBackoff)
\t}
\tsaved, err := m.Update(ctx, updated)
\tif err != nil {
\t\treturn updated, false, err
\t}
\treturn saved, true, nil
}

func (m *Manager) refreshAuth(ctx context.Context, id string) {
''',
)
