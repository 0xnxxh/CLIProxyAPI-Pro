export type GeminiCliTierLabelKey =
  | 'tier_free'
  | 'tier_legacy'
  | 'tier_standard'
  | 'tier_pro'
  | 'tier_ultra';

const GEMINI_CLI_TIER_LABEL_KEYS: Record<string, GeminiCliTierLabelKey> = {
  'free-tier': 'tier_free',
  'legacy-tier': 'tier_legacy',
  'standard-tier': 'tier_standard',
  'g1-pro-tier': 'tier_pro',
  'g1-ultra-tier': 'tier_ultra',
};

const normalizeText = (value: unknown): string | null => {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized || null;
};

export const resolveGeminiCliTierDisplayLabel = (
  tierId: unknown,
  upstreamLabel: unknown,
  translate: (key: GeminiCliTierLabelKey) => string
): string | null => {
  const normalizedTierId = normalizeText(tierId);
  const labelKey = normalizedTierId
    ? GEMINI_CLI_TIER_LABEL_KEYS[normalizedTierId.toLowerCase()]
    : undefined;
  if (labelKey) return translate(labelKey);

  return normalizeText(upstreamLabel) ?? normalizedTierId;
};
