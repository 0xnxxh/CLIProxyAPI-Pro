import { describe, expect, test } from 'bun:test';
import {
  resolveGeminiCliTierDisplayLabel,
  type GeminiCliTierLabelKey,
} from '../src/extensions/quota/geminiCliTierLabels';

const labels: Record<GeminiCliTierLabelKey, string> = {
  tier_free: 'Gemini Code Assist Free',
  tier_legacy: 'Gemini Code Assist Legacy',
  tier_standard: 'Gemini Code Assist Standard',
  tier_pro: 'Google AI Pro',
  tier_ultra: 'Google AI Ultra',
};

const resolve = (tierId: unknown, upstreamLabel: unknown): string | null =>
  resolveGeminiCliTierDisplayLabel(tierId, upstreamLabel, (key) => labels[key]);

describe('Gemini CLI tier labels', () => {
  test('uses the tier ID instead of a generic upstream product name', () => {
    expect(resolve('free-tier', 'Gemini Code Assist')).toBe('Gemini Code Assist Free');
    expect(resolve('legacy-tier', 'Gemini Code Assist')).toBe('Gemini Code Assist Legacy');
    expect(resolve('standard-tier', 'Gemini Code Assist')).toBe('Gemini Code Assist Standard');
  });

  test('uses Google AI product names for paid tiers', () => {
    expect(resolve('g1-pro-tier', 'Gemini Code Assist')).toBe('Google AI Pro');
    expect(resolve('g1-ultra-tier', 'Gemini Code Assist')).toBe('Google AI Ultra');
  });

  test('normalizes known IDs and preserves unknown upstream labels', () => {
    expect(resolve(' G1-PRO-TIER ', 'Generic')).toBe('Google AI Pro');
    expect(resolve('future-tier', 'Future Plan')).toBe('Future Plan');
    expect(resolve('future-tier', null)).toBe('future-tier');
    expect(resolve(null, null)).toBeNull();
  });
});
