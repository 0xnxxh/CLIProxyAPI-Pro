#!/usr/bin/env python3
import hashlib
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get('SRC_ROOT', '/src/CLIProxyAPI'))
PATCH_SOURCE_DIR = Path(__file__).resolve().parent / 'sources'
PRO_PANEL_REPOSITORY = 'https://github.com/ssfun/CLIProxyAPI-Pro'
PRO_PANEL_RELEASE_API = 'https://api.github.com/repos/ssfun/CLIProxyAPI-Pro/releases/latest'


_writes = {}


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding='utf-8')


def read(path: Path) -> str:
    if path in _writes:
        return _writes[path]
    return read_text(path)


def write(path: Path, text: str) -> None:
    _writes[path] = text


def require_source_hash(path: Path, allowed_hashes: set[str]) -> None:
    digest = hashlib.sha256(read(path).encode('utf-8')).hexdigest()
    if digest not in allowed_hashes:
        raise SystemExit(f'upstream source changed before full-file replacement: {path} ({digest})')


def module_path() -> str:
    match = re.search(r'^module\s+(\S+)', read_text(ROOT / 'go.mod'), re.MULTILINE)
    if not match:
        raise SystemExit(f'module path not found in {ROOT / "go.mod"}')
    return match.group(1)


def import_path(suffix: str) -> str:
    return f'{MODULE_PATH}/{suffix}'


def flush_writes() -> None:
    for path, text in _writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, text)
    _writes.clear()


def queue_tree(source: Path, target: Path) -> None:
    for source_path in source.rglob('*'):
        if source_path.is_dir():
            continue
        text = read_text(source_path)
        if source_path.suffix == '.go':
            text = re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, text)
        write(target / source_path.relative_to(source), text)


def queue_go_source(relative_path: str) -> None:
    source = PATCH_SOURCE_DIR / relative_path
    if not source.is_file():
        raise SystemExit(f'Go patch source not found: {source}')
    text = re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(source))
    write(ROOT / relative_path, text)


def replace_once(path: Path, old: str, new: str, present=None) -> None:
    text = read(path)
    if (present or new) and (present or new) in text:
        return
    match_count = text.count(old)
    if match_count != 1:
        raise SystemExit(f'expected one pattern in {path}, found {match_count}: {old[:120]!r}')
    write(path, text.replace(old, new, 1))


def insert_before(path: Path, marker: str, insertion: str, present: str) -> None:
    text = read(path)
    if present in text:
        return
    match_count = text.count(marker)
    if match_count != 1:
        raise SystemExit(f'expected one marker in {path}, found {match_count}: {marker[:120]!r}')
    write(path, text.replace(marker, insertion + marker, 1))


def ensure_go_require(path: Path, module: str, version: str) -> None:
    text = read(path)
    if re.search(rf'^\s*{re.escape(module)}\s+', text, re.MULTILINE):
        return
    line = f'\t{module} {version}\n'
    marker = 'require (\n'
    if marker in text:
        write(path, text.replace(marker, marker + line, 1))
        return
    write(path, text.rstrip() + f'\n\nrequire {module} {version}\n')


def insert_before_nth(path: Path, marker: str, insertion: str, occurrence: int, present: str) -> None:
    text = read(path)
    if present in text:
        return
    start = -1
    for _ in range(occurrence):
        start = text.find(marker, start + 1)
        if start < 0:
            raise SystemExit(f'pattern occurrence {occurrence} not found in {path}: {marker[:120]!r}')
    write(path, text[:start] + insertion + text[start:])


def add_go_import(path: Path, after: str, import_line: str) -> None:
    text = read(path)
    if import_line.strip() in text:
        return
    if after not in text:
        raise SystemExit(f'import anchor not found in {path}: {after[:120]!r}')
    write(path, text.replace(after, after + import_line, 1))


def replace_go_function(path: Path, signature: str, new_function: str, present: str) -> None:
    text = read(path)
    if present in text:
        return
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f'function not found in {path}: {signature!r}')
    brace = text.find('{', start)
    if brace < 0:
        raise SystemExit(f'function body not found in {path}: {signature!r}')
    depth = 0
    for index in range(brace, len(text)):
        char = text[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = index + 1
                if end < len(text) and text[end] == '\n':
                    end += 1
                write(path, text[:start] + new_function + text[end:])
                return
    raise SystemExit(f'function body end not found in {path}: {signature!r}')


def replace_go_call_block(path: Path, call_start: str, new_block: str, present: str) -> None:
    text = read(path)
    if present in text:
        return
    start = text.find(call_start)
    if start < 0:
        raise SystemExit(f'call block not found in {path}: {call_start!r}')
    brace = text.find('{', start)
    if brace < 0:
        raise SystemExit(f'call block body not found in {path}: {call_start!r}')
    depth = 0
    for index in range(brace, len(text)):
        char = text[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = index + 1
                while end < len(text) and text[end] in ')\n':
                    end += 1
                    if text[end - 1] == '\n':
                        break
                write(path, text[:start] + new_block + text[end:])
                return
    raise SystemExit(f'call block end not found in {path}: {call_start!r}')


MODULE_PATH = module_path()
customization_sentinel = ROOT / 'internal/embeddedusage'
if customization_sentinel.exists():
    raise SystemExit(f'target already contains CLIProxyAPI Pro customizations: {customization_sentinel}')

new_customization_paths = (
    'internal/api/handlers/management/account_inspection_scheduler.go',
    'internal/api/handlers/management/account_inspection_scheduler_test.go',
    'internal/api/handlers/management/plugin_quota.go',
    'internal/api/handlers/management/plugin_quota_test.go',
    'internal/api/handlers/management/routing_policy.go',
    'internal/api/handlers/management/routing_policy_test.go',
    'internal/config/routing_protection_config.go',
    'internal/pluginhost/gemini_cli_quota_legacy.go',
    'internal/pluginhost/gemini_cli_quota_legacy_test.go',
    'internal/pluginhost/gemini_cli_storage_compat.go',
    'internal/pluginhost/gemini_cli_storage_compat_test.go',
    'internal/pluginhost/quota_provider.go',
    'internal/pluginhost/quota_provider_test.go',
    'internal/pluginstore/autoinstall.go',
    'internal/pluginstore/autoinstall_test.go',
    'internal/requestmeta/requestid.go',
    'internal/requestmeta/response.go',
    'sdk/cliproxy/auth/auth_runtime_state.go',
    'sdk/cliproxy/auth/auth_runtime_state_test.go',
    'sdk/cliproxy/auth/inspection_refresh.go',
)
for relative_path in new_customization_paths:
    target_path = ROOT / relative_path
    if target_path.exists():
        raise SystemExit(f'upstream path collides with a Pro customization: {target_path}')

require_source_hash(
    ROOT / 'internal/logging/requestid.go',
    {'69d256ca4c4a75759395f6ed6640e9d2673c777e111fcae80faa7b6eea5b15ac'},
)
require_source_hash(
    ROOT / 'internal/logging/requestmeta.go',
    {'aa13ac5136573dba6a4feb9243cad2663b300053288c3b0f6eeaaee26ca09c28'},
)

# Add the optional QuotaProvider capability without changing ABI/schema v1.
pluginapi_types = ROOT / 'sdk/pluginapi/types.go'
replace_once(
    pluginapi_types,
    '\t// FrontendAuthProvider authenticates frontend requests before proxy handling.\n',
    '\t// QuotaProvider fetches normalized per-auth quota and subscription snapshots.\n\tQuotaProvider QuotaProvider\n\t// FrontendAuthProvider authenticates frontend requests before proxy handling.\n',
    'QuotaProvider QuotaProvider',
)
insert_before(
    pluginapi_types,
    '// ModelRegistrar registers plugin-provided models with the host.\n',
    read_text(Path(__file__).resolve().parent / 'plugin_quota_api.go'),
    'type QuotaProvider interface',
)

pluginabi_types = ROOT / 'sdk/pluginabi/types.go'
replace_once(
    pluginabi_types,
    '\tMethodAuthRefresh    = "auth.refresh"\n',
    '\tMethodAuthRefresh    = "auth.refresh"\n\n\tMethodQuotaIdentifier = "quota.identifier"\n\tMethodQuotaFetch      = "quota.fetch"\n',
    'MethodQuotaIdentifier',
)

rpc_schema = ROOT / 'internal/pluginhost/rpc_schema.go'
replace_once(
    rpc_schema,
    '\tAuthProvider                  bool                         `json:"auth_provider"`\n',
    '\tAuthProvider                  bool                         `json:"auth_provider"`\n\tQuotaProvider                 bool                         `json:"quota_provider"`\n',
    'QuotaProvider                 bool',
)
insert_before(
    rpc_schema,
    'type rpcAuthModelRequest struct {\n',
    '''type rpcQuotaFetchRequest struct {
\tpluginapi.QuotaFetchRequest
\tHostCallbackID string `json:"host_callback_id,omitempty"`
}

''',
    'type rpcQuotaFetchRequest struct',
)
replace_once(
    rpc_schema,
    '\t\tAuthProvider:                  caps.AuthProvider != nil,\n',
    '\t\tAuthProvider:                  caps.AuthProvider != nil,\n\t\tQuotaProvider:                 caps.QuotaProvider != nil,\n',
    'QuotaProvider:                 caps.QuotaProvider != nil',
)

rpc_client = ROOT / 'internal/pluginhost/rpc_client.go'
insert_before(
    rpc_client,
    'type rpcFrontendAuthProvider struct {\n',
    '''type rpcQuotaProvider struct {
\t*rpcPluginAdapter
}

''',
    'type rpcQuotaProvider struct',
)
replace_once(
    rpc_client,
    '''\tif resp.Capabilities.FrontendAuthProvider {
\t\tplugin.Capabilities.FrontendAuthProvider = rpcFrontendAuthProvider{rpcPluginAdapter: adapter}
\t}
''',
    '''\tif resp.Capabilities.QuotaProvider {
\t\tplugin.Capabilities.QuotaProvider = rpcQuotaProvider{rpcPluginAdapter: adapter}
\t}
\tif resp.Capabilities.FrontendAuthProvider {
\t\tplugin.Capabilities.FrontendAuthProvider = rpcFrontendAuthProvider{rpcPluginAdapter: adapter}
\t}
''',
    'plugin.Capabilities.QuotaProvider = rpcQuotaProvider',
)
replace_once(
    rpc_client,
    '''\tcase pluginapi.AuthRefreshRequest:
\t\treq.HTTPClient = nil
\t\treturn req
''',
    '''\tcase pluginapi.AuthRefreshRequest:
\t\treq.HTTPClient = nil
\t\treturn req
\tcase pluginapi.QuotaFetchRequest:
\t\treq.HTTPClient = nil
\t\treturn req
\tcase rpcQuotaFetchRequest:
\t\treq.HTTPClient = nil
\t\treturn req
''',
    'case pluginapi.QuotaFetchRequest:',
)
insert_before(
    rpc_client,
    'func sanitizePluginMetadata(src map[string]any) map[string]any {\n',
    '''func (p rpcQuotaProvider) Identifier() string {
\treturn callPluginIdentifier(p.client, pluginabi.MethodQuotaIdentifier)
}

func (p rpcQuotaProvider) FetchQuota(ctx context.Context, req pluginapi.QuotaFetchRequest) (pluginapi.QuotaFetchResponse, error) {
\tcallbackID, closeCallback := p.openHostCallbackContext(ctx)
\tdefer closeCallback()
\treturn callPlugin[pluginapi.QuotaFetchResponse](ctx, p.client, pluginabi.MethodQuotaFetch, rpcQuotaFetchRequest{
\t\tQuotaFetchRequest: req,
\t\tHostCallbackID:    callbackID,
\t})
}

''',
    'func (p rpcQuotaProvider) FetchQuota',
)

plugin_host = ROOT / 'internal/pluginhost/host.go'
replace_once(
    plugin_host,
    '\t\tcaps.AuthProvider != nil ||\n',
    '\t\tcaps.AuthProvider != nil ||\n\t\tcaps.QuotaProvider != nil ||\n',
    'caps.QuotaProvider != nil',
)

plugin_snapshot = ROOT / 'internal/pluginhost/snapshot.go'
replace_once(
    plugin_snapshot,
    '\tOAuthProvider string\n',
    '\tOAuthProvider string\n\tSupportsQuota bool\n\tQuotaProvider string\n\tQuotaMode     string\n',
    'SupportsQuota bool',
)
replace_once(
    plugin_snapshot,
    '''\t\tout = append(out, RegisteredPluginInfo{
''',
    '''\t\tquotaProvider := record.plugin.Capabilities.QuotaProvider
\t\tquotaProviderID := ""
\t\tquotaMode := ""
\t\tsupportsQuota := quotaProvider != nil
\t\tif quotaProvider != nil && !h.isPluginFused(record.id) {
\t\t\tif identifier, okIdentifier := h.callQuotaProviderIdentifier(record.id, quotaProvider); okIdentifier {
\t\t\t\tquotaProviderID = identifier
\t\t\t\tquotaMode = "native"
\t\t\t}
\t\t} else if identifier, okLegacy := h.legacyQuotaProviderForRecord(record); okLegacy {
\t\t\tquotaProviderID = identifier
\t\t\tquotaMode = "legacy-adapter"
\t\t\tsupportsQuota = true
\t\t}
\t\tout = append(out, RegisteredPluginInfo{
''',
    'quotaProvider := record.plugin.Capabilities.QuotaProvider',
)
replace_once(
    plugin_snapshot,
    '\t\t\tOAuthProvider: oauthProvider,\n',
    '\t\t\tOAuthProvider: oauthProvider,\n\t\t\tSupportsQuota: supportsQuota,\n\t\t\tQuotaProvider: quotaProviderID,\n\t\t\tQuotaMode: quotaMode,\n',
    'QuotaProvider: quotaProviderID',
)

management_plugins = ROOT / 'internal/api/handlers/management/plugins.go'
replace_once(
    management_plugins,
    '\tOAuthProvider    string                  `json:"oauth_provider"`\n',
    '\tOAuthProvider    string                  `json:"oauth_provider"`\n\tSupportsQuota    bool                    `json:"supports_quota"`\n\tQuotaProvider    string                  `json:"quota_provider"`\n\tQuotaMode        string                  `json:"quota_mode"`\n',
    'SupportsQuota    bool',
)
replace_once(
    management_plugins,
    '\t\t\tentry.OAuthProvider = htmlsanitize.String(info.OAuthProvider)\n',
    '\t\t\tentry.OAuthProvider = htmlsanitize.String(info.OAuthProvider)\n\t\t\tentry.SupportsQuota = info.SupportsQuota\n\t\t\tentry.QuotaProvider = htmlsanitize.String(info.QuotaProvider)\n\t\t\tentry.QuotaMode = htmlsanitize.String(info.QuotaMode)\n',
    'entry.SupportsQuota = info.SupportsQuota',
)

quota_provider_source = Path(__file__).resolve().parent / 'plugin_quota_provider.go'
quota_provider_target = ROOT / 'internal/pluginhost/quota_provider.go'
write(quota_provider_target, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(quota_provider_source)))
quota_provider_test_source = Path(__file__).resolve().parent / 'plugin_quota_provider_test.go'
quota_provider_test_target = ROOT / 'internal/pluginhost/quota_provider_test.go'
write(quota_provider_test_target, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(quota_provider_test_source)))

legacy_gemini_quota_source = Path(__file__).resolve().parent / 'plugin_gemini_cli_quota_legacy.go'
legacy_gemini_quota_target = ROOT / 'internal/pluginhost/gemini_cli_quota_legacy.go'
write(legacy_gemini_quota_target, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(legacy_gemini_quota_source)))
legacy_gemini_quota_test_source = Path(__file__).resolve().parent / 'plugin_gemini_cli_quota_legacy_test.go'
legacy_gemini_quota_test_target = ROOT / 'internal/pluginhost/gemini_cli_quota_legacy_test.go'
write(legacy_gemini_quota_test_target, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(legacy_gemini_quota_test_source)))

plugin_quota_management = ROOT / 'internal/api/handlers/management/plugin_quota.go'
write(plugin_quota_management, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(Path(__file__).resolve().parent / 'plugin_quota_management.go')))
plugin_quota_management_test = ROOT / 'internal/api/handlers/management/plugin_quota_test.go'
write(plugin_quota_management_test, read_text(Path(__file__).resolve().parent / 'plugin_quota_management_test.go'))

usage_manager = ROOT / 'sdk/cliproxy/usage/manager.go'
add_go_import(usage_manager, '"net/http"\n', '\t"reflect"\n')
replace_once(
    usage_manager,
    'type serviceTierContextKey struct{}\n',
    'type serviceTierContextKey struct{}\ntype streamContextKey struct{}\n',
)
insert_before(
    usage_manager,
    '// WithServiceTier stores the client-requested service tier for usage sinks.\n',
    '''// WithStream stores whether the client requested streaming output for usage sinks.
func WithStream(ctx context.Context, stream bool) context.Context {
\tif ctx == nil {
\t\tctx = context.Background()
\t}
\treturn context.WithValue(ctx, streamContextKey{}, stream)
}

// StreamFromContext returns whether the client requested streaming output.
func StreamFromContext(ctx context.Context) bool {
\tif ctx == nil {
\t\treturn false
\t}
\tstream, _ := ctx.Value(streamContextKey{}).(bool)
\treturn stream
}

''',
    'func WithStream(ctx context.Context, stream bool) context.Context',
)
replace_once(
    usage_manager,
    '''\tm.named[name] = len(m.plugins)
\tm.plugins = append(m.plugins, plugin)
\tm.pluginsMu.Unlock()
''',
    '''\tfor index, existing := range m.plugins {
\t\tif existing == nil {
\t\t\tm.named[name] = index
\t\t\tm.plugins[index] = plugin
\t\t\tm.pluginsMu.Unlock()
\t\t\treturn
\t\t}
\t}
\tm.named[name] = len(m.plugins)
\tm.plugins = append(m.plugins, plugin)
\tm.pluginsMu.Unlock()
''',
    'for index, existing := range m.plugins',
)
insert_before(
    usage_manager,
    '// Publish enqueues a usage record for processing. If no plugin is registered\n',
    '''// UnregisterNamed removes a named plugin only when the current registration
// still belongs to the supplied plugin. Passing nil removes it unconditionally.
func (m *Manager) UnregisterNamed(name string, plugin Plugin) {
\tif m == nil {
\t\treturn
\t}
\tname = strings.TrimSpace(name)
\tif name == "" {
\t\treturn
\t}
\tm.pluginsMu.Lock()
\tdefer m.pluginsMu.Unlock()
\tindex, exists := m.named[name]
\tif !exists || index < 0 || index >= len(m.plugins) {
\t\treturn
\t}
\tcurrent := m.plugins[index]
\tif plugin != nil && !samePlugin(current, plugin) {
\t\treturn
\t}
\tm.plugins[index] = nil
\tdelete(m.named, name)
}

func samePlugin(left, right Plugin) bool {
\tif left == nil || right == nil {
\t\treturn left == nil && right == nil
\t}
\tleftValue := reflect.ValueOf(left)
\trightValue := reflect.ValueOf(right)
\treturn leftValue.Type() == rightValue.Type() &&
\t\tleftValue.Type().Comparable() &&
\t\tleftValue.Interface() == rightValue.Interface()
}

''',
    'func (m *Manager) UnregisterNamed(name string, plugin Plugin)',
)
insert_before(
    usage_manager,
    '// PublishRecord publishes a record using the default manager.\n',
    '''// UnregisterNamedPlugin removes a matching named plugin from the default manager.
func UnregisterNamedPlugin(name string, plugin Plugin) { DefaultManager().UnregisterNamed(name, plugin) }

''',
    'func UnregisterNamedPlugin(name string, plugin Plugin)',
)

usage_manager_test = ROOT / 'sdk/cliproxy/usage/manager_test.go'
if 'func TestUnregisterNamedPreservesReplacement' not in read(usage_manager_test):
    write(usage_manager_test, read(usage_manager_test).rstrip() + '''

type namedLifecycleUsagePlugin struct {
\tcalls int
}

func (p *namedLifecycleUsagePlugin) HandleUsage(context.Context, Record) {
\tp.calls++
}

func TestUnregisterNamedPreservesReplacement(t *testing.T) {
\tmanager := NewManager(1)
\tfirst := &namedLifecycleUsagePlugin{}
\treplacement := &namedLifecycleUsagePlugin{}
\tmanager.RegisterNamed("lifecycle", first)
\tmanager.RegisterNamed("lifecycle", replacement)

\tmanager.UnregisterNamed("lifecycle", first)
\tmanager.dispatch(queueItem{ctx: context.Background(), record: Record{}})
\tif replacement.calls != 1 {
\t\tt.Fatalf("replacement calls = %d, want 1", replacement.calls)
\t}

\tmanager.UnregisterNamed("lifecycle", replacement)
\tmanager.dispatch(queueItem{ctx: context.Background(), record: Record{}})
\tif replacement.calls != 1 {
\t\tt.Fatalf("replacement calls after unregister = %d, want 1", replacement.calls)
\t}

\tmanager.RegisterNamed("lifecycle", first)
\tmanager.dispatch(queueItem{ctx: context.Background(), record: Record{}})
\tif first.calls != 1 {
\t\tt.Fatalf("re-registered plugin calls = %d, want 1", first.calls)
\t}
}
''')

auth_conductor = ROOT / 'sdk/cliproxy/auth/conductor.go'
replace_once(
    auth_conductor,
    '\tctx = coreusage.WithRequestedModelAlias(ctx, alias)\n',
    '\tctx = coreusage.WithRequestedModelAlias(ctx, alias)\n\tctx = coreusage.WithStream(ctx, opts.Stream)\n',
)

config_go = ROOT / 'internal/config/config.go'
replace_once(
    config_go,
    'DefaultPanelGitHubRepository = "https://github.com/router-for-me/Cli-Proxy-API-Management-Center"',
    f'DefaultPanelGitHubRepository = "{PRO_PANEL_REPOSITORY}"',
)

sdk_config_go = ROOT / 'internal/config/sdk_config.go'
replace_once(
    sdk_config_go,
    '''\tForceModelPrefix bool `yaml:"force-model-prefix" json:"force-model-prefix"`

\t// RequestLog enables or disables detailed request logging functionality.
''',
    '''\tForceModelPrefix bool `yaml:"force-model-prefix" json:"force-model-prefix"`

\t// ClaudeModelIDCloakMode controls whether non-Claude model IDs are disguised in
\t// Anthropic-compatible model listings. Supported values are auto, always, and never.
\t// Empty and invalid values use auto, which cloaks only identified Claude Desktop clients.
\tClaudeModelIDCloakMode string `yaml:"claude-model-id-cloak-mode,omitempty" json:"claude-model-id-cloak-mode,omitempty"`

\t// RequestLog enables or disables detailed request logging functionality.
''',
)

claude_model_util = ROOT / 'internal/util/claude_model.go'
replace_once(
    claude_model_util,
    'import "strings"\n',
    '''import (
\t"net/http"
\t"strings"
)
''',
)
insert_before(
    claude_model_util,
    '// EnsureClaudeModelIDPrefix rewrites model IDs for Anthropic /models listings.\n',
    '''const (
\tClaudeModelIDCloakModeAuto   = "auto"
\tClaudeModelIDCloakModeAlways = "always"
\tClaudeModelIDCloakModeNever  = "never"
)

// ShouldCloakClaudeModelIDs reports whether an Anthropic-compatible model listing
// should disguise non-Claude model IDs for the current client.
func ShouldCloakClaudeModelIDs(mode string, headers http.Header) bool {
\tswitch strings.ToLower(strings.TrimSpace(mode)) {
\tcase ClaudeModelIDCloakModeAlways:
\t\treturn true
\tcase ClaudeModelIDCloakModeNever:
\t\treturn false
\tdefault:
\t\treturn isClaudeDesktopModelClient(headers)
\t}
}

func isClaudeDesktopModelClient(headers http.Header) bool {
\tif headers == nil {
\t\treturn false
\t}
\tfor _, value := range []string{
\t\theaders.Get("User-Agent"),
\t\theaders.Get("X-Client-Name"),
\t\theaders.Get("X-Application-Name"),
\t} {
\t\tcompact := strings.NewReplacer("-", "", "_", "", " ", "").Replace(strings.ToLower(strings.TrimSpace(value)))
\t\tif strings.Contains(compact, "claudedesktop") {
\t\t\treturn true
\t\t}
\t}
\treturn false
}

''',
    'func ShouldCloakClaudeModelIDs(mode string, headers http.Header) bool',
)

claude_handler = ROOT / 'sdk/api/handlers/claude/code_handlers.go'
replace_once(
    claude_handler,
    '''func (h *ClaudeCodeAPIHandler) ClaudeModels(c *gin.Context) {
\tmodels := h.Models()
\tfor i := range models {
\t\tif id, ok := models[i]["id"].(string); ok {
\t\t\tmodels[i]["id"] = util.EnsureClaudeModelIDPrefix(id)
\t\t}
\t}
''',
    '''func (h *ClaudeCodeAPIHandler) ClaudeModels(c *gin.Context) {
\tmodels := h.Models()
\tmode := ""
\tif h != nil && h.BaseAPIHandler != nil && h.Cfg != nil {
\t\tmode = h.Cfg.ClaudeModelIDCloakMode
\t}
\tvar headers http.Header
\tif c != nil && c.Request != nil {
\t\theaders = c.Request.Header
\t}
\tif util.ShouldCloakClaudeModelIDs(mode, headers) {
\t\tfor i := range models {
\t\t\tif id, ok := models[i]["id"].(string); ok {
\t\t\t\tmodels[i]["id"] = util.EnsureClaudeModelIDPrefix(id)
\t\t\t}
\t\t}
\t}
''',
)

claude_model_util_test = ROOT / 'internal/util/claude_model_test.go'
replace_once(
    claude_model_util_test,
    'import "testing"\n',
    '''import (
\t"net/http"
\t"testing"
)
''',
)
if 'func TestShouldCloakClaudeModelIDs' not in read(claude_model_util_test):
    write(claude_model_util_test, read(claude_model_util_test).rstrip() + '''

func TestShouldCloakClaudeModelIDs(t *testing.T) {
\ttests := []struct {
\t\tname    string
\t\tmode    string
\t\theaders http.Header
\t\twant    bool
\t}{
\t\t{name: "auto detects desktop user agent", mode: "auto", headers: http.Header{"User-Agent": []string{"Claude-Desktop/1.0"}}, want: true},
\t\t{name: "auto detects desktop client header", mode: "auto", headers: http.Header{"X-Client-Name": []string{"Claude Desktop"}}, want: true},
\t\t{name: "auto leaves claude code unchanged", mode: "auto", headers: http.Header{"User-Agent": []string{"claude-cli/2.1.44"}}, want: false},
\t\t{name: "auto leaves generic anthropic client unchanged", mode: "auto", headers: http.Header{"User-Agent": []string{"Zed/1.0"}}, want: false},
\t\t{name: "empty defaults to auto", headers: http.Header{"User-Agent": []string{"ClaudeDesktop/1.0"}}, want: true},
\t\t{name: "always cloaks generic clients", mode: "always", headers: http.Header{"User-Agent": []string{"Zed/1.0"}}, want: true},
\t\t{name: "never leaves desktop unchanged", mode: "never", headers: http.Header{"User-Agent": []string{"Claude-Desktop/1.0"}}, want: false},
\t}

\tfor _, tt := range tests {
\t\tt.Run(tt.name, func(t *testing.T) {
\t\t\tif got := ShouldCloakClaudeModelIDs(tt.mode, tt.headers); got != tt.want {
\t\t\t\tt.Fatalf("ShouldCloakClaudeModelIDs(%q, %v) = %t, want %t", tt.mode, tt.headers, got, tt.want)
\t\t\t}
\t\t})
\t}
}
''' + '\n')

claude_handler_test = ROOT / 'sdk/api/handlers/claude/code_handlers_model_test.go'
add_go_import(claude_handler_test, '"encoding/json"\n', '\t"net/http"\n')
add_go_import(claude_handler_test, '"' + import_path('sdk/api/handlers') + '"\n', '\t"' + import_path('sdk/config') + '"\n')
if 'func TestClaudeModelsCloakMode' not in read(claude_handler_test):
    write(claude_handler_test, read(claude_handler_test).rstrip() + '''

func TestClaudeModelsCloakMode(t *testing.T) {
\tconst clientID = "claude-model-id-cloak-mode-test"
\tregistryRef := registry.GetGlobalRegistry()
\tregistryRef.RegisterClient(clientID, "claude", []*registry.ModelInfo{{
\t\tID: "gpt-4o", Object: "model", OwnedBy: "openai", DisplayName: "GPT-4o",
\t}})
\tt.Cleanup(func() {
\t\tregistryRef.UnregisterClient(clientID)
\t})

\ttests := []struct {
\t\tname       string
\t\tmode       string
\t\tuserAgent  string
\t\tclientName string
\t\twantID     string
\t}{
\t\t{name: "auto cloaks desktop", mode: "auto", userAgent: "Claude-Desktop/1.0", wantID: "claude-fable-5-dd-o4-tpg"},
\t\t{name: "auto cloaks desktop client header", mode: "auto", clientName: "Claude Desktop", wantID: "claude-fable-5-dd-o4-tpg"},
\t\t{name: "auto keeps claude code raw", mode: "auto", userAgent: "claude-cli/2.1.44", wantID: "gpt-4o"},
\t\t{name: "auto keeps generic client raw", mode: "auto", userAgent: "Zed/1.0", wantID: "gpt-4o"},
\t\t{name: "always cloaks generic client", mode: "always", userAgent: "Zed/1.0", wantID: "claude-fable-5-dd-o4-tpg"},
\t\t{name: "never keeps desktop raw", mode: "never", userAgent: "Claude-Desktop/1.0", wantID: "gpt-4o"},
\t}

\tfor _, tt := range tests {
\t\tt.Run(tt.name, func(t *testing.T) {
\t\t\trecorder := httptest.NewRecorder()
\t\t\tctx, _ := gin.CreateTestContext(recorder)
\t\t\tctx.Request = httptest.NewRequest(http.MethodGet, "/v1/models", nil)
\t\t\tif tt.userAgent != "" {
\t\t\t\tctx.Request.Header.Set("User-Agent", tt.userAgent)
\t\t\t}
\t\t\tif tt.clientName != "" {
\t\t\t\tctx.Request.Header.Set("X-Client-Name", tt.clientName)
\t\t\t}

\t\t\thandler := NewClaudeCodeAPIHandler(&handlers.BaseAPIHandler{
\t\t\t\tCfg: &config.SDKConfig{ClaudeModelIDCloakMode: tt.mode},
\t\t\t})
\t\t\thandler.ClaudeModels(ctx)

\t\t\tvar response struct {
\t\t\t\tData []struct {
\t\t\t\t\tID string `json:"id"`
\t\t\t\t} `json:"data"`
\t\t\t}
\t\t\tif errUnmarshal := json.Unmarshal(recorder.Body.Bytes(), &response); errUnmarshal != nil {
\t\t\t\tt.Fatalf("decode response: %v", errUnmarshal)
\t\t\t}
\t\t\tfor _, model := range response.Data {
\t\t\t\tif model.ID == tt.wantID {
\t\t\t\t\treturn
\t\t\t\t}
\t\t\t}
\t\t\tt.Fatalf("model %q not found in response: %s", tt.wantID, recorder.Body.String())
\t\t})
\t}
}
''' + '\n')

routing_protection_config = ROOT / 'internal/config/routing_protection_config.go'
write(routing_protection_config, read_text(Path(__file__).resolve().parent / 'routing_protection_config.go'))
replace_once(
    config_go,
    '''\tSessionAffinityTTL string `yaml:"session-affinity-ttl,omitempty" json:"session-affinity-ttl,omitempty"`
}
''',
    '''\tSessionAffinityTTL string `yaml:"session-affinity-ttl,omitempty" json:"session-affinity-ttl,omitempty"`

\t// RequestProtection controls request-driven provider credential disabling.
\tRequestProtection RequestProtectionConfig `yaml:"request-protection,omitempty" json:"request-protection,omitempty"`
}
''',
)

config_example = ROOT / 'config.example.yaml'
replace_once(
    config_example,
    '  panel-github-repository: "https://github.com/router-for-me/Cli-Proxy-API-Management-Center"',
    f'  panel-github-repository: "{PRO_PANEL_REPOSITORY}"',
)
replace_once(
    config_example,
    '''# "auto" behavior (cloak only non-Claude-Code clients).
disable-claude-cloak-mode: false

# disable-image-generation supports: false (default), true, "chat", or "passthrough".
''',
    '''# "auto" behavior (cloak only non-Claude-Code clients).
disable-claude-cloak-mode: false

# Controls whether non-Claude model IDs are disguised in Anthropic-compatible /v1/models responses.
# - "auto" (default): disguise IDs only for identified Claude Desktop clients.
# - "always": disguise IDs for every Anthropic-compatible model-list request (upstream legacy behavior).
# - "never": always return the original model IDs.
claude-model-id-cloak-mode: "auto"

# disable-image-generation supports: false (default), true, "chat", or "passthrough".
''',
)

config_diff = ROOT / 'internal/watcher/diff/config_diff.go'
replace_once(
    config_diff,
    '''\tif oldCfg.DisableClaudeCloakMode != newCfg.DisableClaudeCloakMode {
\t\tchanges = append(changes, fmt.Sprintf("disable-claude-cloak-mode: %t -> %t", oldCfg.DisableClaudeCloakMode, newCfg.DisableClaudeCloakMode))
\t}
\tif oldCfg.DisableImageGeneration != newCfg.DisableImageGeneration {
''',
    '''\tif oldCfg.DisableClaudeCloakMode != newCfg.DisableClaudeCloakMode {
\t\tchanges = append(changes, fmt.Sprintf("disable-claude-cloak-mode: %t -> %t", oldCfg.DisableClaudeCloakMode, newCfg.DisableClaudeCloakMode))
\t}
\tif strings.TrimSpace(oldCfg.ClaudeModelIDCloakMode) != strings.TrimSpace(newCfg.ClaudeModelIDCloakMode) {
\t\tchanges = append(changes, fmt.Sprintf("claude-model-id-cloak-mode: %s -> %s", strings.TrimSpace(oldCfg.ClaudeModelIDCloakMode), strings.TrimSpace(newCfg.ClaudeModelIDCloakMode)))
\t}
\tif oldCfg.DisableImageGeneration != newCfg.DisableImageGeneration {
''',
)

insert_before(
    config_go,
    '// NormalizeCommentIndentation removes indentation from standalone YAML comment lines to keep them left aligned.\n',
    '// SaveConfigPreserveCommentsUpdateNestedBoolScalar updates a nested bool scalar while preserving comments and positions.\nfunc SaveConfigPreserveCommentsUpdateNestedBoolScalar(configFile string, path []string, value bool) error {\n\tdata, err := os.ReadFile(configFile)\n\tif err != nil {\n\t\treturn err\n\t}\n\tvar root yaml.Node\n\tif err = yaml.Unmarshal(data, &root); err != nil {\n\t\treturn err\n\t}\n\tif root.Kind != yaml.DocumentNode || len(root.Content) == 0 {\n\t\treturn fmt.Errorf("invalid yaml document structure")\n\t}\n\tnode := root.Content[0]\n\tfor i, key := range path {\n\t\tif i == len(path)-1 {\n\t\t\tv := getOrCreateMapValue(node, key)\n\t\t\tv.Kind = yaml.ScalarNode\n\t\t\tv.Tag = "!!bool"\n\t\t\tif value {\n\t\t\t\tv.Value = "true"\n\t\t\t} else {\n\t\t\t\tv.Value = "false"\n\t\t\t}\n\t\t} else {\n\t\t\tnext := getOrCreateMapValue(node, key)\n\t\t\tif next.Kind != yaml.MappingNode {\n\t\t\t\tnext.Kind = yaml.MappingNode\n\t\t\t\tnext.Tag = "!!map"\n\t\t\t}\n\t\t\tnode = next\n\t\t}\n\t}\n\tf, err := os.Create(configFile)\n\tif err != nil {\n\t\treturn err\n\t}\n\tdefer func() { _ = f.Close() }()\n\tvar buf bytes.Buffer\n\tenc := yaml.NewEncoder(&buf)\n\tenc.SetIndent(2)\n\tif err = enc.Encode(&root); err != nil {\n\t\t_ = enc.Close()\n\t\treturn err\n\t}\n\tif err = enc.Close(); err != nil {\n\t\treturn err\n\t}\n\tdata = NormalizeCommentIndentation(buf.Bytes())\n\t_, err = f.Write(data)\n\treturn err\n}\n\n',
    'func SaveConfigPreserveCommentsUpdateNestedBoolScalar',
)
insert_before(
    config_go,
    '// NormalizeCommentIndentation removes indentation from standalone YAML comment lines to keep them left aligned.\n',
    '// PluginAutoInstallProxyURL returns the proxy URL used by plugin store auto-install requests.\nfunc (cfg *Config) PluginAutoInstallProxyURL() string {\n\tif cfg == nil {\n\t\treturn ""\n\t}\n\treturn cfg.ProxyURL\n}\n\n// PluginAutoInstallEnabled reports whether dynamic plugins are enabled.\nfunc (cfg *Config) PluginAutoInstallEnabled() bool {\n\treturn cfg != nil && cfg.Plugins.Enabled\n}\n\n// PluginAutoInstallDir returns the normalized plugin discovery directory.\nfunc (cfg *Config) PluginAutoInstallDir() string {\n\tif cfg == nil {\n\t\treturn ""\n\t}\n\treturn cfg.Plugins.Dir\n}\n\n// PluginAutoInstallStoreSources returns configured third-party plugin registry URLs.\nfunc (cfg *Config) PluginAutoInstallStoreSources() []string {\n\tif cfg == nil || len(cfg.Plugins.StoreSources) == 0 {\n\t\treturn nil\n\t}\n\treturn append([]string(nil), cfg.Plugins.StoreSources...)\n}\n\n// PluginAutoInstallEnabledIDs returns configured plugin IDs that should be present at startup.\nfunc (cfg *Config) PluginAutoInstallEnabledIDs() []string {\n\tif cfg == nil || len(cfg.Plugins.Configs) == 0 {\n\t\treturn nil\n\t}\n\tids := make([]string, 0, len(cfg.Plugins.Configs))\n\tfor id, item := range cfg.Plugins.Configs {\n\t\tif item.Enabled == nil || !*item.Enabled {\n\t\t\tcontinue\n\t\t}\n\t\tids = append(ids, id)\n\t}\n\treturn ids\n}\n\n',
    'func (cfg *Config) PluginAutoInstallProxyURL',
)

updater = ROOT / 'internal/managementasset/updater.go'
replace_once(
    updater,
    'defaultManagementReleaseURL  = "https://api.github.com/repos/router-for-me/Cli-Proxy-API-Management-Center/releases/latest"',
    f'defaultManagementReleaseURL  = "{PRO_PANEL_RELEASE_API}"',
)
add_go_import(updater, '"net/http"\n', '\t"net/url"\n')
replace_once(updater, '\tgitURL := strings.ToLower(strings.TrimSpace(os.Getenv("GITSTORE_GIT_URL")))\n', '')
replace_once(updater, 'tok != "" && strings.Contains(gitURL, "github.com")', 'tok != "" && isGitHubReleaseURL(releaseURL)')
insert_before(
    updater,
    'func fetchLatestAsset(ctx context.Context, client *http.Client, releaseURL string) (*releaseAsset, string, error) {\n',
    '''func isGitHubReleaseURL(releaseURL string) bool {
\tparsed, err := url.Parse(strings.TrimSpace(releaseURL))
\tif err != nil || parsed.Host == "" {
\t\treturn false
\t}
\treturn strings.Contains(strings.ToLower(parsed.Host), "github.com")
}

''',
    'func isGitHubReleaseURL(releaseURL string) bool',
)

server_main = ROOT / 'cmd/server/main.go'
add_go_import(server_main, '"' + import_path('internal/pluginhost') + '"\n', '\t"' + import_path('internal/pluginstore') + '"\n')
replace_once(
    server_main,
    '''\tconfigaccess.Register(&cfg.SDKConfig)
\tpluginHost.ApplyConfig(context.Background(), cfg)
''',
    '''\tconfigaccess.Register(&cfg.SDKConfig)
\tpluginstore.EnsureConfiguredPluginsInstalled(context.Background(), cfg)
\tpluginHost.ApplyConfig(context.Background(), cfg)
''',
)

queue_go_source('internal/pluginstore/autoinstall.go')

queue_go_source('internal/pluginstore/autoinstall_test.go')

replace_once(
    ROOT / 'internal/pluginhost/auth_provider.go',
    '''\treq.RawJSON = bytes.Clone(req.RawJSON)
\tresp, errParse := provider.ParseAuth(ctx, req)
''',
    '''\treq.RawJSON = normalizePluginStorageJSON(req.Provider, bytes.Clone(req.RawJSON))
\tresp, errParse := provider.ParseAuth(ctx, req)
''',
)

replace_once(
    ROOT / 'internal/pluginhost/auth_provider.go',
    '''\tif provider != "" {
\t\tmetadata["type"] = provider
\t}
\tattributes := cloneStringMap(data.Attributes)
''',
    '''\tif provider != "" {
\t\tmetadata["type"] = provider
\t}
\tdisabled := data.Disabled || pluginAuthDisabledFromMetadata(metadata)
\tmetadata["disabled"] = disabled
\tattributes := cloneStringMap(data.Attributes)
''',
)

replace_once(
    ROOT / 'internal/pluginhost/auth_provider.go',
    '''\tstatus := coreauth.StatusActive
\tif data.Disabled {
\t\tstatus = coreauth.StatusDisabled
\t}
''',
    '''\tstatus := coreauth.StatusActive
\tif disabled {
\t\tstatus = coreauth.StatusDisabled
\t}
''',
)

replace_once(
    ROOT / 'internal/pluginhost/auth_provider.go',
    '''\t\tDisabled:         data.Disabled,
''',
    '''\t\tDisabled:         disabled,
''',
)

replace_once(
    ROOT / 'internal/pluginhost/adapters.go',
    '''func storageJSONFromAuth(auth *coreauth.Auth) []byte {
\tif auth == nil {
\t\treturn nil
\t}
\tif rawProvider, okRaw := auth.Storage.(interface{ RawJSON() []byte }); okRaw {
\t\treturn bytes.Clone(rawProvider.RawJSON())
\t}
\tif len(auth.Metadata) == 0 {
\t\treturn nil
\t}
\tdata, errMarshal := json.Marshal(auth.Metadata)
\tif errMarshal != nil {
\t\treturn nil
\t}
\treturn data
}
''',
    '''func storageJSONFromAuth(auth *coreauth.Auth) []byte {
\tif auth == nil {
\t\treturn nil
\t}
\tif rawProvider, okRaw := auth.Storage.(interface{ RawJSON() []byte }); okRaw {
\t\treturn normalizePluginStorageJSON(auth.Provider, bytes.Clone(rawProvider.RawJSON()))
\t}
\tif len(auth.Metadata) == 0 {
\t\treturn nil
\t}
\tdata, errMarshal := json.Marshal(auth.Metadata)
\tif errMarshal != nil {
\t\treturn nil
\t}
\treturn normalizePluginStorageJSON(auth.Provider, data)
}
''',
)

queue_go_source('internal/pluginhost/gemini_cli_storage_compat.go')

queue_go_source('internal/pluginhost/gemini_cli_storage_compat_test.go')

server = ROOT / 'internal/api/server.go'
auth_files = ROOT / 'internal/api/handlers/management/auth_files.go'
api_tools = ROOT / 'internal/api/handlers/management/api_tools.go'
management_scheduler = ROOT / 'internal/api/handlers/management/account_inspection_scheduler.go'
management_scheduler_test = ROOT / 'internal/api/handlers/management/account_inspection_scheduler_test.go'
routing_policy = ROOT / 'internal/api/handlers/management/routing_policy.go'
routing_policy_test = ROOT / 'internal/api/handlers/management/routing_policy_test.go'
scheduler_source = Path(__file__).resolve().parent / 'account_inspection_scheduler.go'
write(management_scheduler, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(scheduler_source)))
scheduler_test_source = Path(__file__).resolve().parent / 'account_inspection_scheduler_test.go'
if scheduler_test_source.is_file():
    write(management_scheduler_test, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(scheduler_test_source)))
write(routing_policy, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(Path(__file__).resolve().parent / 'routing_policy.go')))
write(routing_policy_test, re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(Path(__file__).resolve().parent / 'routing_policy_test.go')))

replace_once(
    server,
    '''\tif isClaude {
\t\tout := formatHomeClaudeModels(entries)
''',
    '''\tif isClaude {
\t\tmode := ""
\t\tif s != nil && s.cfg != nil {
\t\t\tmode = s.cfg.ClaudeModelIDCloakMode
\t\t}
\t\tvar headers http.Header
\t\tif c != nil && c.Request != nil {
\t\t\theaders = c.Request.Header
\t\t}
\t\tout := formatHomeClaudeModels(entries, util.ShouldCloakClaudeModelIDs(mode, headers))
''',
)
replace_once(
    server,
    '''func formatHomeClaudeModels(entries []homeModelEntry) []map[string]any {
\tout := make([]map[string]any, 0, len(entries))
\tfor _, entry := range entries {
\t\tout = append(out, formatHomeClaudeModel(entry))
''',
    '''func formatHomeClaudeModels(entries []homeModelEntry, cloakModelIDs bool) []map[string]any {
\tout := make([]map[string]any, 0, len(entries))
\tfor _, entry := range entries {
\t\tout = append(out, formatHomeClaudeModel(entry, cloakModelIDs))
''',
)
replace_once(
    server,
    '''func formatHomeClaudeModel(entry homeModelEntry) map[string]any {
\tdisplayName := entry.displayName
''',
    '''func formatHomeClaudeModel(entry homeModelEntry, cloakModelID bool) map[string]any {
\tdisplayName := entry.displayName
''',
)
replace_once(
    server,
    '''\tmodel := map[string]any{
\t\t"id":               util.EnsureClaudeModelIDPrefix(entry.id),
''',
    '''\tmodelID := entry.id
\tif cloakModelID {
\t\tmodelID = util.EnsureClaudeModelIDPrefix(modelID)
\t}
\tmodel := map[string]any{
\t\t"id":               modelID,
''',
)

server_test = ROOT / 'internal/api/server_test.go'
replace_once(
    server_test,
    '''\t\tvar claudeModel map[string]any
\t\tvar rewrittenModel map[string]any
\t\tfor _, m := range resp.Data {
\t\t\tid, _ := m["id"].(string)
\t\t\tswitch id {
\t\t\tcase "claude-sonnet-4-6":
\t\t\t\tclaudeModel = m
\t\t\tcase "claude-fable-5-dd-o4-tpg":
\t\t\t\trewrittenModel = m
\t\t\tcase "gpt-4o", "claude-gpt-4o":
\t\t\t\tt.Fatalf("expected non-claude model id to be rewritten as claude-fable-5-dd-<reversed>, got %q", id)
\t\t\t}
\t\t}
\t\tif claudeModel == nil {
\t\t\tt.Fatalf("expected claude-sonnet-4-6 in response, got %s", rr.Body.String())
\t\t}
\t\tif rewrittenModel == nil {
\t\t\tt.Fatalf("expected claude-fable-5-dd-o4-tpg in response, got %s", rr.Body.String())
\t\t}
''',
    '''\t\tvar claudeModel map[string]any
\t\tvar rawModel map[string]any
\t\tfor _, m := range resp.Data {
\t\t\tid, _ := m["id"].(string)
\t\t\tswitch id {
\t\t\tcase "claude-sonnet-4-6":
\t\t\t\tclaudeModel = m
\t\t\tcase "gpt-4o":
\t\t\t\trawModel = m
\t\t\tcase "claude-gpt-4o", "claude-fable-5-dd-o4-tpg":
\t\t\t\tt.Fatalf("did not expect generic Anthropic client model id to be cloaked, got %q", id)
\t\t\t}
\t\t}
\t\tif claudeModel == nil {
\t\t\tt.Fatalf("expected claude-sonnet-4-6 in response, got %s", rr.Body.String())
\t\t}
\t\tif rawModel == nil {
\t\t\tt.Fatalf("expected raw gpt-4o in response, got %s", rr.Body.String())
\t\t}
''',
)
replace_once(
    server_test,
    '''\t\tmaxCompletionTokens: 64000,
\t})
''',
    '''\t\tmaxCompletionTokens: 64000,
\t}, true)
''',
)
replace_once(
    server_test,
    'withDefaults := formatHomeClaudeModel(homeModelEntry{id: "claude-no-limits"})\n',
    'withDefaults := formatHomeClaudeModel(homeModelEntry{id: "claude-no-limits"}, true)\n',
)
replace_once(
    server_test,
    'prefixed := formatHomeClaudeModel(homeModelEntry{id: "gpt-4o", displayName: "GPT-4o"})\n',
    'prefixed := formatHomeClaudeModel(homeModelEntry{id: "gpt-4o", displayName: "GPT-4o"}, true)\n',
)
replace_once(
    server_test,
    '''\tif got := prefixed["display_name"]; got != "GPT-4o" {
\t\tt.Fatalf("display_name = %v, want GPT-4o", got)
\t}
''',
    '''\tif got := prefixed["display_name"]; got != "GPT-4o" {
\t\tt.Fatalf("display_name = %v, want GPT-4o", got)
\t}
\traw := formatHomeClaudeModel(homeModelEntry{id: "gpt-4o", displayName: "GPT-4o"}, false)
\tif got := raw["id"]; got != "gpt-4o" {
\t\tt.Fatalf("raw id = %v, want gpt-4o", got)
\t}
''',
)
replace_once(
    server_test,
    '''\tout := formatHomeClaudeModels([]homeModelEntry{
\t\t{id: "claude-z", displayName: "Zebra"},
\t\t{id: "gpt-4o", displayName: "Alpha"},
\t\t{id: "claude-b", displayName: "Beta"},
\t})
''',
    '''\tout := formatHomeClaudeModels([]homeModelEntry{
\t\t{id: "claude-z", displayName: "Zebra"},
\t\t{id: "gpt-4o", displayName: "Alpha"},
\t\t{id: "claude-b", displayName: "Beta"},
\t}, true)
''',
)

replace_once(
    auth_files,
    '''\tmetadata["disabled"] = disabled
\traw, errMarshal := json.Marshal(metadata)
''',
    '''\tmetadata["disabled"] = disabled
\tdelete(metadata, routingProtectionMetadataKey)
\traw, errMarshal := json.Marshal(metadata)
''',
)
replace_once(
    auth_files,
    '''\tif auth.Metadata == nil {
\t\tauth.Metadata = make(map[string]any)
\t}
\tauth.Metadata["disabled"] = disabled
}
''',
    '''\tif auth.Metadata == nil {
\t\tauth.Metadata = make(map[string]any)
\t}
\tauth.Metadata["disabled"] = disabled
\tclearRoutingProtectionOwnership(auth)
}
''',
)
replace_once(
    auth_files,
    '''func syncAuthFileDisabledState(auth *coreauth.Auth) {
\tif auth == nil {
\t\treturn
\t}
\tdisabled, ok := authFileBoolValue(auth.Metadata["disabled"])
''',
    '''func syncAuthFileDisabledState(auth *coreauth.Auth) {
\tif auth == nil {
\t\treturn
\t}
\tdisabled, ok := authFileBoolValue(auth.Metadata["disabled"])
\tclearRoutingProtectionOwnership(auth)
''',
)

replace_once(
    api_tools,
    '''	Data            string            `json:"data"`
}
''',
    '''	Data            string            `json:"data"`
	UseExecutorSnake *bool             `json:"use_executor"`
	UseExecutorCamel *bool             `json:"useExecutor"`
	UseExecutorPascal *bool            `json:"UseExecutor"`
}
''',
)
insert_before(
    api_tools,
    'func firstNonEmptyString(values ...*string) string {\n',
    '''func firstNonNilBool(values ...*bool) bool {
\tfor _, v := range values {
\t\tif v != nil {
\t\t\treturn *v
\t\t}
\t}
\treturn false
}

''',
    'func firstNonNilBool(values ...*bool) bool',
)
replace_once(
    api_tools,
    '''\thttpClient := &http.Client{
\t\tTimeout: defaultAPICallTimeout,
\t}
\thttpClient.Transport = h.apiCallTransport(auth)

\tresp, errDo := httpClient.Do(req)
''',
    '''\tuseExecutor := firstNonNilBool(body.UseExecutorSnake, body.UseExecutorCamel, body.UseExecutorPascal)
\tvar resp *http.Response
\tvar errDo error
\tif useExecutor {
\t\tif auth == nil {
\t\t\tc.JSON(http.StatusBadRequest, gin.H{"error": "auth not found"})
\t\t\treturn
\t\t}
\t\tif h == nil || h.authManager == nil {
\t\t\tc.JSON(http.StatusServiceUnavailable, gin.H{"error": "core auth manager unavailable"})
\t\t\treturn
\t\t}
\t\tresp, errDo = h.authManager.HttpRequest(c.Request.Context(), auth, req)
\t} else {
\t\thttpClient := &http.Client{
\t\t\tTimeout: defaultAPICallTimeout,
\t\t}
\t\thttpClient.Transport = h.apiCallTransport(auth)
\t\tresp, errDo = httpClient.Do(req)
\t}
''',
)
replace_once(
    auth_files,
    '''		"unavailable":    auth.Unavailable,
		"runtime_only":   runtimeOnly,
''',
    '''		"unavailable":    auth.Unavailable,
		"last_error":     authFileLastError(auth),
		"runtime_only":   runtimeOnly,
''',
)
insert_before(
    auth_files,
    'func authAttribute(auth *coreauth.Auth, key string) string {\n',
    '''func authFileLastError(auth *coreauth.Auth) *coreauth.Error {
	if auth == nil {
		return nil
	}
	if auth.LastError != nil {
		return auth.LastError
	}
	if auth.Metadata == nil {
		return nil
	}
	raw, ok := auth.Metadata["last_error"].(map[string]any)
	if !ok {
		return nil
	}
	lastError := &coreauth.Error{
		Code:       metadataString(raw["code"]),
		Message:    metadataString(raw["message"]),
		Retryable:  metadataBool(raw["retryable"]),
		HTTPStatus: metadataInt(raw["http_status"]),
	}
	if lastError.Code == "" && lastError.Message == "" && lastError.HTTPStatus == 0 {
		return nil
	}
	return lastError
}

func metadataString(value any) string {
	if value == nil {
		return ""
	}
	return strings.TrimSpace(fmt.Sprint(value))
}

func metadataBool(value any) bool {
	switch typed := value.(type) {
	case bool:
		return typed
	case string:
		return strings.EqualFold(strings.TrimSpace(typed), "true")
	default:
		return false
	}
}

func metadataInt(value any) int {
	switch typed := value.(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	case json.Number:
		parsed, _ := typed.Int64()
		return int(parsed)
	case string:
		parsed, _ := strconv.Atoi(strings.TrimSpace(typed))
		return parsed
	default:
		return 0
	}
}

''',
    'func authFileLastError',
)
replace_once(
    auth_files,
    '''				typeValue := gjson.GetBytes(data, "type").String()
				emailValue := gjson.GetBytes(data, "email").String()
				fileData["type"] = typeValue
				fileData["email"] = emailValue
''',
    '''				typeValue := gjson.GetBytes(data, "type").String()
				emailValue := gjson.GetBytes(data, "email").String()
				fileData["type"] = typeValue
				fileData["email"] = emailValue
				if lastErrorRaw := gjson.GetBytes(data, "last_error"); lastErrorRaw.IsObject() {
					var lastError map[string]any
					if errUnmarshal := json.Unmarshal([]byte(lastErrorRaw.Raw), &lastError); errUnmarshal == nil && len(lastError) > 0 {
						fileData["last_error"] = lastError
					}
				}
				if strings.EqualFold(strings.TrimSpace(typeValue), "codex") {
					if claims := extractCodexIDTokenClaimsFromRaw(gjson.GetBytes(data, "id_token").String()); claims != nil {
						fileData["id_token"] = claims
					}
				}
''',
)
insert_before(
    auth_files,
    'func extractCodexIDTokenClaims(auth *coreauth.Auth) gin.H {\n',
    '''func extractCodexIDTokenClaimsFromRaw(idTokenRaw string) gin.H {
	idToken := strings.TrimSpace(idTokenRaw)
	if idToken == "" {
		return nil
	}
	claims, err := codex.ParseJWTToken(idToken)
	if err != nil || claims == nil {
		return nil
	}
	return codexIDTokenClaimsEntry(claims)
}

''',
    'func extractCodexIDTokenClaimsFromRaw',
)
replace_go_function(
    auth_files,
    'func extractCodexIDTokenClaims(auth *coreauth.Auth) gin.H',
    '''func extractCodexIDTokenClaims(auth *coreauth.Auth) gin.H {
	if auth == nil || auth.Metadata == nil {
		return nil
	}
	if !strings.EqualFold(strings.TrimSpace(auth.Provider), "codex") {
		return nil
	}
	idTokenRaw, ok := auth.Metadata["id_token"].(string)
	if !ok {
		return nil
	}
	return extractCodexIDTokenClaimsFromRaw(idTokenRaw)
}

func codexIDTokenClaimsEntry(claims *codex.JWTClaims) gin.H {
	if claims == nil {
		return nil
	}
	result := gin.H{}
	if v := strings.TrimSpace(claims.CodexAuthInfo.ChatgptAccountID); v != "" {
		result["chatgpt_account_id"] = v
	}
	if v := strings.TrimSpace(claims.CodexAuthInfo.ChatgptPlanType); v != "" {
		result["plan_type"] = v
	}
	if v := claims.CodexAuthInfo.ChatgptSubscriptionActiveStart; v != nil {
		result["chatgpt_subscription_active_start"] = v
	}
	if v := claims.CodexAuthInfo.ChatgptSubscriptionActiveUntil; v != nil {
		result["chatgpt_subscription_active_until"] = v
	}

	if len(result) == 0 {
		return nil
	}
	return result
}
''',
    'func codexIDTokenClaimsEntry',
)

patch_dir = Path(__file__).resolve().parent
embeddedusage_source = patch_dir.parent / 'embeddedusage'
embeddedusage_target = ROOT / 'internal/embeddedusage'
if embeddedusage_source.is_dir():
    queue_tree(embeddedusage_source, embeddedusage_target)
elif not embeddedusage_target.is_dir():
    raise SystemExit(f'embeddedusage source not found: {embeddedusage_source}')
ensure_go_require(ROOT / 'go.mod', 'modernc.org/sqlite', 'v1.51.0')
auth_runtime_state = ROOT / 'sdk/cliproxy/auth/auth_runtime_state.go'
write(
    auth_runtime_state,
    re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(patch_dir / 'auth_runtime_state.go')),
)
write(
    ROOT / 'sdk/cliproxy/auth/auth_runtime_state_test.go',
    re.sub(r'github\.com/router-for-me/CLIProxyAPI/v\d+', MODULE_PATH, read_text(patch_dir / 'auth_runtime_state_test.go')),
)

redisqueue_plugin = ROOT / 'internal/redisqueue/plugin.go'
replace_once(
    redisqueue_plugin,
    f'\tinternallogging "{import_path("internal/logging")}"\n',
    f'\t"{import_path("internal/requestmeta")}"\n',
    f'"{import_path("internal/requestmeta")}"',
)
redisqueue_plugin_text = read(redisqueue_plugin)
if 'internallogging.' in redisqueue_plugin_text:
    write(redisqueue_plugin, redisqueue_plugin_text.replace('internallogging.', 'requestmeta.'))
elif 'requestmeta.' not in redisqueue_plugin_text:
    raise SystemExit(f'request metadata calls not found in {redisqueue_plugin}')
replace_once(
    redisqueue_plugin,
    '\trequestID := strings.TrimSpace(requestmeta.GetRequestID(ctx))\n\treasoningEffort :=',
    '\trequestID := strings.TrimSpace(requestmeta.GetRequestID(ctx))\n\tstream := coreusage.StreamFromContext(ctx)\n\treasoningEffort :=',
    'stream := coreusage.StreamFromContext(ctx)',
)
replace_once(
    redisqueue_plugin,
    '\t\tRequestID:           requestID,\n\t\tReasoningEffort:',
    '\t\tRequestID:           requestID,\n\t\tStream:              stream,\n\t\tReasoningEffort:',
    'Stream:              stream',
)
redisqueue_plugin_text = read(redisqueue_plugin)
stream_field = '\tStream bool `json:"stream"`\n'
if '`json:"stream"`' not in redisqueue_plugin_text:
    request_id_field = re.compile(r'(?m)^\tRequestID[ \t]+string[ \t]+`json:"request_id"`\n')
    matches = request_id_field.findall(redisqueue_plugin_text)
    if len(matches) != 1:
        raise SystemExit(
            f'expected one request ID field in {redisqueue_plugin}, found {len(matches)}'
        )
    write(
        redisqueue_plugin,
        request_id_field.sub(lambda match: match.group(0) + stream_field, redisqueue_plugin_text, count=1),
    )
redisqueue_plugin_test = ROOT / 'internal/redisqueue/plugin_test.go'
if redisqueue_plugin_test.exists():
    text = read_text(redisqueue_plugin_test)
    text = text.replace(
        f'internallogging "{import_path("internal/logging")}"',
        f'"{import_path("internal/requestmeta")}"',
    )
    text = text.replace('internallogging.', 'requestmeta.')
    write(redisqueue_plugin_test, text)

queue_go_source('internal/requestmeta/requestid.go')

queue_go_source('internal/requestmeta/response.go')

logging_request_id = ROOT / 'internal/logging/requestid.go'
queue_go_source('internal/logging/requestid.go')

logging_request_meta = ROOT / 'internal/logging/requestmeta.go'
queue_go_source('internal/logging/requestmeta.go')

add_go_import(server, '"' + import_path('internal/config') + '"\n', '\t"' + import_path('internal/embeddedusage') + '"\n')

replace_go_call_block(
    server,
    '\ts.engine.GET("/", func(c *gin.Context) {',
    '''\ts.engine.GET("/", func(c *gin.Context) {
\t\tc.Redirect(http.StatusTemporaryRedirect, "/management.html")
\t})
''',
    'c.Redirect(http.StatusTemporaryRedirect, "/management.html")',
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
    '''\t\tmgmt.POST("/api-call", s.mgmt.APICall)\n\t\ts.mgmt.RegisterPluginQuotaRoutes(mgmt)\n\t\ts.mgmt.RegisterAccountInspectionRoutes(mgmt)\n\t\ts.mgmt.RegisterRoutingPolicyRoutes(mgmt)\n''',
)

handler = ROOT / 'internal/api/handlers/management/handler.go'
add_go_import(handler, '"net/http"\n', '\t"net/url"\n')
replace_once(
    handler,
    '''\tpluginReleaseCacheMu    sync.Mutex
\tpluginReleaseCache      map[string]pluginReleaseCacheEntry
}
''',
    '''\tpluginReleaseCacheMu    sync.Mutex
\tpluginReleaseCache      map[string]pluginReleaseCacheEntry
\tlifecycleContext        context.Context
\tlifecycleCancel         context.CancelFunc
\tlifecycleWG             sync.WaitGroup
\tshutdownOnce            sync.Once
}
''',
    'lifecycleContext        context.Context',
)
replace_once(
    handler,
    '''\th := &Handler{
''',
    '''\tlifecycleContext, lifecycleCancel := context.WithCancel(context.Background())

\th := &Handler{
''',
    'lifecycleContext, lifecycleCancel := context.WithCancel(context.Background())',
)
replace_once(
    handler,
    '''\t\tallowRemoteOverride: envSecret != "",
\t\tenvSecret:           envSecret,
\t}
''',
    '''\t\tallowRemoteOverride: envSecret != "",
\t\tenvSecret:           envSecret,
\t\tlifecycleContext:    lifecycleContext,
\t\tlifecycleCancel:     lifecycleCancel,
\t}
''',
    'lifecycleContext:    lifecycleContext',
)
replace_go_function(
    handler,
    'func (h *Handler) startAttemptCleanup() {',
    '''func (h *Handler) startAttemptCleanup() {
\tif h == nil || h.lifecycleContext == nil {
\t\treturn
\t}
\th.lifecycleWG.Add(1)
\tgo func() {
\t\tdefer h.lifecycleWG.Done()
\t\tticker := time.NewTicker(attemptCleanupInterval)
\t\tdefer ticker.Stop()
\t\tfor {
\t\t\tselect {
\t\t\tcase <-h.lifecycleContext.Done():
\t\t\t\treturn
\t\t\tcase <-ticker.C:
\t\t\t\th.purgeStaleAttempts()
\t\t\t}
\t\t}
\t}()
}
''',
    'case <-h.lifecycleContext.Done():',
)
replace_once(
    handler,
    '''\t\tif provided == "" {
\t\t\tprovided = c.GetHeader("X-Management-Key")
\t\t}
''',
    '''\t\tif provided == "" {
\t\t\tprovided = c.GetHeader("X-Management-Key")
\t\t}
\t\tif provided == "" {
\t\t\tprovided = managementKeyFromWebSocketProtocol(c)
\t\t}
''',
)
insert_before(
    handler,
    '''func (h *Handler) Middleware() gin.HandlerFunc {
''',
    '''func managementKeyFromWebSocketProtocol(c *gin.Context) string {
\tif !strings.EqualFold(c.GetHeader("Upgrade"), "websocket") {
\t\treturn ""
\t}
\tfor _, protocol := range strings.Split(c.GetHeader("Sec-WebSocket-Protocol"), ",") {
\t\tprotocol = strings.TrimSpace(protocol)
\t\tif !strings.HasPrefix(protocol, "cpa-management.") {
\t\t\tcontinue
\t\t}
\t\tdecoded, err := url.QueryUnescape(strings.TrimPrefix(protocol, "cpa-management."))
\t\tif err != nil {
\t\t\treturn ""
\t\t}
\t\treturn decoded
\t}
\treturn ""
}

''',
    'func managementKeyFromWebSocketProtocol(c *gin.Context) string',
)
replace_once(
    handler,
    '''\th.startAttemptCleanup()
\treturn h
''',
    '''\th.startAccountInspectionScheduler()
\th.startAttemptCleanup()
\treturn h
''',
)
replace_once(
    server,
    '''\tlog.Debug("Stopping API server...")

\tif s.keepAliveEnabled {
''',
    '''\tlog.Debug("Stopping API server...")
\tdefer func() {
\t\tif s.mgmt != nil {
\t\t\ts.mgmt.Shutdown()
\t\t}
\t}()

\tif s.keepAliveEnabled {
''',
    's.mgmt.Shutdown()',
)

run = ROOT / 'internal/cmd/run.go'
add_go_import(run, '"' + import_path('internal/config') + '"\n', '\t"' + import_path('internal/embeddedusage') + '"\n')
insert_before(
    run,
    '// StartService builds and runs the proxy service using the exported SDK.\n',
    'func applyProRequiredStartupConfig(cfg *config.Config, configPath string) {\n\tif cfg == nil {\n\t\treturn\n\t}\n\tshouldPersistUsageStatistics := !cfg.UsageStatisticsEnabled\n\tshouldPersistPanelRepository := cfg.RemoteManagement.PanelGitHubRepository != config.DefaultPanelGitHubRepository\n\tcfg.UsageStatisticsEnabled = true\n\tcfg.RemoteManagement.PanelGitHubRepository = config.DefaultPanelGitHubRepository\n\tif configPath == "" {\n\t\treturn\n\t}\n\tif shouldPersistUsageStatistics {\n\t\tif err := config.SaveConfigPreserveCommentsUpdateNestedBoolScalar(configPath, []string{"usage-statistics-enabled"}, true); err != nil {\n\t\t\tlog.Warnf("failed to persist usage statistics config: %v", err)\n\t\t}\n\t}\n\tif shouldPersistPanelRepository {\n\t\tif err := config.SaveConfigPreserveCommentsUpdateNestedScalar(configPath, []string{"remote-management", "panel-github-repository"}, config.DefaultPanelGitHubRepository); err != nil {\n\t\t\tlog.Warnf("failed to persist panel repository config: %v", err)\n\t\t}\n\t}\n}\n\n',
    'func applyProRequiredStartupConfig',
)
insert_before_nth(
    run,
    '''\tservice, err := builder.Build()
''',
    '''\tusageService, err := embeddedusage.Start(ctx)
\tif err != nil {
\t\tlog.Errorf("failed to start embedded usage service: %v", err)
\t\tclose(doneCh)
\t\treturn cancelFn, doneCh
\t}
\tembeddedusage.SetDefaultService(usageService)
\tapplyProRequiredStartupConfig(cfg, configPath)

''',
    2,
    'embeddedusage.Start(ctx)',
)
insert_before_nth(
    run,
    '''\tservice, err := builder.Build()
''',
    '''\tusageService, err := embeddedusage.Start(runCtx)
\tif err != nil {
\t\tlog.Errorf("failed to start embedded usage service: %v", err)
\t\treturn
\t}
\tembeddedusage.SetDefaultService(usageService)
\tapplyProRequiredStartupConfig(cfg, configPath)

''',
    1,
    'embeddedusage.Start(runCtx)',
)

queue_go_source('sdk/cliproxy/auth/inspection_refresh.go')

auth_types = ROOT / 'sdk/cliproxy/auth/types.go'
replace_once(
    auth_types,
    '''\tSuccess int64 `json:"-"`
\tFailed  int64 `json:"-"`
''',
    '''\tSelected int64 `json:"-"`
\tSuccess  int64 `json:"-"`
\tFailed   int64 `json:"-"`
''',
    'Selected int64',
)

auth_conductor = ROOT / 'sdk/cliproxy/auth/conductor.go'
replace_once(
    auth_conductor,
    '''\tauth.EnsureIndex()
\tauthClone := auth.Clone()
\tm.mu.Lock()
\tm.auths[auth.ID] = authClone
''',
    '''\tauth.EnsureIndex()
\trestoreAuthRuntimeStats(auth)
\tcleanupLegacyQuotaCacheOnRegister(auth)
\tauthClone := auth.Clone()
\tm.mu.Lock()
\tm.auths[auth.ID] = authClone
''',
    'cleanupLegacyQuotaCacheOnRegister(auth)',
)
replace_once(
    auth_conductor,
    '''\tauth.Success = existing.Success
\tauth.Failed = existing.Failed
\tauth.recentRequests = existing.recentRequests
''',
    '''\tauth.Selected = existing.Selected
\tauth.Success = existing.Success
\tauth.Failed = existing.Failed
\tauth.recentRequests = existing.recentRequests
''',
    'auth.Selected = existing.Selected',
)
replace_once(
    auth_conductor,
    '''\tm.mu.Unlock()
\tif m.scheduler != nil && authSnapshot != nil {
\t\tm.scheduler.upsertAuth(authSnapshot)
\t}
''',
    '''\tm.mu.Unlock()
\tqueueAuthRuntimeStats(authSnapshot)
\tif m.scheduler != nil && authSnapshot != nil {
\t\tm.scheduler.upsertAuth(authSnapshot)
\t}
''',
    'queueAuthRuntimeStats(authSnapshot)',
)
replace_once(
    auth_conductor,
    '''\tif m.HomeEnabled() {
\t\tauth, exec, _, err := m.pickNextViaHome(ctx, model, opts, tried)
\t\treturn auth, exec, err
\t}

\tif m.hasPluginScheduler() || !m.useSchedulerFastPath() {
\t\treturn m.pickNextLegacy(ctx, provider, model, opts, tried)
\t}
''',
    '''\tif m.HomeEnabled() {
\t\tauth, exec, _, err := m.pickNextViaHome(ctx, model, opts, tried)
\t\tif err == nil && auth != nil {
\t\t\tm.recordAuthSelected(auth.ID)
\t\t}
\t\treturn auth, exec, err
\t}

\tif m.hasPluginScheduler() || !m.useSchedulerFastPath() {
\t\tauth, exec, err := m.pickNextLegacy(ctx, provider, model, opts, tried)
\t\tif err == nil && auth != nil {
\t\t\tm.recordAuthSelected(auth.ID)
\t\t}
\t\treturn auth, exec, err
\t}
''',
    'm.recordAuthSelected(auth.ID)',
)
replace_once(
    auth_conductor,
    '''\t\treturn authCopy, executor, nil
\t}
}

func (m *Manager) pickNextMixedLegacy''',
    '''\t\tm.recordAuthSelected(authCopy.ID)
\t\treturn authCopy, executor, nil
\t}
}

func (m *Manager) pickNextMixedLegacy''',
    'm.recordAuthSelected(authCopy.ID)\n\t\treturn authCopy, executor, nil',
)
replace_once(
    auth_conductor,
    '''\t\t\tif m.routeAwareSelectionRequired(candidate, model) {
\t\t\t\tm.mu.RUnlock()
\t\t\t\treturn m.pickNextLegacy(ctx, provider, model, opts, tried)
\t\t\t}
''',
    '''\t\t\tif m.routeAwareSelectionRequired(candidate, model) {
\t\t\t\tm.mu.RUnlock()
\t\t\t\tauth, exec, err := m.pickNextLegacy(ctx, provider, model, opts, tried)
\t\t\t\tif err == nil && auth != nil {
\t\t\t\t\tm.recordAuthSelected(auth.ID)
\t\t\t\t}
\t\t\t\treturn auth, exec, err
\t\t\t}
''',
    'm.mu.RUnlock()\n\t\t\t\tauth, exec, err := m.pickNextLegacy',
)
replace_once(
    auth_conductor,
    '''\tif m.HomeEnabled() {
\t\treturn m.pickNextViaHome(ctx, model, opts, tried)
\t}

\tif m.hasPluginScheduler() || !m.useSchedulerFastPath() {
\t\treturn m.pickNextMixedLegacy(ctx, providers, model, opts, tried)
\t}
''',
    '''\tif m.HomeEnabled() {
\t\tauth, exec, providerKey, err := m.pickNextViaHome(ctx, model, opts, tried)
\t\tif err == nil && auth != nil {
\t\t\tm.recordAuthSelected(auth.ID)
\t\t}
\t\treturn auth, exec, providerKey, err
\t}

\tif m.hasPluginScheduler() || !m.useSchedulerFastPath() {
\t\tauth, exec, providerKey, err := m.pickNextMixedLegacy(ctx, providers, model, opts, tried)
\t\tif err == nil && auth != nil {
\t\t\tm.recordAuthSelected(auth.ID)
\t\t}
\t\treturn auth, exec, providerKey, err
\t}
''',
    'auth, exec, providerKey, err := m.pickNextViaHome',
)
replace_once(
    auth_conductor,
    '''\t\treturn authCopy, executor, providerKey, nil
\t}
}

type homeErrorEnvelope''',
    '''\t\tm.recordAuthSelected(authCopy.ID)
\t\treturn authCopy, executor, providerKey, nil
\t}
}

type homeErrorEnvelope''',
    'm.recordAuthSelected(authCopy.ID)\n\t\treturn authCopy, executor, providerKey, nil',
)
replace_once(
    auth_conductor,
    '''\t\t\tif m.routeAwareSelectionRequired(candidate, model) {
\t\t\t\tm.mu.RUnlock()
\t\t\t\treturn m.pickNextMixedLegacy(ctx, providers, model, opts, tried)
\t\t\t}
''',
    '''\t\t\tif m.routeAwareSelectionRequired(candidate, model) {
\t\t\t\tm.mu.RUnlock()
\t\t\t\tauth, exec, providerKey, err := m.pickNextMixedLegacy(ctx, providers, model, opts, tried)
\t\t\t\tif err == nil && auth != nil {
\t\t\t\t\tm.recordAuthSelected(auth.ID)
\t\t\t\t}
\t\t\t\treturn auth, exec, providerKey, err
\t\t\t}
''',
    'm.mu.RUnlock()\n\t\t\t\tauth, exec, providerKey, err := m.pickNextMixedLegacy',
)

auth_files_handler = ROOT / 'internal/api/handlers/management/auth_files.go'
add_go_import(
    auth_files_handler,
    '"' + import_path('internal/config') + '"\n',
    '\t"' + import_path('internal/embeddedusage') + '"\n',
)
replace_once(
    auth_files_handler,
    '''\tentry["success"] = auth.Success
\tentry["failed"] = auth.Failed
''',
    '''\tentry["selected"] = auth.Selected
\tentry["success"] = auth.Success
\tentry["failed"] = auth.Failed
''',
    'entry["selected"] = auth.Selected',
)
replace_once(
    auth_files_handler,
    '''\t\t\t\tdeleted++
\t\t\t\th.removeAuth(ctx, full)
''',
    '''\t\t\t\tdeleted++
\t\t\t\th.removeAuth(ctx, full)
\t\t\t\t_ = embeddedusage.DeleteAuthRuntimeState(ctx, "", "", name)
''',
    'DeleteAuthRuntimeState(ctx, "", "", name)',
)
replace_once(
    auth_files_handler,
    '''\ttargetPath := filepath.Join(h.cfg.AuthDir, filepath.Base(name))
\ttargetID := ""
\tif targetAuth := h.findAuthForDelete(name); targetAuth != nil {
''',
    '''\ttargetPath := filepath.Join(h.cfg.AuthDir, filepath.Base(name))
\ttargetID := ""
\ttargetIndex := ""
\tif targetAuth := h.findAuthForDelete(name); targetAuth != nil {
''',
    'targetIndex := ""',
)
replace_once(
    auth_files_handler,
    '''\t\ttargetID = strings.TrimSpace(targetAuth.ID)
\t\tif path := strings.TrimSpace(authAttribute(targetAuth, "path")); path != "" {
''',
    '''\t\ttargetID = strings.TrimSpace(targetAuth.ID)
\t\ttargetIndex = strings.TrimSpace(targetAuth.Index)
\t\tif path := strings.TrimSpace(authAttribute(targetAuth, "path")); path != "" {
''',
    'targetIndex = strings.TrimSpace(targetAuth.Index)',
)
replace_once(
    auth_files_handler,
    '''\th.removeAuthsForPath(ctx, targetPath, targetID)
\treturn filepath.Base(name), http.StatusOK, nil
''',
    '''\th.removeAuthsForPath(ctx, targetPath, targetID)
\t_ = embeddedusage.DeleteAuthRuntimeState(ctx, targetID, targetIndex, filepath.Base(name))
\treturn filepath.Base(name), http.StatusOK, nil
''',
    'DeleteAuthRuntimeState(ctx, targetID, targetIndex',
)

auth_scheduler = ROOT / 'sdk/cliproxy/auth/scheduler.go'
add_go_import(auth_scheduler, '"context"\n', '\t"fmt"\n')
add_go_import(auth_scheduler, '"time"\n', '\t"' + import_path('internal/embeddedusage') + '"\n')
replace_once(
    auth_scheduler,
    '''\tmixedCursors  map[string]int
}''',
    '''\tmixedCursors     map[string]int
\tmixedRestored    map[string]bool
\tpersistedCursors map[string]string
}''',
    'persistedCursors map[string]string',
)
replace_once(
    auth_scheduler,
    '''\tmodelShards map[string]*modelScheduler
}''',
    '''\tmodelShards      map[string]*modelScheduler
\tpersistedCursors map[string]string
}''',
    'modelShards      map[string]*modelScheduler',
)
replace_once(
    auth_scheduler,
    '''type modelScheduler struct {
\tmodelKey        string''',
    '''type modelScheduler struct {
\tproviderKey     string
\tmodelKey        string
\tpersistedCursors map[string]string''',
    'providerKey     string\n\tmodelKey',
)
replace_once(
    auth_scheduler,
    '''type readyView struct {
\tflat   []*scheduledAuth
\tcursor int
}''',
    '''type readyView struct {
\tflat       []*scheduledAuth
\tcursor     int
\tcursorKey  string
\tlastAuthID string
\tpersisted  map[string]string
}''',
    'cursorKey  string',
)
replace_once(
    auth_scheduler,
    '''func newAuthScheduler(selector Selector) *authScheduler {
\treturn &authScheduler{
\t\tstrategy:      selectorStrategy(selector),
\t\tproviders:     make(map[string]*providerScheduler),
\t\tauthProviders: make(map[string]string),
\t\tmixedCursors:  make(map[string]int),
\t}
}''',
    '''func newAuthScheduler(selector Selector) *authScheduler {
\tpersistedCursors := make(map[string]string)
\tif states, err := embeddedusage.ListRoutingCursorStates(context.Background()); err == nil {
\t\tfor _, state := range states {
\t\t\tpersistedCursors[state.CursorKey] = state.LastAuthID
\t\t}
\t}
\treturn &authScheduler{
\t\tstrategy:         selectorStrategy(selector),
\t\tproviders:        make(map[string]*providerScheduler),
\t\tauthProviders:    make(map[string]string),
\t\tmixedCursors:     make(map[string]int),
\t\tmixedRestored:    make(map[string]bool),
\t\tpersistedCursors: persistedCursors,
\t}
}''',
    'persistedCursors := make(map[string]string)',
)
insert_before(
    auth_scheduler,
    '// selectorStrategy maps a selector implementation to the scheduler semantics it should emulate.\n',
    '''func (s *authScheduler) applyImportedRuntimeState(states []embeddedusage.RoutingCursorState, auths []*Auth) {
\tif s == nil {
\t\treturn
\t}
\tpersistedCursors := make(map[string]string, len(states))
\tfor _, state := range states {
\t\tif state.CursorKey != "" && state.LastAuthID != "" {
\t\t\tpersistedCursors[state.CursorKey] = state.LastAuthID
\t\t}
\t}
\ts.mu.Lock()
\tdefer s.mu.Unlock()
\ts.persistedCursors = persistedCursors
\ts.providers = make(map[string]*providerScheduler)
\ts.authProviders = make(map[string]string)
\ts.mixedCursors = make(map[string]int)
\ts.mixedRestored = make(map[string]bool)
\tnow := time.Now()
\tfor _, auth := range auths {
\t\ts.upsertAuthLocked(auth, now)
\t}
}

''',
    'func (s *authScheduler) applyImportedRuntimeState',
)
replace_once(
    auth_scheduler,
    '''\ts.mixedCursors = make(map[string]int)
\tnow := time.Now()''',
    '''\ts.mixedCursors = make(map[string]int)
\ts.mixedRestored = make(map[string]bool)
\tnow := time.Now()''',
    's.mixedRestored = make(map[string]bool)',
)
replace_once(
    auth_scheduler,
    '''\ts.strategy = selectorStrategy(selector)
\tclear(s.mixedCursors)
''',
    '''\ts.strategy = selectorStrategy(selector)
\tclear(s.mixedCursors)
\tclear(s.mixedRestored)
''',
    'clear(s.mixedRestored)',
)
replace_once(
    auth_scheduler,
    '''\t\tproviderState = &providerScheduler{
\t\t\tproviderKey: providerKey,
\t\t\tauths:       make(map[string]*scheduledAuthMeta),
\t\t\tmodelShards: make(map[string]*modelScheduler),
\t\t}''',
    '''\t\tproviderState = &providerScheduler{
\t\t\tproviderKey:      providerKey,
\t\t\tauths:            make(map[string]*scheduledAuthMeta),
\t\t\tmodelShards:      make(map[string]*modelScheduler),
\t\t\tpersistedCursors: s.persistedCursors,
\t\t}''',
    'persistedCursors: s.persistedCursors',
)
replace_once(
    auth_scheduler,
    '''\tshard := &modelScheduler{
\t\tmodelKey:        modelKey,
\t\tentries:         make(map[string]*scheduledAuth),
\t\treadyByPriority: make(map[int]*readyBucket),
\t}''',
    '''\tshard := &modelScheduler{
\t\tproviderKey:      p.providerKey,
\t\tmodelKey:         modelKey,
\t\tpersistedCursors: p.persistedCursors,
\t\tentries:          make(map[string]*scheduledAuth),
\t\treadyByPriority:  make(map[int]*readyBucket),
\t}''',
    'persistedCursors: p.persistedCursors',
)
replace_once(
    auth_scheduler,
    '''\t\tbucket := buildReadyBucket(entries)
''',
    '''\t\tcursorPrefix := fmt.Sprintf("single|%s|%s|%d", m.providerKey, m.modelKey, priority)
\t\tbucket := buildReadyBucket(entries, cursorPrefix, m.persistedCursors)
''',
    'cursorPrefix := fmt.Sprintf("single|%s|%s|%d"',
)
replace_once(
    auth_scheduler,
    '''func buildReadyBucket(entries []*scheduledAuth) *readyBucket {
\tbucket := &readyBucket{}
\tbucket.all = buildReadyView(entries)''',
    '''func buildReadyBucket(entries []*scheduledAuth, cursorPrefix string, persisted map[string]string) *readyBucket {
\tbucket := &readyBucket{}
\tbucket.all = buildReadyView(entries, cursorPrefix+"|all", persisted)''',
    'func buildReadyBucket(entries []*scheduledAuth, cursorPrefix string',
)
replace_once(
    auth_scheduler,
    '''\tbucket.ws = buildReadyView(wsEntries)
''',
    '''\tbucket.ws = buildReadyView(wsEntries, cursorPrefix+"|ws", persisted)
''',
    'buildReadyView(wsEntries, cursorPrefix+"|ws"',
)
replace_once(
    auth_scheduler,
    '''func buildReadyView(entries []*scheduledAuth) readyView {
\treturn readyView{flat: append([]*scheduledAuth(nil), entries...)}
}''',
    '''func buildReadyView(entries []*scheduledAuth, cursorKey string, persisted map[string]string) readyView {
\tview := readyView{flat: append([]*scheduledAuth(nil), entries...), cursorKey: cursorKey, persisted: persisted}
\tview.restoreAfterAuthID(persisted[cursorKey])
\treturn view
}

func (v *readyView) restoreAfterAuthID(lastAuthID string) {
\tlastAuthID = strings.TrimSpace(lastAuthID)
\tif lastAuthID == "" || len(v.flat) == 0 {
\t\treturn
\t}
\tv.lastAuthID = lastAuthID
\tfor index, entry := range v.flat {
\t\tif entry == nil || entry.auth == nil {
\t\t\tcontinue
\t\t}
\t\tif entry.auth.ID == lastAuthID {
\t\t\tv.cursor = index + 1
\t\t\treturn
\t\t}
\t\tif entry.auth.ID > lastAuthID {
\t\t\tv.cursor = index
\t\t\treturn
\t\t}
\t}
\tv.cursor = 0
}''',
    'func (v *readyView) restoreAfterAuthID',
)
replace_once(
    auth_scheduler,
    '''\t\tv.cursor = index + 1
\t\treturn entry
''',
    '''\t\tv.cursor = index + 1
\t\tv.lastAuthID = entry.auth.ID
\t\tif v.persisted != nil {
\t\t\tv.persisted[v.cursorKey] = entry.auth.ID
\t\t}
\t\tembeddedusage.QueueRoutingCursorState(embeddedusage.RoutingCursorState{
\t\t\tCursorKey: v.cursorKey, LastAuthID: entry.auth.ID, UpdatedAtMS: time.Now().UnixMilli(),
\t\t})
\t\treturn entry
''',
    'v.persisted[v.cursorKey] = entry.auth.ID',
)
replace_once(
    auth_scheduler,
    '''\tstartSlot := s.mixedCursors[cursorKey] % totalWeight
''',
    '''\tstartSlot := s.mixedCursors[cursorKey] % totalWeight
\tpersistedCursorKey := fmt.Sprintf("mixed|%s|%d", cursorKey, bestPriority)
\tif !s.mixedRestored[cursorKey] {
\t\ts.mixedRestored[cursorKey] = true
\t\tif lastAuthID := s.persistedCursors[persistedCursorKey]; lastAuthID != "" {
\t\t\tfor providerIndex, shard := range candidateShards {
\t\t\t\tif shard != nil {
\t\t\t\t\tif _, ok := shard.entries[lastAuthID]; ok && weights[providerIndex] > 0 {
\t\t\t\t\t\tstartSlot = segmentStarts[providerIndex]
\t\t\t\t\t\tbreak
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t}
''',
    'persistedCursorKey := fmt.Sprintf("mixed|%s|%d"',
)
replace_once(
    auth_scheduler,
    '''\t\ts.mixedCursors[cursorKey] = slot + 1
\t\treturn picked, providerKey, nil
''',
    '''\t\ts.mixedCursors[cursorKey] = slot + 1
\t\ts.persistedCursors[persistedCursorKey] = picked.ID
\t\tembeddedusage.QueueRoutingCursorState(embeddedusage.RoutingCursorState{
\t\t\tCursorKey: persistedCursorKey, LastAuthID: picked.ID, UpdatedAtMS: time.Now().UnixMilli(),
\t\t})
\t\treturn picked, providerKey, nil
''',
    's.persistedCursors[persistedCursorKey] = picked.ID',
)

flush_writes()
subprocess.run([
    'gofmt',
    '-w',
    'cmd/server/main.go',
    'internal/api/server.go',
    'internal/api/server_test.go',
    'internal/api/handlers/management/account_inspection_scheduler.go',
    'internal/api/handlers/management/account_inspection_scheduler_test.go',
    'internal/api/handlers/management/auth_files.go',
    'internal/api/handlers/management/handler.go',
    'internal/api/handlers/management/plugin_quota.go',
    'internal/api/handlers/management/plugin_quota_test.go',
    'internal/config/sdk_config.go',
    'internal/logging/requestid.go',
    'internal/logging/requestmeta.go',
    'internal/util/claude_model.go',
    'internal/util/claude_model_test.go',
    'internal/watcher/diff/config_diff.go',
    'internal/api/handlers/management/routing_policy.go',
    'internal/api/handlers/management/routing_policy_test.go',
    'internal/config/routing_protection_config.go',
    'internal/pluginhost/gemini_cli_storage_compat.go',
    'internal/pluginhost/gemini_cli_storage_compat_test.go',
    'internal/pluginhost/gemini_cli_quota_legacy.go',
    'internal/pluginhost/gemini_cli_quota_legacy_test.go',
    'internal/pluginhost/quota_provider.go',
    'internal/pluginhost/quota_provider_test.go',
    'internal/pluginhost/rpc_client.go',
    'internal/pluginhost/rpc_schema.go',
    'internal/pluginhost/snapshot.go',
    'internal/pluginstore/autoinstall.go',
    'internal/pluginstore/autoinstall_test.go',
    'internal/redisqueue/plugin.go',
    'internal/redisqueue/plugin_test.go',
    'internal/requestmeta/requestid.go',
    'internal/requestmeta/response.go',
    'sdk/api/handlers/claude/code_handlers.go',
    'sdk/api/handlers/claude/code_handlers_model_test.go',
    'sdk/cliproxy/auth/auth_runtime_state.go',
    'sdk/cliproxy/auth/auth_runtime_state_test.go',
    'sdk/cliproxy/auth/conductor.go',
    'sdk/cliproxy/auth/scheduler.go',
    'sdk/cliproxy/auth/types.go',
    'sdk/cliproxy/usage/manager.go',
    'sdk/cliproxy/usage/manager_test.go',
    'sdk/pluginabi/types.go',
    'sdk/pluginapi/types.go',
], cwd=ROOT, check=True)
subprocess.run(['go', 'mod', 'tidy'], cwd=ROOT, check=True)
