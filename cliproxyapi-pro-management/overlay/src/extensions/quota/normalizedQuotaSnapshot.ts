const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

export const normalizePersistedQuotaState = (
  provider: string,
  data: unknown,
  cachedAt: number
): unknown => {
  if (provider !== 'gemini-cli' || !isRecord(data)) return data;
  if (data.status !== undefined || !Array.isArray(data.items)) return data;

  const plan = isRecord(data.plan) ? data.plan : null;
  const metadata = isRecord(data.metadata) ? data.metadata : null;
  return {
    status: 'success',
    buckets: data.items.filter(isRecord).map((item) => ({
      id: String(item.id ?? ''),
      label: String(item.label ?? item.id ?? ''),
      remainingFraction:
        typeof item.remaining_fraction === 'number' ? item.remaining_fraction : null,
      remainingAmount:
        typeof item.remaining_amount === 'number' ? item.remaining_amount : null,
      resetTime: typeof item.reset_at === 'string' ? item.reset_at : undefined,
      tokenType:
        isRecord(item.metadata) && typeof item.metadata.token_type === 'string'
          ? item.metadata.token_type
          : null,
      modelIds: Array.isArray(item.model_ids) ? item.model_ids : [],
    })),
    projectId: typeof metadata?.project_id === 'string' ? metadata.project_id : '',
    tierLabel: typeof plan?.label === 'string' ? plan.label : null,
    tierId: typeof plan?.id === 'string' ? plan.id : null,
    creditBalance: typeof plan?.credit_balance === 'number' ? plan.credit_balance : null,
    cachedAt: typeof data.observed_at_ms === 'number' ? data.observed_at_ms : cachedAt,
    quotaProviderSnapshot: true,
  };
};
