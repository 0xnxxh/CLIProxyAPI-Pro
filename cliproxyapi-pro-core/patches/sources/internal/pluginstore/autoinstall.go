package pluginstore

import (
	"context"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"

	"github.com/router-for-me/CLIProxyAPI/v7/sdk/proxyutil"
	log "github.com/sirupsen/logrus"
	"golang.org/x/sys/cpu"
)

var autoInstallPluginIDPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)

// AutoInstallWarning describes a non-fatal plugin auto-install issue.
type AutoInstallWarning struct {
	PluginID  string
	SourceID  string
	SourceURL string
	Message   string
}

// AutoInstallReport summarizes startup plugin auto-install work.
type AutoInstallReport struct {
	Installed []InstallResult
	Warnings  []AutoInstallWarning
}

// AutoInstallConfig is the small read-only config surface needed by plugin auto-install.
type AutoInstallConfig interface {
	NormalizePluginsConfig()
	PluginAutoInstallProxyURL() string
	PluginAutoInstallEnabled() bool
	PluginAutoInstallDir() string
	PluginAutoInstallStoreSources() []string
	PluginAutoInstallEnabledIDs() []string
}

type autoInstallOptions struct {
	HTTPClient HTTPDoer
	GOOS       string
	GOARCH     string
	Install    func(context.Context, Client, Plugin, InstallOptions) (InstallResult, error)
}

type autoInstallSourcePlugin struct {
	source Source
	plugin Plugin
}

// EnsureConfiguredPluginsInstalled downloads missing enabled plugins before the plugin host scans local binaries.
func EnsureConfiguredPluginsInstalled(ctx context.Context, cfg AutoInstallConfig) AutoInstallReport {
	report := ensureConfiguredPluginsInstalled(ctx, cfg, autoInstallOptions{})
	for _, warning := range report.Warnings {
		fields := log.Fields{}
		if warning.PluginID != "" {
			fields["plugin_id"] = warning.PluginID
		}
		if warning.SourceID != "" {
			fields["source_id"] = warning.SourceID
		}
		if warning.SourceURL != "" {
			fields["source_url"] = warning.SourceURL
		}
		log.WithFields(fields).Warnf("pluginstore: auto install skipped: %s", warning.Message)
	}
	for _, installed := range report.Installed {
		log.WithFields(log.Fields{
			"plugin_id": installed.ID,
			"version":   installed.Version,
			"path":      installed.Path,
		}).Info("pluginstore: plugin auto installed")
	}
	return report
}

func ensureConfiguredPluginsInstalled(ctx context.Context, cfg AutoInstallConfig, options autoInstallOptions) AutoInstallReport {
	var report AutoInstallReport
	if ctx == nil {
		ctx = context.Background()
	}
	if cfg == nil {
		return report
	}
	cfg.NormalizePluginsConfig()
	if !cfg.PluginAutoInstallEnabled() {
		return report
	}

	enabledIDs := enabledConfiguredPluginIDs(cfg)
	if len(enabledIDs) == 0 {
		return report
	}

	installedIDs, errDiscover := installedPluginIDs(cfg.PluginAutoInstallDir())
	if errDiscover != nil {
		report.Warnings = append(report.Warnings, AutoInstallWarning{Message: "discover installed plugins: " + errDiscover.Error()})
		return report
	}

	missingIDs := make([]string, 0, len(enabledIDs))
	for _, id := range enabledIDs {
		if _, installed := installedIDs[id]; installed {
			continue
		}
		missingIDs = append(missingIDs, id)
	}
	if len(missingIDs) == 0 {
		return report
	}
	wanted := make(map[string]struct{}, len(missingIDs))
	for _, id := range missingIDs {
		wanted[id] = struct{}{}
	}

	sources, errSources := NormalizeSources(cfg.PluginAutoInstallStoreSources())
	if errSources != nil {
		report.Warnings = append(report.Warnings, AutoInstallWarning{Message: "normalize plugin store sources: " + errSources.Error()})
		return report
	}

	httpClient := options.HTTPClient
	if httpClient == nil {
		httpClient = autoInstallHTTPClient(cfg.PluginAutoInstallProxyURL())
	}

	matches := make(map[string][]autoInstallSourcePlugin, len(missingIDs))
	for _, source := range sources {
		client := Client{HTTPClient: httpClient, RegistryURL: source.URL}
		registry, errRegistry := client.FetchRegistry(ctx)
		if errRegistry != nil {
			report.Warnings = append(report.Warnings, AutoInstallWarning{
				SourceID:  source.ID,
				SourceURL: source.URL,
				Message:   "fetch plugin registry: " + errRegistry.Error(),
			})
			continue
		}
		for _, plugin := range registry.Plugins {
			if _, ok := wanted[plugin.ID]; !ok {
				continue
			}
			matches[plugin.ID] = append(matches[plugin.ID], autoInstallSourcePlugin{source: source, plugin: plugin})
		}
	}

	installer := options.Install
	if installer == nil {
		installer = func(ctx context.Context, client Client, plugin Plugin, installOptions InstallOptions) (InstallResult, error) {
			return client.Install(ctx, plugin, installOptions)
		}
	}
	goos := strings.TrimSpace(options.GOOS)
	if goos == "" {
		goos = runtime.GOOS
	}
	goarch := strings.TrimSpace(options.GOARCH)
	if goarch == "" {
		goarch = runtime.GOARCH
	}

	for _, id := range missingIDs {
		candidates := matches[id]
		switch len(candidates) {
		case 0:
			report.Warnings = append(report.Warnings, AutoInstallWarning{PluginID: id, Message: "plugin not found in configured registries"})
			continue
		case 1:
			candidate := candidates[0]
			result, errInstall := installer(ctx, Client{HTTPClient: httpClient, RegistryURL: candidate.source.URL}, candidate.plugin, InstallOptions{
				PluginsDir: cfg.PluginAutoInstallDir(),
				GOOS:       goos,
				GOARCH:     goarch,
			})
			if errInstall != nil {
				report.Warnings = append(report.Warnings, AutoInstallWarning{
					PluginID:  id,
					SourceID:  candidate.source.ID,
					SourceURL: candidate.source.URL,
					Message:   "install plugin: " + errInstall.Error(),
				})
				continue
			}
			report.Installed = append(report.Installed, result)
		default:
			report.Warnings = append(report.Warnings, AutoInstallWarning{PluginID: id, Message: "plugin id appears in multiple registries; install source is ambiguous"})
		}
	}

	return report
}

func enabledConfiguredPluginIDs(cfg AutoInstallConfig) []string {
	configuredIDs := cfg.PluginAutoInstallEnabledIDs()
	ids := make([]string, 0, len(configuredIDs))
	for _, id := range configuredIDs {
		id = strings.TrimSpace(id)
		if id == "" {
			continue
		}
		if !autoInstallValidatePluginID(id) {
			continue
		}
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func installedPluginIDs(pluginsDir string) (map[string]struct{}, error) {
	files, err := autoInstallDiscoverPluginFiles(pluginsDir)
	if err != nil {
		return nil, err
	}
	out := make(map[string]struct{}, len(files))
	for _, file := range files {
		out[file.ID] = struct{}{}
	}
	return out, nil
}

type autoInstallPluginFile struct {
	ID   string
	Path string
}

func autoInstallValidatePluginID(id string) bool {
	return autoInstallPluginIDPattern.MatchString(id)
}

func autoInstallPluginIDFromPath(path string) string {
	base := filepath.Base(path)
	lowerBase := strings.ToLower(base)
	for _, extension := range []string{".so", ".dylib", ".dll"} {
		if strings.HasSuffix(lowerBase, extension) {
			return base[:len(base)-len(extension)]
		}
	}
	return base
}

func autoInstallPluginExtension(goos string) string {
	switch goos {
	case "darwin":
		return ".dylib"
	case "windows":
		return ".dll"
	default:
		return ".so"
	}
}

func autoInstallDiscoverPluginFiles(root string) ([]autoInstallPluginFile, error) {
	root = strings.TrimSpace(root)
	if root == "" {
		root = "plugins"
	}

	candidates := autoInstallCandidateDirs(root, runtime.GOOS, runtime.GOARCH, autoInstallCPUVariant())
	extension := autoInstallPluginExtension(runtime.GOOS)
	selected := make([]autoInstallPluginFile, 0)
	seen := make(map[string]struct{})
	for _, dir := range candidates {
		entries, errReadDir := os.ReadDir(dir)
		if errReadDir != nil {
			if os.IsNotExist(errReadDir) {
				continue
			}
			return nil, errReadDir
		}
		files := make([]string, 0, len(entries))
		for _, entry := range entries {
			if entry == nil || !entry.Type().IsRegular() {
				continue
			}
			if strings.HasSuffix(strings.ToLower(entry.Name()), extension) {
				files = append(files, filepath.Join(dir, entry.Name()))
			}
		}
		sort.Strings(files)
		for _, path := range files {
			id := autoInstallPluginIDFromPath(path)
			if !autoInstallValidatePluginID(id) {
				continue
			}
			if _, exists := seen[id]; exists {
				continue
			}
			seen[id] = struct{}{}
			selected = append(selected, autoInstallPluginFile{ID: id, Path: path})
		}
	}
	return selected, nil
}

func autoInstallCandidateDirs(root, goos, goarch, variant string) []string {
	dirs := make([]string, 0, 3)
	if variant != "" {
		dirs = append(dirs, filepath.Join(root, goos, goarch+"-"+variant))
	}
	dirs = append(dirs, filepath.Join(root, goos, goarch))
	dirs = append(dirs, root)
	return dirs
}

func autoInstallCPUVariant() string {
	if runtime.GOARCH != "amd64" {
		return ""
	}
	if cpu.X86.HasAVX512F && cpu.X86.HasAVX512BW && cpu.X86.HasAVX512CD && cpu.X86.HasAVX512DQ && cpu.X86.HasAVX512VL {
		return "v4"
	}
	if cpu.X86.HasAVX && cpu.X86.HasAVX2 && cpu.X86.HasBMI1 && cpu.X86.HasBMI2 && cpu.X86.HasFMA {
		return "v3"
	}
	if cpu.X86.HasSSE3 && cpu.X86.HasSSSE3 && cpu.X86.HasSSE41 && cpu.X86.HasSSE42 && cpu.X86.HasPOPCNT {
		return "v2"
	}
	return "v1"
}

func autoInstallHTTPClient(proxyURL string) HTTPDoer {
	client := &http.Client{}
	proxyURL = strings.TrimSpace(proxyURL)
	if proxyURL == "" {
		return client
	}
	transport, _, errBuild := proxyutil.BuildHTTPTransport(proxyURL)
	if errBuild != nil {
		log.WithError(errBuild).Warn("pluginstore: invalid proxy URL for auto install")
		return client
	}
	if transport != nil {
		client.Transport = transport
	}
	return client
}
