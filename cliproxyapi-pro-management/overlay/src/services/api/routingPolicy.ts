import { apiClient } from './client';

export const ROUTING_POLICY_PROVIDERS = [
  'antigravity',
  'xai',
  'codex',
  'gemini-cli',
] as const;

export type RoutingPolicyProvider = (typeof ROUTING_POLICY_PROVIDERS)[number];
export type RoutingProtectionMode = 'observe' | 'enforce';

export interface RoutingPolicyGlobalSettings {
  strategy: 'round-robin' | 'fill-first';
  sessionAffinity: boolean;
  sessionAffinityTTL: string;
  requestRetry: number;
  maxRetryCredentials: number;
  maxRetryInterval: number;
  coolingEnabled: boolean;
  saveCooldownStatus: boolean;
  transientErrorCooldownSeconds: number;
  quotaSwitchProject: boolean;
  quotaSwitchPreviewModel: boolean;
  quotaAntigravityCredits: boolean;
  codexIdentityConfuse: boolean;
}

export interface RoutingProtectionProviderPolicy {
  enabled: boolean;
  statusCodes: number[];
  confirmations: number;
  confirmationWindowSeconds: number;
  autoEnable: boolean;
  fallbackDisableMinutes: number;
  requireQuotaEvidence: boolean;
}

export interface RoutingRequestProtectionConfig {
  enabled: boolean;
  mode: RoutingProtectionMode;
  providers: Record<RoutingPolicyProvider, RoutingProtectionProviderPolicy>;
}

export interface RoutingProtectedAccount {
  provider: string;
  authId: string;
  authIndex: string;
  fileName: string;
  statusCode: number;
  reason: string;
  triggeredAt: number;
  releaseAt: number;
}

export interface RoutingProtectionEvent {
  id: string;
  provider: string;
  authId: string;
  authIndex: string;
  statusCode: number;
  mode: RoutingProtectionMode;
  action: 'pending' | 'observe' | 'disabled' | 'released' | 'error' | string;
  reason: string;
  count: number;
  required: number;
  triggeredAt: number;
  releaseAt: number;
}

export interface RoutingPolicyResponse {
  global: RoutingPolicyGlobalSettings;
  requestProtection: RoutingRequestProtectionConfig;
  active: RoutingProtectedAccount[];
  recentEvents: RoutingProtectionEvent[];
}

export interface RoutingPolicyUpdate {
  global: RoutingPolicyGlobalSettings;
  requestProtection: RoutingRequestProtectionConfig;
}

export const routingPolicyApi = {
  get: () => apiClient.get<RoutingPolicyResponse>('/routing-policy'),
  update: (payload: RoutingPolicyUpdate) =>
    apiClient.put<RoutingPolicyResponse>('/routing-policy', payload),
  release: (authIndex: string) =>
    apiClient.post<RoutingPolicyResponse>('/routing-policy/release', { authIndex }),
};
