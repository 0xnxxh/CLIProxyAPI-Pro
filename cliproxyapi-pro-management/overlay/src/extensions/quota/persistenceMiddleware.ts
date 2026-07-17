/**
 * Zustand persistence middleware for quota data.
 * Automatically syncs quota state to SQLite quota cache.
 */

import { useQuotaStore } from '@/stores';
import {
  getQuotaProviderMapName,
  getQuotaProviderSetterName,
  isRecordValue,
  isQuotaProviderType,
  QUOTA_PROVIDER_TYPES,
  type QuotaProviderType,
} from '@/utils/quota';
import { sqliteQuotaCache, type QuotaCacheEntry } from './sqliteQuotaCache';

interface QuotaStatusState {
  status: 'idle' | 'loading' | 'success' | 'error';
  cachedAt?: number;
}

type QuotaStoreState = ReturnType<typeof useQuotaStore.getState>;
type QuotaMapUpdater = (
  previous: Record<string, QuotaStatusState>
) => Record<string, QuotaStatusState>;

class QuotaPersistenceMiddleware {
  private unsubscribe: (() => void) | null = null;
  private isPreloading = false;
  private syncQueue = new Set<string>();
  private isFlushing = false;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private retryDelayMs = 1_000;
  private syncedVersions = new Map<string, string>();
  private loadedGeneration = 0;
  private reloadRequested = false;
  private preloadPromise: Promise<void> | null = null;
  private ensureFreshPromise: Promise<void> | null = null;
  private lastQuotaMaps = new Map<QuotaProviderType, Record<string, QuotaStatusState>>();
  private hydratedKeys = new Map<QuotaProviderType, Set<string>>();

  /**
   * Start the middleware
   */
  start() {
    if (this.unsubscribe) {
      console.warn('QuotaPersistenceMiddleware already started');
      return;
    }

    // Check if upstream store structure is compatible
    if (!this.checkCompatibility()) {
      console.warn('QuotaPersistenceMiddleware: Upstream store structure changed, persistence disabled');
      return;
    }

    console.log('QuotaPersistenceMiddleware: Starting...');

    // Preload cache first
    this.ensureFresh().then(() => {
      console.log('QuotaPersistenceMiddleware: Cache preloaded');
    });

    this.unsubscribe = useQuotaStore.subscribe((state) => {
      if (this.isPreloading) return;

      QUOTA_PROVIDER_TYPES.forEach((provider) => {
        const quotaMap = this.getQuotaMap(state, provider);
        if (!quotaMap || this.lastQuotaMaps.get(provider) === quotaMap) return;
        this.lastQuotaMaps.set(provider, quotaMap);
        this.syncProvider(provider, quotaMap);
      });
    });

    console.log('QuotaPersistenceMiddleware: Started successfully');
  }

  /**
   * Stop the middleware
   */
  stop() {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
    this.lastQuotaMaps.clear();
    this.syncedVersions.clear();
    this.hydratedKeys.clear();
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    void this.flushSyncQueue();
    console.log('QuotaPersistenceMiddleware: Stopped');
  }

  /**
   * Check if upstream store structure is compatible
   */
  private checkCompatibility(): boolean {
    const state = useQuotaStore.getState();
    const requiredFields = [
      ...QUOTA_PROVIDER_TYPES.map(getQuotaProviderMapName),
      ...QUOTA_PROVIDER_TYPES.map(getQuotaProviderSetterName),
      'clearQuotaCache',
    ];

    const missing = requiredFields.filter((field) => !(field in state));
    if (missing.length > 0) {
      console.error(`QuotaPersistenceMiddleware: Missing fields: ${missing.join(', ')}`);
      return false;
    }

    return true;
  }

  /**
   * Sync provider quota to SQLite quota cache.
   */
  private syncProvider(
    provider: QuotaProviderType,
    quotaMap: Record<string, QuotaStatusState>
  ) {
    let changed = false;
    const activeKeys = new Set<string>();
    Object.entries(quotaMap).forEach(([fileName, state]) => {
      const key = `${provider}:${fileName}`;
      activeKeys.add(key);
      if (state.status !== 'success') return;

      const version = this.getSyncVersion(state);
      if (this.syncedVersions.get(key) === version) return;
      this.syncQueue.add(key);
      changed = true;
    });

    this.pruneSyncedVersions(provider, activeKeys);
    if (changed) void this.flushSyncQueue();
  }

  private getSyncVersion(state: unknown) {
    if (state && typeof state === 'object' && 'cachedAt' in state) {
      const cachedAt = (state as QuotaStatusState).cachedAt;
      if (cachedAt !== undefined) return String(cachedAt);
    }
    return JSON.stringify(state);
  }

  private pruneSyncedVersions(provider: QuotaProviderType, activeKeys: Set<string>) {
    const prefix = `${provider}:`;
    Array.from(this.syncedVersions.keys()).forEach((key) => {
      if (key.startsWith(prefix) && !activeKeys.has(key)) {
        this.syncedVersions.delete(key);
      }
    });
  }

  /**
   * Flush sync queue to SQLite quota cache
   */
  private async flushSyncQueue() {
    if (this.isFlushing) return;
    this.isFlushing = true;

    try {
      while (this.syncQueue.size > 0) {
        const key = this.syncQueue.values().next().value as string | undefined;
        if (!key) break;
        this.syncQueue.delete(key);

        const separatorIndex = key.indexOf(':');
        if (separatorIndex <= 0) continue;

        const provider = key.slice(0, separatorIndex) as QuotaProviderType;
        const fileName = key.slice(separatorIndex + 1);
        const state = useQuotaStore.getState();
        const quotaMap = this.getQuotaMap(state, provider);
        const quotaState = quotaMap?.[fileName];

        if (quotaState?.status !== 'success') continue;

        const version = this.getSyncVersion(quotaState);
        const cachedAt = quotaState.cachedAt ?? Date.now();
        const synced = await sqliteQuotaCache.set(provider, fileName, { ...quotaState, cachedAt }, cachedAt);
        if (synced) {
          this.syncedVersions.set(key, version);
          this.retryDelayMs = 1_000;
        } else {
          this.syncQueue.add(key);
          this.scheduleRetry();
          break;
        }
      }
    } catch (err) {
      console.error('QuotaPersistenceMiddleware: Failed to sync to SQLite quota cache:', err);
    } finally {
      this.isFlushing = false;
      if (this.syncQueue.size > 0 && !this.retryTimer) {
        void this.flushSyncQueue();
      }
    }
  }

  private scheduleRetry() {
    if (this.retryTimer) return;
    const delay = this.retryDelayMs;
    this.retryDelayMs = Math.min(this.retryDelayMs * 2, 30_000);
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.flushSyncQueue();
    }, delay);
  }

  async ensureFresh() {
    if (this.ensureFreshPromise) return this.ensureFreshPromise;

    this.ensureFreshPromise = (async () => {
      const stats = await sqliteQuotaCache.getStats();
      if (!this.reloadRequested && stats.generation > 0 && stats.generation <= this.loadedGeneration) return;
      await this.runPreload(stats.generation);
      this.reloadRequested = false;
    })().finally(() => {
      this.ensureFreshPromise = null;
    });

    return this.ensureFreshPromise;
  }

  private runPreload(generation = 0) {
    if (this.preloadPromise) return this.preloadPromise;

    this.preloadPromise = this.preloadCache(generation).finally(() => {
      this.preloadPromise = null;
    });

    return this.preloadPromise;
  }

  markStale() {
    this.reloadRequested = true;
  }

  /**
   * Preload cache from SQLite quota cache to Zustand store
   */
  private async preloadCache(generation = 0) {
    this.isPreloading = true;

    try {
      const cachedEntries = await sqliteQuotaCache.getAll();
      const entriesByProvider = new Map<QuotaProviderType, QuotaCacheEntry[]>();
      cachedEntries.forEach((entry) => {
        if (!isQuotaProviderType(entry.provider)) return;
        const provider = entry.provider;
        const entries = entriesByProvider.get(provider) ?? [];
        entries.push(entry);
        entriesByProvider.set(provider, entries);
      });

      QUOTA_PROVIDER_TYPES.forEach((provider) => {
        this.preloadProvider(provider, entriesByProvider.get(provider) ?? []);
      });
      this.loadedGeneration = Math.max(this.loadedGeneration, generation);
    } catch (err) {
      console.error('QuotaPersistenceMiddleware: Failed to preload cache:', err);
    } finally {
      this.isPreloading = false;
    }
  }

  /**
   * Preload single provider from SQLite quota cache
   */
  private preloadProvider(provider: QuotaProviderType, cachedEntries: QuotaCacheEntry[]) {
    const cached = new Map(cachedEntries.map((entry) => [entry.fileName, entry]));
    const previouslyHydrated = this.hydratedKeys.get(provider) ?? new Set<string>();

    const setterName = getQuotaProviderSetterName(provider);
    const storeState = useQuotaStore.getState();
    const setter = storeState[setterName] as unknown as (updater: QuotaMapUpdater) => void;

    if (typeof setter === 'function') {
      setter((prev) => {
        let changed = false;
        const next = { ...prev };
        previouslyHydrated.forEach((fileName) => {
          if (cached.has(fileName) || !(fileName in next)) return;
          delete next[fileName];
          this.syncedVersions.delete(`${provider}:${fileName}`);
          changed = true;
        });
        cached.forEach((entry, fileName) => {
          if (!this.isCacheEntryCompatible(provider, entry.data)) {
            void sqliteQuotaCache.delete(provider, fileName);
            return;
          }
          this.syncedVersions.set(`${provider}:${fileName}`, this.getSyncVersion(entry.data));
          if (next[fileName] === entry.data) return;
          next[fileName] = entry.data;
          changed = true;
        });
        return changed ? next : prev;
      });

      this.hydratedKeys.set(provider, new Set(cached.keys()));

      console.log(`QuotaPersistenceMiddleware: Preloaded ${cached.size} entries for ${provider}`);
    }
  }

  private isCacheEntryCompatible(provider: QuotaProviderType, data: unknown): data is QuotaStatusState {
    if (!isRecordValue(data)) return false;

    const status = data.status;
    if (!['idle', 'loading', 'success', 'error'].includes(String(status))) return false;
    if (status !== 'success') return true;

    switch (provider) {
      case 'antigravity': {
        const groups = data.groups;
        return Array.isArray(groups) && groups.every((group) => (
          isRecordValue(group) && Array.isArray(group.buckets)
        ));
      }
      case 'claude':
      case 'codex':
        return Array.isArray(data.windows);
      case 'gemini-cli':
        return Array.isArray(data.buckets);
      case 'kimi':
        return Array.isArray(data.rows);
      case 'xai':
        return isRecordValue(data.billing);
      default:
        return false;
    }
  }

  /**
   * Get quota map from state by provider
   */
  private getQuotaMap(
    state: QuotaStoreState,
    provider: QuotaProviderType
  ): Record<string, QuotaStatusState> | null {
    const mapName = getQuotaProviderMapName(provider);
    return state[mapName] || null;
  }

  /**
   * Get cache statistics
   */
  async getStats() {
    return await sqliteQuotaCache.getStats();
  }

  /**
   * Clear all cache
   */
  async clearCache() {
    await sqliteQuotaCache.clear();
    this.syncedVersions.clear();
    this.syncQueue.clear();
    this.hydratedKeys.clear();
    this.loadedGeneration = 0;
    this.reloadRequested = true;
    console.log('QuotaPersistenceMiddleware: Cache cleared');
  }
}

export const quotaPersistenceMiddleware = new QuotaPersistenceMiddleware();
