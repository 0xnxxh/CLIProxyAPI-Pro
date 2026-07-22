import { describe, expect, test } from 'bun:test';
import { normalizePersistedQuotaState } from '../src/extensions/quota/normalizedQuotaSnapshot';

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
});
