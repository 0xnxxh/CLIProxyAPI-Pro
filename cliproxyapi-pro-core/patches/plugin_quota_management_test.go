package management

import "testing"

func TestQuotaFileNameFallsBackToAuthIndex(t *testing.T) {
	if got := quotaFileName("", "gemini-cli:user@example.com:project-a"); got != "gemini-cli:user@example.com:project-a" {
		t.Fatalf("quotaFileName() = %q", got)
	}
	if got := quotaFileName("gemini.json", "ignored"); got != "gemini.json" {
		t.Fatalf("quotaFileName() = %q", got)
	}
}
