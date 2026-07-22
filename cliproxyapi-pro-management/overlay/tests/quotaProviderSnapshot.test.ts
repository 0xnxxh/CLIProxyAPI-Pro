import { describe, expect, test } from 'bun:test';
import {
  normalizePersistedQuotaState,
  selectPreferredQuotaCacheEntries,
} from '../src/extensions/quota/normalizedQuotaSnapshot';
import type { QuotaCacheEntry } from '../src/extensions/quota/sqliteQuotaCache';

const cacheEntry = (
  id: string,
  data: unknown,
  observedAt: number,
  revision = 1
): QuotaCacheEntry => ({
  id,
  provider: 'gemini-cli',
  fileName: 'gemini.json',
  data,
  cachedAt: observedAt,
  accessedAt: observedAt,
  observedAt,
  storedAt: observedAt,
  version: 1,
  revision,
});

describe('QuotaProvider snapshot persistence', () => {
  test('hydrates a normalized Gemini snapshot without converting it back on write', () => {
    const normalized = normalizePersistedQuotaState(
      'gemini-cli',
      {
        schema_version: 1,
        observed_at_ms: 123,
        items: [
          {
            id: 'gemini-pro-series',
            label: 'Gemini Pro Series',
            remaining_fraction: 0.75,
            remaining_amount: 42,
            reset_at: '2026-07-23T00:00:00Z',
            model_ids: ['gemini-3.1-pro-preview'],
            metadata: { token_type: 'requests' },
          },
        ],
        plan: { id: 'g1-pro-tier', label: 'Google AI Pro', credit_balance: 10 },
        metadata: { project_id: 'project-a' },
      },
      999
    ) as Record<string, unknown>;

    expect(normalized.status).toBe('success');
    expect(normalized.cachedAt).toBe(123);
    expect(normalized.quotaProviderSnapshot).toBe(true);
    expect(normalized.projectId).toBe('project-a');
    expect(normalized.tierId).toBe('g1-pro-tier');
    expect((normalized.buckets as Array<Record<string, unknown>>)[0]).toMatchObject({
      id: 'gemini-pro-series',
      remainingFraction: 0.75,
      tokenType: 'requests',
    });
  });

  test('leaves legacy provider states untouched', () => {
    const legacy = { status: 'success', buckets: [] };
    expect(normalizePersistedQuotaState('gemini-cli', legacy, 1)).toBe(legacy);
  });

  test('prefers the canonical Gemini snapshot over a duplicate legacy UI cache entry', () => {
    const canonical = cacheEntry(
      'quota-provider:gemini-cli:auth-1',
      {
        schema_version: 1,
        observed_at_ms: 200,
        items: [{ id: 'new', label: 'New quota', remaining_fraction: 0.8 }],
        plan: { id: 'g1-pro-tier', label: 'Google AI Pro' },
      },
      200
    );
    const legacy = cacheEntry(
      'gemini-cli:gemini.json',
      {
        status: 'success',
        buckets: [{ id: 'old', label: 'Old quota', remainingFraction: 0.1 }],
        tierId: 'free-tier',
      },
      100
    );

    for (const entries of [
      [canonical, legacy],
      [legacy, canonical],
    ]) {
      const selected = selectPreferredQuotaCacheEntries('gemini-cli', entries).get('gemini.json');
      expect(selected?.id).toBe(canonical.id);
      const hydrated = normalizePersistedQuotaState(
        'gemini-cli',
        selected?.data,
        selected?.cachedAt ?? 0
      ) as Record<string, unknown>;
      expect(hydrated.tierId).toBe('g1-pro-tier');
      expect((hydrated.buckets as Array<Record<string, unknown>>)[0]?.id).toBe('new');
    }
  });

  test('uses freshness metadata when duplicate entries have the same representation', () => {
    const older = cacheEntry('older', { status: 'success', buckets: [] }, 100, 5);
    const newer = cacheEntry('newer', { status: 'success', buckets: [] }, 200, 1);

    const selected = selectPreferredQuotaCacheEntries('gemini-cli', [older, newer]);
    expect(selected.get('gemini.json')?.id).toBe('newer');
  });
});
