import type { AuthFileItem } from '@/types';
import { useQuotaStore } from '@/stores';
import { normalizeProviderKey } from '@/features/authFiles/constants';

const PLAN_SORT_PROVIDERS = new Set(['antigravity', 'claude', 'codex', 'gemini-cli', 'xai']);
const XAI_SUPERGROK_LIMIT_CENTS = 15_000;
const XAI_SUPERGROK_HEAVY_LIMIT_CENTS = 150_000;

const PLAN_RANKS: Record<string, Record<string, number>> = {
  antigravity: {
    ultra: 500,
    'ultra-lite': 450,
    pro: 300,
    free: 100,
  },
  claude: {
    enterprise: 700,
    team: 600,
    'max-20x': 500,
    'max-5x': 450,
    max: 425,
    pro: 300,
    free: 100,
  },
  codex: {
    enterprise: 700,
    team: 600,
    business: 600,
    pro: 500,
    'pro-lite': 450,
    prolite: 450,
    plus: 300,
    free: 100,
  },
  'gemini-cli': {
    ultra: 500,
    'g1-ultra-tier': 500,
    pro: 400,
    'g1-pro-tier': 400,
    standard: 300,
    'standard-tier': 300,
    legacy: 200,
    'legacy-tier': 200,
    free: 100,
    'free-tier': 100,
  },
  xai: {
    'supergrok-heavy': 500,
    supergrok: 400,
  },
};

type PlanSortQuotaStore = Pick<
  ReturnType<typeof useQuotaStore.getState>,
  'antigravityQuota' | 'claudeQuota' | 'codexQuota' | 'geminiCliQuota' | 'xaiQuota'
>;

type PlanSortKey = {
  rank: number;
  label: string;
};

const toRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const normalizePlan = (value: unknown): string =>
  typeof value === 'string'
    ? value.trim().toLowerCase().replace(/_/g, '-').replace(/^plan-/, '').replace(/\s+/g, '-')
    : '';

const readPlanField = (item: AuthFileItem, ...keys: string[]): unknown => {
  const record = item as Record<string, unknown>;
  const containers = [
    record,
    toRecord(record.metadata),
    toRecord(record.attributes),
    toRecord(record.id_token),
    toRecord(record.idToken),
  ];
  for (const container of containers) {
    if (!container) continue;
    for (const key of keys) {
      const value = container[key];
      if (value !== undefined && value !== null && value !== '') return value;
    }
  }
  return null;
};

const normalizeCents = (value: unknown): number | null => {
  const source = toRecord(value)?.val ?? value;
  if (typeof source === 'number' && Number.isFinite(source)) return source;
  if (typeof source !== 'string') return null;
  const parsed = Number(source.trim());
  return Number.isFinite(parsed) ? parsed : null;
};

const resolvePlanSortKey = (item: AuthFileItem, quotaStore: PlanSortQuotaStore): PlanSortKey => {
  const provider = normalizeProviderKey(String(item.type ?? item.provider ?? ''));
  const name = item.name;
  let rawPlan: unknown = null;

  if (provider === 'antigravity') {
    const subscription =
      quotaStore.antigravityQuota[name]?.subscription ??
      readPlanField(item, 'subscription', 'subscriptionPlan', 'subscription_plan');
    const record = toRecord(subscription);
    rawPlan = record?.plan ?? record?.tierName ?? record?.tierId ?? subscription;
  } else if (provider === 'claude') {
    rawPlan =
      quotaStore.claudeQuota[name]?.planType ??
      readPlanField(item, 'planType', 'plan_type', 'plan');
  } else if (provider === 'codex') {
    rawPlan =
      quotaStore.codexQuota[name]?.planType ??
      readPlanField(item, 'planType', 'plan_type', 'plan');
  } else if (provider === 'gemini-cli') {
    rawPlan =
      quotaStore.geminiCliQuota[name]?.tierId ??
      quotaStore.geminiCliQuota[name]?.tierLabel ??
      readPlanField(item, 'tierId', 'tier_id', 'tierLabel', 'tier_label', 'tier');
  } else if (provider === 'xai') {
    const billing = quotaStore.xaiQuota[name]?.billing;
    const monthlyLimitCents = normalizeCents(billing?.monthlyLimitCents);
    rawPlan =
      monthlyLimitCents === XAI_SUPERGROK_HEAVY_LIMIT_CENTS
        ? 'supergrok-heavy'
        : monthlyLimitCents === XAI_SUPERGROK_LIMIT_CENTS
          ? 'supergrok'
          : readPlanField(item, 'planType', 'plan_type', 'plan', 'package');
  }

  const label = normalizePlan(rawPlan);
  if (!label) return { rank: 0, label: '' };
  return { rank: PLAN_RANKS[provider]?.[label] ?? 1, label };
};

export const isAuthFilePlanSortProvider = (provider: string): boolean =>
  PLAN_SORT_PROVIDERS.has(normalizeProviderKey(provider));

export const compareAuthFilesByPlanDescending = (
  left: AuthFileItem,
  right: AuthFileItem,
  quotaStore: PlanSortQuotaStore
): number => {
  const leftPlan = resolvePlanSortKey(left, quotaStore);
  const rightPlan = resolvePlanSortKey(right, quotaStore);
  if (leftPlan.rank !== rightPlan.rank) return rightPlan.rank - leftPlan.rank;
  const labelCompare = leftPlan.label.localeCompare(rightPlan.label);
  if (labelCompare !== 0) return labelCompare;
  return left.name.localeCompare(right.name);
};
