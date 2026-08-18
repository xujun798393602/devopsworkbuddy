import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

vi.mock('../api/client', () => ({ api: vi.fn() }));

import { api } from '../api/client';
import { useAuthStore } from '../stores/auth';
import { SCOPE_CROSS_PROJECT, SCOPE_MINE, type DashboardData } from '../api/portal';
import { useDashboard } from './useDashboard';

function stubDashboard(overrides: Partial<DashboardData> = {}) {
  return {
    data: {
      scope: 'mine',
      scope_requested: 'mine',
      scope_downgraded: false,
      can_cross_project: false,
      generated_at: '2026-08-10T00:00:00Z',
      projects: { total: 0, items: [] },
      my_work: {
        pending_requirement_reviews: { count: 0, items: [] },
        my_open_defects: { count: 0, items: [] },
        pending_test_executions: { count: 0, items: [] },
        pending_workflow_approvals: { count: 0, items: [] },
      },
      requirement_stats: { total: 0, by_status: {}, baseline_total: 0 },
      tp_stats: { case_total: 0, plan_total: 0, execution_total: 0, execution_by_status: {}, pass_rate: null },
      td_stats: { total: 0, by_status: {}, by_severity: {}, sla_breached: 0 },
      recent_activities: { source: 'notification', items: [] },
      degraded: [],
      ...overrides,
    },
    meta: { trace_id: 't', took_ms: 1 },
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  const apiMock = api as unknown as ReturnType<typeof vi.fn>;
  apiMock.mockImplementation(async (path: string) => {
    const match = /scope=([\w-]+)/.exec(path);
    const requested = match?.[1] ?? 'mine';
    if (path.includes('/bff/api/portal/dashboard')) {
      return stubDashboard({
        scope: requested as DashboardData['scope'],
        scope_requested: requested as DashboardData['scope'],
        can_cross_project: requested === 'cross-project',
      });
    }
    return { data: { principal: { id: 'u', permissions: [] } } };
  });
});

describe('useDashboard', () => {
  it('loads data and starts in idle then ready', async () => {
    const auth = useAuthStore();
    auth.principal = { id: 'u', username: 'u', display_name: 'U', permissions: [], break_glass: false };
    const dash = useDashboard();
    expect(dash.status.value).toBe('idle');

    await dash.refresh();
    expect(dash.status.value).toBe('ready');
    expect(dash.data.value?.scope).toBe('mine');
    expect(dash.isInitialLoading.value).toBe(false);
  });

  it('detects a degraded domain', async () => {
    const auth = useAuthStore();
    auth.principal = { id: 'u', username: 'u', display_name: 'U', permissions: [], break_glass: false };
    const apiMock = api as unknown as ReturnType<typeof vi.fn>;
    apiMock.mockImplementation(async (path: string) =>
      path.includes('/bff/api/portal/dashboard')
        ? stubDashboard({ degraded: [{ domain: 'tp', reason: 'UPSTREAM_TIMEOUT' }] })
        : { data: { principal: { id: 'u', permissions: [] } } },
    );
    const dash = useDashboard();
    await dash.refresh();
    expect(dash.isDegraded('tp')).toBe(true);
    expect(dash.isDegraded('td')).toBe(false);
  });

  it('adopts the authoritative scope and capability from the backend', async () => {
    const auth = useAuthStore();
    auth.principal = { id: 'u', username: 'u', display_name: 'U', permissions: [], break_glass: false };
    const dash = useDashboard(SCOPE_MINE);
    await dash.setScope(SCOPE_CROSS_PROJECT);
    expect(dash.scope.value).toBe('cross-project');
    expect(dash.canCrossProject.value).toBe(true);
  });

  it('keeps stale data on a background poll failure (no error escalation)', async () => {
    const auth = useAuthStore();
    auth.principal = { id: 'u', username: 'u', display_name: 'U', permissions: [], break_glass: false };
    const apiMock = api as unknown as ReturnType<typeof vi.fn>;
    const dash = useDashboard();
    await dash.refresh();
    expect(dash.status.value).toBe('ready');

    apiMock.mockRejectedValueOnce(new Error('network'));
    await dash.refresh();
    expect(dash.status.value).toBe('ready');
    expect(dash.data.value).not.toBeNull();
    expect(dash.error.value).not.toBeNull();
  });
});
