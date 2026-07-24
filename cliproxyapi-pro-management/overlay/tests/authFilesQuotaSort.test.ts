import { describe, expect, test } from 'bun:test';
import type { AuthFileItem } from '@/types';
import {
  compareAuthFilesByAvailableQuotaDescending,
  isAuthFileQuotaSortProvider,
  resolveAuthFileAvailablePercent,
} from '@/features/authFiles/quotaSort';

type QuotaSortStore = Parameters<typeof compareAuthFilesByAvailableQuotaDescending>[2];

const file = (name: string, type: string): AuthFileItem =>
  ({ name, type }) as unknown as AuthFileItem;

const quotaStore = (overrides: Partial<QuotaSortStore> = {}): QuotaSortStore =>
  ({
    antigravityQuota: {},
    claudeQuota: {},
    codexQuota: {},
    geminiCliQuota: {},
    kimiQuota: {},
    xaiQuota: {},
    ...overrides,
  }) as QuotaSortStore;

describe('auth-file available-quota sorting', () => {
  test('only exposes quota sorting on concrete quota-provider tabs', () => {
    expect(isAuthFileQuotaSortProvider('antigravity')).toBe(true);
    expect(isAuthFileQuotaSortProvider('claude')).toBe(true);
    expect(isAuthFileQuotaSortProvider('codex')).toBe(true);
    expect(isAuthFileQuotaSortProvider('gemini-cli')).toBe(true);
    expect(isAuthFileQuotaSortProvider('kimi')).toBe(true);
    expect(isAuthFileQuotaSortProvider('xai')).toBe(true);
    expect(isAuthFileQuotaSortProvider('all')).toBe(false);
    expect(isAuthFileQuotaSortProvider('aistudio')).toBe(false);
  });

  test('uses the most constrained Codex window and keeps unknown quota last', () => {
    const items = [file('unknown.json', 'codex'), file('higher.json', 'codex'), file('lower.json', 'codex')];
    const store = quotaStore({
      codexQuota: {
        'higher.json': {
          status: 'success',
          cachedAt: Date.now(),
          windows: [{ usedPercent: 10 }, { usedPercent: 40 }],
        },
        'lower.json': {
          status: 'success',
          cachedAt: Date.now(),
          windows: [{ usedPercent: 20 }, { usedPercent: 70 }],
        },
      },
    } as unknown as Partial<QuotaSortStore>);

    items.sort((left, right) => compareAuthFilesByAvailableQuotaDescending(left, right, store));

    expect(resolveAuthFileAvailablePercent(items[0], store)).toBe(60);
    expect(items.map((item) => item.name)).toEqual(['higher.json', 'lower.json', 'unknown.json']);
  });

  test('normalizes Antigravity and Gemini CLI remaining fractions', () => {
    const antigravity = file('antigravity.json', 'antigravity');
    const gemini = file('gemini.json', 'gemini-cli');
    const store = quotaStore({
      antigravityQuota: {
        'antigravity.json': {
          status: 'success',
          cachedAt: Date.now(),
          groups: [
            { buckets: [{ remainingFraction: 0.8 }, { remainingFraction: 0.35 }] },
            { buckets: [{ remainingFraction: 0.6 }] },
          ],
        },
      },
      geminiCliQuota: {
        'gemini.json': {
          status: 'success',
          cachedAt: Date.now(),
          buckets: [{ remainingFraction: 0.9 }, { remainingFraction: 25 }],
        },
      },
    } as unknown as Partial<QuotaSortStore>);

    expect(resolveAuthFileAvailablePercent(antigravity, store)).toBe(35);
    expect(resolveAuthFileAvailablePercent(gemini, store)).toBe(25);
  });

  test('derives Kimi availability from used and limit values', () => {
    const kimi = file('kimi.json', 'kimi');
    const store = quotaStore({
      kimiQuota: {
        'kimi.json': {
          status: 'success',
          cachedAt: Date.now(),
          rows: [
            { used: 20, limit: 100 },
            { used: 75, limit: 100 },
          ],
        },
      },
    } as unknown as Partial<QuotaSortStore>);

    expect(resolveAuthFileAvailablePercent(kimi, store)).toBe(25);
  });

  test('follows xAI weekly, monthly, then product-usage precedence', () => {
    const weekly = file('weekly.json', 'xai');
    const monthly = file('monthly.json', 'xai');
    const product = file('product.json', 'xai');
    const store = quotaStore({
      xaiQuota: {
        'weekly.json': {
          status: 'success',
          cachedAt: Date.now(),
          billing: { usagePercent: 20, usedPercent: 90, productUsage: [] },
        },
        'monthly.json': {
          status: 'success',
          cachedAt: Date.now(),
          billing: { usagePercent: null, usedPercent: 55, productUsage: [] },
        },
        'product.json': {
          status: 'success',
          cachedAt: Date.now(),
          billing: {
            usagePercent: null,
            usedPercent: null,
            productUsage: [{ usagePercent: 10 }, { usagePercent: 65 }],
          },
        },
      },
    } as unknown as Partial<QuotaSortStore>);

    expect(resolveAuthFileAvailablePercent(weekly, store)).toBe(80);
    expect(resolveAuthFileAvailablePercent(monthly, store)).toBe(45);
    expect(resolveAuthFileAvailablePercent(product, store)).toBe(35);
  });

  test('uses rolling free-token quota only for free xAI plans', () => {
    const free = file('free.json', 'xai');
    const paid = file('paid.json', 'xai');
    const store = quotaStore({
      xaiQuota: {
        'free.json': {
          status: 'success',
          cachedAt: Date.now(),
          billing: {
            planType: 'free',
            freeQuota: { usedTokens: 25, limitTokens: 100 },
          },
        },
        'paid.json': {
          status: 'success',
          cachedAt: Date.now(),
          billing: {
            planType: 'x-premium-plus',
            freeQuota: { exhausted: true },
            usagePercent: 10,
          },
        },
      },
    } as unknown as Partial<QuotaSortStore>);

    expect(resolveAuthFileAvailablePercent(free, store)).toBe(75);
    expect(resolveAuthFileAvailablePercent(paid, store)).toBe(90);
  });

  test('ignores stale successful quota snapshots', () => {
    const stale = file('stale.json', 'codex');
    const store = quotaStore({
      codexQuota: {
        'stale.json': {
          status: 'success',
          cachedAt: Date.now() - 25 * 60 * 60 * 1000,
          windows: [{ usedPercent: 10 }],
        },
      },
    } as unknown as Partial<QuotaSortStore>);

    expect(resolveAuthFileAvailablePercent(stale, store)).toBeNull();
  });
});
