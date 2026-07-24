import React from 'react';
import type { ReactNode } from 'react';
import type { TFunction } from 'i18next';
import type {
  AuthFileItem,
  GeminiCliQuotaBucketState,
  GeminiCliQuotaState,
} from '@/types';
import { apiClient } from '@/services/api/client';
import {
  formatQuotaResetTime,
  isDisabledAuthFile,
  isGeminiCliFile,
  isRuntimeOnlyAuthFile,
  normalizeNumberValue,
  normalizeQuotaFraction,
  normalizeStringValue,
} from '@/utils/quota';
import { normalizeAuthIndex } from '@/utils/authIndex';
import type { QuotaConfig } from '@/components/quota/quotaConfigs';
import type { QuotaRenderHelpers } from '@/components/quota/QuotaCard';
import styles from '@/pages/QuotaPage.module.scss';
import { resolveGeminiCliTierDisplayLabel } from './geminiCliTierLabels';

const QUOTA_PROGRESS_HIGH_THRESHOLD = 70;
const QUOTA_PROGRESS_MEDIUM_THRESHOLD = 30;

type GeminiCliQuotaData = {
  fileName: string;
  buckets: GeminiCliQuotaBucketState[];
  projectId: string;
  tierLabel: string | null;
  tierId: string | null;
  creditBalance: number | null;
};

const resolveGeminiCliTierDisplay = (
  tierId: unknown,
  upstreamLabel: unknown,
  t: TFunction
): string | null =>
  resolveGeminiCliTierDisplayLabel(tierId, upstreamLabel, (labelKey) =>
    t(`gemini_cli_quota.${labelKey}`)
  );

type PluginQuotaItem = {
  id: string;
  label: string;
  remaining_fraction?: number;
  remaining_amount?: number;
  reset_at?: string;
  model_ids?: string[];
  metadata?: Record<string, unknown>;
};

type PluginQuotaSnapshot = {
  schema_version: number;
  observed_at_ms: number;
  items: PluginQuotaItem[];
  plan?: {
    id?: string;
    label?: string;
    credit_balance?: number;
  };
  metadata?: Record<string, unknown>;
};

type PluginQuotaFetchResponse = {
  snapshot?: PluginQuotaSnapshot;
};

const PREMIUM_GEMINI_CLI_TIER_IDS = new Set(['g1-pro-tier', 'g1-ultra-tier']);

const fetchGeminiCliQuota = async (
  file: AuthFileItem,
  t: TFunction
): Promise<GeminiCliQuotaData> => {
  const authIndex = normalizeAuthIndex(file['auth_index'] ?? file.authIndex);
  if (!authIndex) {
    throw new Error(t('gemini_cli_quota.missing_auth_index'));
  }

  const response = await apiClient.post<PluginQuotaFetchResponse>('/quota/fetch', {
    auth_index: authIndex,
  });
  const snapshot = response.snapshot;
  if (!snapshot || !Array.isArray(snapshot.items) || snapshot.items.length === 0) {
    throw new Error(t('gemini_cli_quota.empty_buckets'));
  }
  const buckets: GeminiCliQuotaBucketState[] = snapshot.items.map((item) => ({
    id: item.id,
    label: item.label,
    remainingFraction: normalizeQuotaFraction(item.remaining_fraction),
    remainingAmount: normalizeNumberValue(item.remaining_amount),
    resetTime: normalizeStringValue(item.reset_at) ?? undefined,
    tokenType: normalizeStringValue(item.metadata?.token_type),
    modelIds: Array.isArray(item.model_ids) ? item.model_ids : [],
  }));
  const tierId = normalizeStringValue(snapshot.plan?.id);
  return {
    fileName: file.name,
    buckets,
    projectId: normalizeStringValue(snapshot.metadata?.project_id) ?? '',
    tierLabel: resolveGeminiCliTierDisplay(tierId, snapshot.plan?.label, t),
    tierId,
    creditBalance: normalizeNumberValue(snapshot.plan?.credit_balance),
  };
};

const renderGeminiCliItems = (
  quota: GeminiCliQuotaState,
  t: TFunction,
  helpers: QuotaRenderHelpers
): ReactNode => {
  const { styles: styleMap, QuotaProgressBar } = helpers;
  const { createElement: h, Fragment } = React;
  const buckets = quota.buckets ?? [];
  const nodes: ReactNode[] = [];
  const tierId = quota.tierId ?? null;
  const tierLabel = resolveGeminiCliTierDisplay(tierId, quota.tierLabel, t);
  const creditBalance = quota.creditBalance ?? null;

  if (tierLabel || creditBalance !== null) {
    nodes.push(
      h(
        'div',
        { key: 'tier', className: styleMap.codexPlan },
        tierLabel
          ? h(
              'span',
              { className: styleMap.codexPlanItem },
              h('span', { className: styleMap.codexPlanLabel }, t('gemini_cli_quota.tier_label')),
              h(
                'span',
                {
                  className:
                    tierId && PREMIUM_GEMINI_CLI_TIER_IDS.has(tierId)
                      ? styleMap.premiumPlanValue
                      : styleMap.codexPlanValue,
                },
                tierLabel
              )
            )
          : null,
        creditBalance !== null
          ? h(
              'span',
              { className: styleMap.codexPlanItem },
              h('span', { className: styleMap.codexPlanLabel }, t('gemini_cli_quota.credit_label')),
              h(
                'span',
                { className: styleMap.codexPlanValue },
                t('gemini_cli_quota.credit_amount', { count: creditBalance })
              )
            )
          : null
      )
    );
  }

  if (buckets.length === 0) {
    nodes.push(
      h('div', { key: 'empty', className: styleMap.quotaMessage }, t('gemini_cli_quota.empty_buckets'))
    );
    return h(Fragment, null, ...nodes);
  }

  nodes.push(
    ...buckets.map((bucket) => {
      const remainingFraction = bucket.remainingFraction;
      const remaining =
        remainingFraction === null ? null : Math.max(0, Math.min(100, remainingFraction * 100));
      const percentLabel = remaining === null ? '--' : `${Math.round(remaining)}%`;
      const amountLabel =
        bucket.remainingAmount === null
          ? null
          : t('gemini_cli_quota.remaining_amount', { count: bucket.remainingAmount });

      return h(
        'div',
        { key: bucket.id, className: styleMap.quotaRow },
        h(
          'div',
          { className: styleMap.quotaRowHeader },
          h('span', { className: styleMap.quotaModel, title: bucket.modelIds?.join(', ') }, bucket.label),
          h(
            'div',
            { className: styleMap.quotaMeta },
            h('span', { className: styleMap.quotaPercent }, percentLabel),
            amountLabel ? h('span', { className: styleMap.quotaAmount }, amountLabel) : null,
            h('span', { className: styleMap.quotaReset }, formatQuotaResetTime(bucket.resetTime))
          )
        ),
        h(QuotaProgressBar, {
          percent: remaining,
          highThreshold: QUOTA_PROGRESS_HIGH_THRESHOLD,
          mediumThreshold: QUOTA_PROGRESS_MEDIUM_THRESHOLD,
        })
      );
    })
  );

  return h(Fragment, null, ...nodes);
};

export const GEMINI_CLI_CONFIG = {
  type: 'gemini-cli',
  i18nPrefix: 'gemini_cli_quota',
  filterFn: (file: AuthFileItem) =>
    isGeminiCliFile(file) && !isRuntimeOnlyAuthFile(file) && !isDisabledAuthFile(file),
  fetchQuota: fetchGeminiCliQuota,
  storeSelector: (state) => state.geminiCliQuota,
  storeSetter: 'setGeminiCliQuota',
  buildLoadingState: () => ({
    status: 'loading',
    buckets: [],
    projectId: '',
    tierLabel: null,
    tierId: null,
    creditBalance: null,
  }),
  buildSuccessState: (data: GeminiCliQuotaData) => ({
    status: 'success',
    buckets: data.buckets,
    projectId: data.projectId,
    tierLabel: data.tierLabel,
    tierId: data.tierId,
    creditBalance: data.creditBalance,
    quotaProviderSnapshot: true,
    cachedAt: Date.now(),
  }),
  buildErrorState: (message: string, status?: number) => ({
    status: 'error',
    buckets: [],
    projectId: '',
    tierLabel: null,
    tierId: null,
    creditBalance: null,
    error: message,
    errorStatus: status,
  }),
  cardClassName: styles.geminiCliCard,
  gridClassName: styles.geminiCliGrid,
  renderQuotaItems: renderGeminiCliItems,
} satisfies QuotaConfig<GeminiCliQuotaState, GeminiCliQuotaData>;
