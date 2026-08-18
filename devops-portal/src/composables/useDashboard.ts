/**
 * Dashboard data binding for the portal homepage.
 *
 * Responsibilities (see docs/architecture-portal-dashboard.md §7, §8.7):
 *  - Own the requested scope and surface the *authoritative* scope/permission
 *    returned by the gateway (never trust the local principal alone).
 *  - Stale-while-revalidate polling every 60s, paused while the tab is hidden,
 *    with an immediate pull when the tab becomes visible again.
 *  - Expose per-domain degradation so a single failed card can render its own
 *    fallback without taking down the page.
 */
import { computed, getCurrentInstance, onUnmounted, ref, type Ref } from 'vue';

import {
  fetchDashboard,
  PERMISSION_CROSS_PROJECT_VIEW,
  SCOPE_MINE,
  type DashboardData,
  type Scope,
} from '../api/portal';
import { useAuthStore } from '../stores/auth';

const POLL_INTERVAL_MS = 60_000;

export type DashboardStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface UseDashboard {
  data: Ref<DashboardData | null>;
  status: Ref<DashboardStatus>;
  error: Ref<unknown>;
  scope: Ref<Scope>;
  /** Authoritative cross-project capability (from the backend response). */
  canCrossProject: Ref<boolean>;
  /** True only on the very first load, before any data has arrived. */
  isInitialLoading: Ref<boolean>;
  refresh: () => Promise<void>;
  setScope: (next: Scope) => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  isDegraded: (domain: string) => boolean;
}

export function useDashboard(initialScope: Scope = SCOPE_MINE): UseDashboard {
  const auth = useAuthStore();
  const data = ref<DashboardData | null>(null);
  const status = ref<DashboardStatus>('idle');
  const error = ref<unknown>(null);
  const scope = ref<Scope>(initialScope);
  const canCrossProject = ref<boolean>(auth.has(PERMISSION_CROSS_PROJECT_VIEW));

  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const isInitialLoading = computed(() => status.value === 'loading' && data.value === null);

  async function refresh(): Promise<void> {
    // First load shows the skeleton; later pulls keep the old data visible.
    if (data.value === null) {
      status.value = 'loading';
    }
    try {
      const result = await fetchDashboard(scope.value);
      data.value = result;
      // The gateway is authoritative: adopt its resolved scope + capability.
      scope.value = result.scope;
      canCrossProject.value = result.can_cross_project;
      status.value = 'ready';
      error.value = null;
    } catch (caught) {
      error.value = caught;
      // Keep showing stale data on a background poll failure; only a first-load
      // failure escalates to the page-level error state.
      status.value = data.value === null ? 'error' : 'ready';
    }
  }

  async function setScope(next: Scope): Promise<void> {
    scope.value = next;
    await refresh();
  }

  function onVisibility(): void {
    if (document.visibilityState === 'visible') {
      void refresh();
    }
  }

  function startPolling(): void {
    if (pollTimer) return;
    pollTimer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        void refresh();
      }
    }, POLL_INTERVAL_MS);
    document.addEventListener('visibilitychange', onVisibility);
  }

  function stopPolling(): void {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    document.removeEventListener('visibilitychange', onVisibility);
  }

  function isDegraded(domain: string): boolean {
    return data.value?.degraded.some((entry) => entry.domain === domain) ?? false;
  }

  // Only register the teardown hook when used inside a component; calling
  // onUnmounted at module top-level (e.g. in unit tests) only emits a warning.
  if (getCurrentInstance()) {
    onUnmounted(stopPolling);
  }

  return {
    data,
    status,
    error,
    scope,
    canCrossProject,
    isInitialLoading,
    refresh,
    setScope,
    startPolling,
    stopPolling,
    isDegraded,
  };
}
