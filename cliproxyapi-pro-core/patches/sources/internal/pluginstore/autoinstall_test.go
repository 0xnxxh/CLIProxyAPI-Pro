package pluginstore

import (
	"context"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"testing"
)

type autoInstallFakeDoer map[string]string

func (d autoInstallFakeDoer) Do(req *http.Request) (*http.Response, error) {
	body, ok := d[req.URL.String()]
	if !ok {
		return &http.Response{
			StatusCode: http.StatusNotFound,
			Body:       io.NopCloser(strings.NewReader("missing")),
			Header:     make(http.Header),
		}, nil
	}
	return &http.Response{
		StatusCode: http.StatusOK,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     make(http.Header),
	}, nil
}

func enabledBoolPtr(value bool) *bool {
	return &value
}

type fakeAutoInstallPlugin struct {
	Enabled *bool
}

type fakeAutoInstallConfig struct {
	ProxyURL     string
	Enabled      bool
	Dir          string
	StoreSources []string
	Configs      map[string]fakeAutoInstallPlugin
}

func (cfg *fakeAutoInstallConfig) NormalizePluginsConfig() {
	if cfg == nil {
		return
	}
	cfg.Dir = strings.TrimSpace(cfg.Dir)
	if cfg.Dir == "" {
		cfg.Dir = "plugins"
	}
	if len(cfg.StoreSources) > 0 {
		sources := make([]string, 0, len(cfg.StoreSources))
		for _, source := range cfg.StoreSources {
			source = strings.TrimSpace(source)
			if source == "" {
				continue
			}
			sources = append(sources, source)
		}
		cfg.StoreSources = sources
	}
	if cfg.Configs == nil {
		cfg.Configs = map[string]fakeAutoInstallPlugin{}
	}
}

func (cfg *fakeAutoInstallConfig) PluginAutoInstallProxyURL() string {
	if cfg == nil {
		return ""
	}
	return cfg.ProxyURL
}

func (cfg *fakeAutoInstallConfig) PluginAutoInstallEnabled() bool {
	return cfg != nil && cfg.Enabled
}

func (cfg *fakeAutoInstallConfig) PluginAutoInstallDir() string {
	if cfg == nil {
		return ""
	}
	return cfg.Dir
}

func (cfg *fakeAutoInstallConfig) PluginAutoInstallStoreSources() []string {
	if cfg == nil || len(cfg.StoreSources) == 0 {
		return nil
	}
	return append([]string(nil), cfg.StoreSources...)
}

func (cfg *fakeAutoInstallConfig) PluginAutoInstallEnabledIDs() []string {
	if cfg == nil || len(cfg.Configs) == 0 {
		return nil
	}
	ids := make([]string, 0, len(cfg.Configs))
	for id, item := range cfg.Configs {
		if item.Enabled == nil || !*item.Enabled {
			continue
		}
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func TestEnsureConfiguredPluginsInstalledSkipsDisabledGlobal(t *testing.T) {
	cfg := &fakeAutoInstallConfig{
		Enabled: false,
		Dir:     t.TempDir(),
		Configs: map[string]fakeAutoInstallPlugin{
			"sample-provider": {Enabled: enabledBoolPtr(true)},
		},
	}
	called := false
	report := ensureConfiguredPluginsInstalled(context.Background(), cfg, autoInstallOptions{
		Install: func(context.Context, Client, Plugin, InstallOptions) (InstallResult, error) {
			called = true
			return InstallResult{}, nil
		},
	})
	if called {
		t.Fatal("installer called while plugins are globally disabled")
	}
	if len(report.Installed) != 0 || len(report.Warnings) != 0 {
		t.Fatalf("report = %#v, want empty", report)
	}
}

func TestEnsureConfiguredPluginsInstalledSkipsDisabledPlugin(t *testing.T) {
	cfg := &fakeAutoInstallConfig{
		Enabled: true,
		Dir:     t.TempDir(),
		Configs: map[string]fakeAutoInstallPlugin{
			"sample-provider": {Enabled: enabledBoolPtr(false)},
		},
	}
	called := false
	report := ensureConfiguredPluginsInstalled(context.Background(), cfg, autoInstallOptions{
		Install: func(context.Context, Client, Plugin, InstallOptions) (InstallResult, error) {
			called = true
			return InstallResult{}, nil
		},
	})
	if called {
		t.Fatal("installer called for disabled plugin")
	}
	if len(report.Installed) != 0 || len(report.Warnings) != 0 {
		t.Fatalf("report = %#v, want empty", report)
	}
}

func TestEnsureConfiguredPluginsInstalledSkipsInstalledPlugin(t *testing.T) {
	root := t.TempDir()
	targetDir := filepath.Join(root, runtime.GOOS, runtime.GOARCH)
	if err := os.MkdirAll(targetDir, 0o755); err != nil {
		t.Fatalf("MkdirAll() error = %v", err)
	}
	if err := os.WriteFile(filepath.Join(targetDir, "sample-provider"+autoInstallPluginExtension(runtime.GOOS)), []byte("plugin"), 0o755); err != nil {
		t.Fatalf("WriteFile() error = %v", err)
	}
	cfg := &fakeAutoInstallConfig{
		Enabled: true,
		Dir:     root,
		Configs: map[string]fakeAutoInstallPlugin{
			"sample-provider": {Enabled: enabledBoolPtr(true)},
		},
	}
	called := false
	report := ensureConfiguredPluginsInstalled(context.Background(), cfg, autoInstallOptions{
		Install: func(context.Context, Client, Plugin, InstallOptions) (InstallResult, error) {
			called = true
			return InstallResult{}, nil
		},
	})
	if called {
		t.Fatal("installer called for already installed plugin")
	}
	if len(report.Installed) != 0 || len(report.Warnings) != 0 {
		t.Fatalf("report = %#v, want empty", report)
	}
}

func TestEnsureConfiguredPluginsInstalledInstallsUniqueRegistryMatch(t *testing.T) {
	root := t.TempDir()
	cfg := &fakeAutoInstallConfig{
		Enabled: true,
		Dir:     root,
		Configs: map[string]fakeAutoInstallPlugin{
			"sample-provider": {Enabled: enabledBoolPtr(true)},
		},
	}
	fakeHTTP := autoInstallFakeDoer{
		DefaultRegistryURL: `{"schema_version":1,"plugins":[{"id":"sample-provider","name":"Sample","description":"Sample plugin","author":"Tester","repository":"https://github.com/example/sample-provider"}]}`,
	}
	var gotPlugin Plugin
	var gotOptions InstallOptions
	report := ensureConfiguredPluginsInstalled(context.Background(), cfg, autoInstallOptions{
		HTTPClient: fakeHTTP,
		GOOS:       "linux",
		GOARCH:     "amd64",
		Install: func(_ context.Context, _ Client, plugin Plugin, options InstallOptions) (InstallResult, error) {
			gotPlugin = plugin
			gotOptions = options
			return InstallResult{ID: plugin.ID, Version: "1.2.3", Path: filepath.Join(options.PluginsDir, options.GOOS, options.GOARCH, plugin.ID+".so")}, nil
		},
	})
	if len(report.Warnings) != 0 {
		t.Fatalf("warnings = %#v, want none", report.Warnings)
	}
	if len(report.Installed) != 1 {
		t.Fatalf("installed len = %d, want 1; report=%#v", len(report.Installed), report)
	}
	if gotPlugin.ID != "sample-provider" {
		t.Fatalf("installed plugin = %#v", gotPlugin)
	}
	if gotOptions.PluginsDir != root || gotOptions.GOOS != "linux" || gotOptions.GOARCH != "amd64" {
		t.Fatalf("install options = %#v", gotOptions)
	}
}

func TestEnsureConfiguredPluginsInstalledSkipsAmbiguousRegistryMatch(t *testing.T) {
	sourceURL := "https://plugins.example/registry.json"
	cfg := &fakeAutoInstallConfig{
		Enabled:      true,
		Dir:          t.TempDir(),
		StoreSources: []string{sourceURL},
		Configs: map[string]fakeAutoInstallPlugin{
			"sample-provider": {Enabled: enabledBoolPtr(true)},
		},
	}
	registry := `{"schema_version":1,"plugins":[{"id":"sample-provider","name":"Sample","description":"Sample plugin","author":"Tester","repository":"https://github.com/example/sample-provider"}]}`
	called := false
	report := ensureConfiguredPluginsInstalled(context.Background(), cfg, autoInstallOptions{
		HTTPClient: autoInstallFakeDoer{
			DefaultRegistryURL: registry,
			sourceURL:          registry,
		},
		Install: func(context.Context, Client, Plugin, InstallOptions) (InstallResult, error) {
			called = true
			return InstallResult{}, nil
		},
	})
	if called {
		t.Fatal("installer called for ambiguous registry match")
	}
	if len(report.Installed) != 0 {
		t.Fatalf("installed = %#v, want none", report.Installed)
	}
	if len(report.Warnings) != 1 || !strings.Contains(report.Warnings[0].Message, "multiple registries") {
		t.Fatalf("warnings = %#v, want ambiguity warning", report.Warnings)
	}
}
