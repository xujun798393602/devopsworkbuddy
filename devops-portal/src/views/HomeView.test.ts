import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ api: vi.fn() }));

import { api } from '../api/client';
import { PERMISSION_CROSS_PROJECT_VIEW, type DashboardData } from '../api/portal';
import { useAuthStore } from '../stores/auth';
import HomeView from './HomeView.vue';

/** Authoritative capability echoed by the fake gateway; per-test overridable. */
let canCrossProject = false;

function stubDashboard(overrides: Partial<DashboardData> = {}) {
  return {
    data: {
      scope: 'mine',
      scope_requested: 'mine',
      scope_downgraded: false,
      can_cross_project: false,
      generated_at: '2026-08-10T00:00:00Z',
      projects: {
        total: 1,
        items: [
          {
            id: 'p1',
            business_no: 'PRJ-1',
            name: '支付中台',
            status: 'active',
            progress_percent: 50,
            current_iteration: null,
            current_version: null,
            my_open_task_count: 2,
          },
        ],
      },
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

function mountHome(permissions: string[] = []) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.principal = { id: 'u', username: 'u', display_name: 'U', permissions, break_glass: false };
  return mount(HomeView, { global: { plugins: [pinia] } });
}

beforeEach(() => {
  canCrossProject = false;
  const apiMock = api as unknown as ReturnType<typeof vi.fn>;
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) => {
    if (path.includes('/bff/api/portal/dashboard')) {
      const requested = (/scope=([\w-]+)/.exec(path)?.[1] ?? 'mine') as DashboardData['scope'];
      return stubDashboard({
        scope: requested,
        scope_requested: requested,
        can_cross_project: canCrossProject,
      });
    }
    return { data: { principal: { id: 'u', permissions: [] } } };
  });
});

describe('HomeView', () => {
  it('fetches the dashboard and renders project cards', async () => {
    const wrapper = mountHome();
    await flushPromises();

    expect(api).toHaveBeenCalledWith('/bff/api/portal/dashboard?scope=mine');
    expect(wrapper.text()).toContain('驾驶舱');
    expect(wrapper.text()).toContain('支付中台');
    // Every card in the family renders, even when its domain block is empty.
    expect(wrapper.findAll('.dcard').length).toBeGreaterThanOrEqual(6);
  });

  it('defaults to cross-project scope and shows the toggle for permitted users', async () => {
    canCrossProject = true;
    const wrapper = mountHome([PERMISSION_CROSS_PROJECT_VIEW]);
    await flushPromises();

    expect(api).toHaveBeenCalledWith('/bff/api/portal/dashboard?scope=cross-project');
    const buttons = wrapper.findAll('.segmented__btn');
    expect(buttons).toHaveLength(2);
    expect(buttons[1].text()).toBe('全平台');
    expect(buttons[1].attributes('aria-pressed')).toBe('true');
    expect(buttons[0].attributes('aria-pressed')).toBe('false');
  });

  it('refetches when the user switches scope', async () => {
    canCrossProject = true;
    const wrapper = mountHome([PERMISSION_CROSS_PROJECT_VIEW]);
    await flushPromises();

    await wrapper.findAll('.segmented__btn')[0].trigger('click');
    await flushPromises();

    expect(api).toHaveBeenLastCalledWith('/bff/api/portal/dashboard?scope=mine');
    expect(wrapper.findAll('.segmented__btn')[0].attributes('aria-pressed')).toBe('true');
  });

  it('hides the cross-project toggle when the user lacks permission', async () => {
    const wrapper = mountHome();
    await flushPromises();

    expect(wrapper.find('.segmented').exists()).toBe(false);
    expect(wrapper.find('.home__scope-static').text()).toBe('我的项目');
    expect(wrapper.text()).not.toContain('全平台');
  });

  it('shows a degradation note when a domain is down', async () => {
    const apiMock = api as unknown as ReturnType<typeof vi.fn>;
    apiMock.mockImplementation(async (path: string) => {
      if (path.includes('/bff/api/portal/dashboard')) {
        return stubDashboard({
          degraded: [{ domain: 'tp', reason: 'UPSTREAM_TIMEOUT' }],
          tp_stats: {
            case_total: 10,
            plan_total: 2,
            execution_total: 4,
            execution_by_status: { passed: 3, failed: 1 },
            pass_rate: 0.75,
          },
        });
      }
      return { data: { principal: { id: 'u', permissions: [] } } };
    });

    const wrapper = mountHome();
    await flushPromises();

    // A tp outage degrades exactly the two tp-derived cards; every other card
    // — and the page as a whole — keeps rendering its data.
    const degradedTitles = wrapper
      .findAll('.dcard--degraded')
      .map((card) => card.find('.dcard__title').text());
    expect(degradedTitles).toEqual(['测试统计', '待执行用例']);

    const tpCard = wrapper.findAll('.dcard--degraded')[0];
    expect(tpCard.find('.dcard__badge').text()).toBe('降级');
    expect(tpCard.find('.dcard__fallback-text').text()).toBe('该模块数据暂不可用');
    expect(wrapper.text()).toContain('支付中台');
  });

  it('surfaces a notice when the gateway downgraded the scope', async () => {
    const apiMock = api as unknown as ReturnType<typeof vi.fn>;
    apiMock.mockImplementation(async () =>
      stubDashboard({ scope: 'mine', scope_requested: 'cross-project', scope_downgraded: true }),
    );

    const wrapper = mountHome([PERMISSION_CROSS_PROJECT_VIEW]);
    await flushPromises();

    expect(wrapper.find('.home__notice').text()).toContain('已切换为「我的项目」视图');
    // The gateway is authoritative: the toggle disappears once it says no.
    expect(wrapper.find('.segmented').exists()).toBe(false);
  });

  it('renders a page-level error when the first load fails', async () => {
    const apiMock = api as unknown as ReturnType<typeof vi.fn>;
    apiMock.mockImplementation(async () => {
      throw new Error('gateway down');
    });

    const wrapper = mountHome();
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain('驾驶舱数据加载失败');
  });
});
