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
