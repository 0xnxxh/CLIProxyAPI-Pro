package auth

import "testing"

func runtimeStateTestEntries(ids ...string) []*scheduledAuth {
	entries := make([]*scheduledAuth, 0, len(ids))
	for _, id := range ids {
		auth := &Auth{ID: id}
		entries = append(entries, &scheduledAuth{auth: auth})
	}
	return entries
}

func TestReadyViewRestoresSuccessorOfLastSelectedAuth(t *testing.T) {
	const key = "single|codex|gpt-5|0|all"
	persisted := map[string]string{key: "auth-b"}
	view := buildReadyView(runtimeStateTestEntries("auth-a", "auth-b", "auth-c"), key, persisted)
	picked := view.pickRoundRobin(nil)
	if picked == nil || picked.auth == nil || picked.auth.ID != "auth-c" {
		t.Fatalf("restored pick = %#v, want auth-c", picked)
	}
}

func TestReadyViewRestoresNextSortedAuthWhenSavedAuthIsMissing(t *testing.T) {
	const key = "single|codex|gpt-5|0|all"
	persisted := map[string]string{key: "auth-b"}
	view := buildReadyView(runtimeStateTestEntries("auth-a", "auth-c", "auth-d"), key, persisted)
	picked := view.pickRoundRobin(nil)
	if picked == nil || picked.auth == nil || picked.auth.ID != "auth-c" {
		t.Fatalf("restored missing-auth pick = %#v, want auth-c", picked)
	}
}
