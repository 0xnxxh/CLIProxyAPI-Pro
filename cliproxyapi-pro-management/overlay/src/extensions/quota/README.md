# Quota persistence

Quota runtime state is persisted by the backend embedded-usage SQLite store. The browser Zustand store is only an in-memory view of that state.

## Flow

1. Provider quota fetchers write successful states to the Zustand quota maps with `cachedAt`.
2. `persistenceMiddleware.ts` observes those maps and writes them through `sqliteQuotaCache.ts`.
3. The backend assigns a monotonically increasing record revision and advances the quota-cache generation on set, delete, clear, or import.
4. The middleware compares generations in `ensureFresh()` and reloads all entries when the backend state changes.
5. Failed writes stay queued and retry with bounded exponential backoff.

Account inspection writes directly to the same SQLite cache. Authentication JSON files are not used as a quota-cache store.

The cache is included in the usage JSONL export/import format. Imported older revisions do not overwrite newer records.
