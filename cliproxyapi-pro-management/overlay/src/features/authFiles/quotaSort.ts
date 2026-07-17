import type { AuthFileItem } from '@/types';
import { useQuotaStore } from '@/stores';
import { normalizeProviderKey } from '@/features/authFiles/constants';

const QUOTA_SORT_PROVIDERS = new Set([
  'antigravity',
  'claude',
  'codex',
  'gemini-cli',
  'kimi',
  'xai',
]);

export const AUTH_FILE_QUOTA_SORT_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const AUTH_FILE_QUOTA_SORT_MAX_FUTURE_SKEW_MS = 5 * 60 * 1000;

type QuotaSortStore = Pick<
  ReturnType<typeof useQuotaStore.getState>,
  | 'antigravityQuota'
  | 'claudeQuota'
  | 'codexQuota'
  | 'geminiCliQuota'
  | 'kimiQuota'
  | 'xaiQuota'
>;

const toRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const normalizeNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : null;
};

const clampPercent = (value: number): number => Math.max(0, Math.min(100, value));

const readBoolean = (value: unknown): boolean | null => {
  if (typeof value === 'boolean') return value;
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  if (normalized === 'true') return true;
  if (normalized === 'false') return false;
  return null;
};

const remainingPercentFromFraction = (value: unknown): number | null => {
  const fraction = normalizeNumber(value);
  if (fraction === null || fraction > 100) return null;
  return clampPercent(fraction > 1 ? fraction : fraction * 100);
};

const remainingPercentFromItem = (value: unknown): number | null => {
  const item = toRecord(value);
  if (!item) return null;

  if (readBoolean(item.limitReached ?? item.limit_reached) === true) return 0;
  if (item.allowed !== undefined && readBoolean(item.allowed) === false) return 0;

  const usedPercent = normalizeNumber(item.usedPercent ?? item.used_percent ?? item.usagePercent ?? item.usage_percent);
  if (usedPercent !== null) return clampPercent(100 - clampPercent(usedPercent));

  const remainingFraction = remainingPercentFromFraction(
    item.remainingFraction ?? item.remaining_fraction
  );
  if (remainingFraction !== null) return remainingFraction;

  const limit = normalizeNumber(item.limit);
  if (limit === null || limit <= 0) return null;
  const remaining = normalizeNumber(item.remainingAmount ?? item.remaining_amount ?? item.remaining);
  if (remaining !== null) return clampPercent((remaining / limit) * 100);
  const used = normalizeNumber(item.used);
  if (used !== null) return clampPercent(((limit - used) / limit) * 100);
  return null;
};

const minimumRemainingPercent = (items: unknown): number | null => {
  if (!Array.isArray(items)) return null;
  const values = items
    .map(remainingPercentFromItem)
    .filter((value): value is number => value !== null);
  return values.length > 0 ? Math.min(...values) : null;
};

const isFreshQuotaState = (state: Record<string, unknown>): boolean => {
  const cachedAt = normalizeNumber(state.cachedAt);
  if (cachedAt === null || cachedAt <= 0) return false;
  const age = Date.now() - cachedAt;
  return age >= -AUTH_FILE_QUOTA_SORT_MAX_FUTURE_SKEW_MS && age <= AUTH_FILE_QUOTA_SORT_MAX_AGE_MS;
};

const antigravityRemainingPercent = (quota: unknown): number | null => {
  const state = toRecord(quota);
  if (!state || state.status !== 'success' || !isFreshQuotaState(state) || !Array.isArray(state.groups)) return null;
  const buckets = state.groups.flatMap((group) => {
    const record = toRecord(group);
    return record && Array.isArray(record.buckets) ? record.buckets : [];
  });
  return minimumRemainingPercent(buckets);
};

const windowedRemainingPercent = (quota: unknown, key: 'windows' | 'buckets' | 'rows'): number | null => {
  const state = toRecord(quota);
  if (!state || state.status !== 'success' || !isFreshQuotaState(state)) return null;
  return minimumRemainingPercent(state[key]);
};

const xaiRemainingPercent = (quota: unknown): number | null => {
  const state = toRecord(quota);
  if (!state || state.status !== 'success' || !isFreshQuotaState(state)) return null;
  const billing = toRecord(state.billing);
  if (!billing) return null;

  const usedPercent = normalizeNumber(billing.usagePercent ?? billing.usage_percent);
  if (usedPercent !== null) return clampPercent(100 - clampPercent(usedPercent));

  const monthlyUsedPercent = normalizeNumber(billing.usedPercent ?? billing.used_percent);
  if (monthlyUsedPercent !== null) return clampPercent(100 - clampPercent(monthlyUsedPercent));

  const productRemaining = minimumRemainingPercent(billing.productUsage ?? billing.product_usage);
  if (productRemaining !== null) return productRemaining;

  const monthlyLimit = normalizeNumber(billing.monthlyLimitCents ?? billing.monthly_limit_cents);
  const monthlyUsed = normalizeNumber(billing.includedUsedCents ?? billing.included_used_cents);
  if (monthlyLimit !== null && monthlyLimit > 0 && monthlyUsed !== null) {
    return clampPercent(((monthlyLimit - monthlyUsed) / monthlyLimit) * 100);
  }
  return null;
};

export const isAuthFileQuotaSortProvider = (provider: string): boolean =>
  QUOTA_SORT_PROVIDERS.has(normalizeProviderKey(provider));

export const resolveAuthFileAvailablePercent = (
  item: AuthFileItem,
  quotaStore: QuotaSortStore
): number | null => {
  const provider = normalizeProviderKey(String(item.type ?? item.provider ?? ''));
  const name = item.name;
  if (provider === 'antigravity') return antigravityRemainingPercent(quotaStore.antigravityQuota[name]);
  if (provider === 'claude') return windowedRemainingPercent(quotaStore.claudeQuota[name], 'windows');
  if (provider === 'codex') return windowedRemainingPercent(quotaStore.codexQuota[name], 'windows');
  if (provider === 'gemini-cli') return windowedRemainingPercent(quotaStore.geminiCliQuota[name], 'buckets');
  if (provider === 'kimi') return windowedRemainingPercent(quotaStore.kimiQuota[name], 'rows');
  if (provider === 'xai') return xaiRemainingPercent(quotaStore.xaiQuota[name]);
  return null;
};

export const compareAuthFilesByAvailableQuotaDescending = (
  left: AuthFileItem,
  right: AuthFileItem,
  quotaStore: QuotaSortStore
): number => {
  const leftAvailable = resolveAuthFileAvailablePercent(left, quotaStore);
  const rightAvailable = resolveAuthFileAvailablePercent(right, quotaStore);
  if (leftAvailable === null || rightAvailable === null) {
    if (leftAvailable === null && rightAvailable !== null) return 1;
    if (leftAvailable !== null && rightAvailable === null) return -1;
  } else if (leftAvailable !== rightAvailable) {
    return rightAvailable - leftAvailable;
  }
  return left.name.localeCompare(right.name);
};
