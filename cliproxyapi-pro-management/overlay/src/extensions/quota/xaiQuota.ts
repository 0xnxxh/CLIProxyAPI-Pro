import type { XaiBillingSummary } from '@/types';

export const XAI_SUPERGROK_LIMIT_CENTS = 15_000;
export const XAI_X_PREMIUM_PLUS_LIMIT_CENTS = 20_000;
export const XAI_SUPERGROK_HEAVY_LIMIT_CENTS = 150_000;

export type XaiNormalizedPlanType =
  | 'free'
  | 'supergrok'
  | 'x-premium-plus'
  | 'supergrok-heavy'
  | 'paid'
  | 'paid-unknown';

export const resolveXaiPlanType = (
  monthlyLimitCents: number | null,
  monthlyBillingKnown: boolean
): XaiNormalizedPlanType | undefined => {
  if (!monthlyBillingKnown) return undefined;
  if (monthlyLimitCents === null || monthlyLimitCents === 0) return 'free';
  if (monthlyLimitCents === XAI_SUPERGROK_LIMIT_CENTS) return 'supergrok';
  if (monthlyLimitCents === XAI_X_PREMIUM_PLUS_LIMIT_CENTS) return 'x-premium-plus';
  if (monthlyLimitCents === XAI_SUPERGROK_HEAVY_LIMIT_CENTS) return 'supergrok-heavy';
  return monthlyLimitCents > 0 ? 'paid-unknown' : undefined;
};

const observedAt = (billing: XaiBillingSummary | null | undefined): number => {
  const value = billing?.freeQuota?.observedAt;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
};

export const mergeXaiBillingRuntimeState = (
  billing: XaiBillingSummary,
  previous: XaiBillingSummary | null | undefined
): XaiBillingSummary => {
  let merged = billing;
  if (billing.planType === undefined && previous?.planType !== undefined) {
    merged = { ...merged, planType: previous.planType };
  }
  if (previous?.freeQuota && (!billing.freeQuota || observedAt(previous) > observedAt(billing))) {
    merged = { ...merged, freeQuota: previous.freeQuota };
  }
  return merged;
};

export const xaiFreeQuotaUsedPercent = (
  billing: unknown
): number | null => {
  if (!billing || typeof billing !== 'object' || Array.isArray(billing)) return null;
  const record = billing as Record<string, unknown>;
  const candidate = record.freeQuota ?? record.free_quota;
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return null;
  const freeQuota = candidate as Record<string, unknown>;
  if (freeQuota.exhausted === true) return 100;
  const used = Number(freeQuota.usedTokens ?? freeQuota.used_tokens);
  const limit = Number(freeQuota.limitTokens ?? freeQuota.limit_tokens);
  if (!Number.isFinite(used) || !Number.isFinite(limit) || limit <= 0) return null;
  return Math.max(0, Math.min(100, (used / limit) * 100));
};

export const xaiFreeQuotaRemainingPercent = (
  billing: unknown
): number | null => {
  const used = xaiFreeQuotaUsedPercent(billing);
  return used === null ? null : Math.max(0, Math.min(100, 100 - used));
};
