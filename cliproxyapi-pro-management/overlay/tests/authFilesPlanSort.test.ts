import { describe, expect, test } from 'bun:test';
import type { AuthFileItem } from '@/types';
import {
  compareAuthFilesByPlanDescending,
  isAuthFilePlanSortProvider,
} from '@/features/authFiles/planSort';

type PlanSortQuotaStore = Parameters<typeof compareAuthFilesByPlanDescending>[2];

const file = (
  name: string,
  type: string,
  extra: Record<string, unknown> = {}
): AuthFileItem => ({ name, type, ...extra }) as unknown as AuthFileItem;

const quotaStore = (overrides: Partial<PlanSortQuotaStore> = {}): PlanSortQuotaStore =>
  ({
    antigravityQuota: {},
    claudeQuota: {},
    codexQuota: {},
    geminiCliQuota: {},
    xaiQuota: {},
    ...overrides,
  }) as PlanSortQuotaStore;

describe('auth-file plan sorting', () => {
  test('only exposes plan sorting for providers with comparable plans', () => {
    expect(isAuthFilePlanSortProvider('codex')).toBe(true);
    expect(isAuthFilePlanSortProvider('gemini-cli')).toBe(true);
    expect(isAuthFilePlanSortProvider('all')).toBe(false);
    expect(isAuthFilePlanSortProvider('kimi')).toBe(false);
  });

  test('sorts Codex plans high to low and keeps missing plans last', () => {
    const items = [
      file('unknown.json', 'codex'),
      file('free.json', 'codex', { plan_type: 'free' }),
      file('plus.json', 'codex'),
      file('pro-b.json', 'codex'),
      file('pro-a.json', 'codex'),
    ];
    const store = quotaStore({
      codexQuota: {
        'plus.json': { planType: 'plus' },
        'pro-b.json': { planType: 'pro' },
        'pro-a.json': { planType: 'pro' },
      },
    } as unknown as Partial<PlanSortQuotaStore>);

    items.sort((left, right) => compareAuthFilesByPlanDescending(left, right, store));

    expect(items.map((item) => item.name)).toEqual([
      'pro-a.json',
      'pro-b.json',
      'plus.json',
      'free.json',
      'unknown.json',
    ]);
  });

  test('uses raw Gemini tier IDs instead of translated labels', () => {
    const items = [file('standard.json', 'gemini-cli'), file('ultra.json', 'gemini-cli')];
    const store = quotaStore({
      geminiCliQuota: {
        'standard.json': { tierId: 'standard-tier', tierLabel: '标准版' },
        'ultra.json': { tierId: 'g1-ultra-tier', tierLabel: '至尊版' },
      },
    } as unknown as Partial<PlanSortQuotaStore>);

    items.sort((left, right) => compareAuthFilesByPlanDescending(left, right, store));

    expect(items.map((item) => item.name)).toEqual(['ultra.json', 'standard.json']);
  });

  test('maps xAI monthly limits to all known tiers', () => {
    const items = [
      file('free.json', 'xai'),
      file('supergrok.json', 'xai'),
      file('premium-plus.json', 'xai'),
      file('heavy.json', 'xai'),
    ];
    const store = quotaStore({
      xaiQuota: {
        'free.json': { billing: { monthlyLimitCents: null, planType: 'free' } },
        'supergrok.json': { billing: { monthlyLimitCents: 15_000 } },
        'premium-plus.json': { billing: { monthlyLimitCents: 20_000 } },
        'heavy.json': { billing: { monthlyLimitCents: 150_000 } },
      },
    } as unknown as Partial<PlanSortQuotaStore>);

    items.sort((left, right) => compareAuthFilesByPlanDescending(left, right, store));

    expect(items.map((item) => item.name)).toEqual([
      'heavy.json',
      'premium-plus.json',
      'supergrok.json',
      'free.json',
    ]);
  });
});
