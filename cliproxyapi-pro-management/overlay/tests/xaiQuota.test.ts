import { describe, expect, test } from 'bun:test';
import {
  mergeXaiBillingRuntimeState,
  resolveXaiPlanType,
  xaiFreeQuotaRemainingPercent,
} from '@/extensions/quota/xaiQuota';

describe('xAI quota normalization', () => {
  test('recognizes plans only from a known monthly billing response', () => {
    expect(resolveXaiPlanType(null, false)).toBeUndefined();
    expect(resolveXaiPlanType(null, true)).toBe('free');
    expect(resolveXaiPlanType(0, true)).toBe('free');
    expect(resolveXaiPlanType(15_000, true)).toBe('supergrok');
    expect(resolveXaiPlanType(20_000, true)).toBe('x-premium-plus');
    expect(resolveXaiPlanType(150_000, true)).toBe('supergrok-heavy');
    expect(resolveXaiPlanType(99_000, true)).toBe('paid-unknown');
  });

  test('preserves the newest runtime free-quota observation', () => {
    const incoming = {
      mode: 'billing' as const,
      periodType: 'monthly' as const,
      usagePercent: null,
      productUsage: [],
      monthlyLimitCents: 20_000,
      usedCents: null,
      includedUsedCents: null,
      onDemandCapCents: null,
      onDemandUsedCents: null,
      onDemandUsedPercent: null,
      usedPercent: null,
      freeQuota: { observedAt: 100, remainingTokens: 80 },
    };
    const previous = {
      ...incoming,
      planType: 'x-premium-plus' as const,
      freeQuota: { observedAt: 200, remainingTokens: 10 },
    };

    const merged = mergeXaiBillingRuntimeState(incoming, previous);
    expect(merged.planType).toBe('x-premium-plus');
    expect(merged.freeQuota?.remainingTokens).toBe(10);
  });

  test('derives free-token availability and handles exhaustion', () => {
    expect(xaiFreeQuotaRemainingPercent({
      freeQuota: { usedTokens: 25, limitTokens: 100 },
    })).toBe(75);
    expect(xaiFreeQuotaRemainingPercent({ freeQuota: { exhausted: true } })).toBe(0);
  });
});
