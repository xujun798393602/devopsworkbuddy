import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Always mock the transport layer so no real network call is made.
vi.mock('../../api/client', () => ({ api: vi.fn() }));

import { api } from '../../api/client';
import type { ListEnvelope } from '../../api/envelope';
import type { Defect } from '../../api/types/defect';
import DefectList from './DefectList.vue';

function sampleDefects(): Defect[] {
  return [
    {
      id: 'd1',
      project_id: 'p1',
      business_no: 'TD-1',
      title: '登录崩溃',
      description: '',
      severity: 'blocker',
      priority: 'p0',
      defect_type: 'functional',
      status: 'new',
      reporter_id: 'u',
      assignee_id: null,
      verifier_id: null,
      reopen_count: 0,
      version: 1,
      sla: null,
    },
    {
      id: 'd2',
      project_id: 'p1',
      business_no: 'TD-2',
      title: '支付超时',
      description: '',
      severity: 'major',
      priority: 'p2',
      defect_type: 'performance',
      status: 'in_progress',
      reporter_id: 'u',
      assignee_id: 'a',
      verifier_id: null,
      reopen_count: 0,
      version: 3,
      sla: null,
    },
  ];
}

function stubDefects(
  items: Defect[],
  hasMore = false,
  nextCursor: string | null = null,
): ListEnvelope<Defect> {
  return { data: { items }, meta: { next_cursor: nextCursor, has_more: hasMore, trace_id: 't' } };
}

function mountList() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(DefectList, {
    props: { projectId: 'p1' },
    global: { plugins: [pinia] },
  });
}

const apiMock = api as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) => {
    if (path.includes('/defects')) return stubDefects(sampleDefects());
    return { data: {} };
  });
});

describe('DefectList', () => {
  it('lists defects fetched from the API', async () => {
    const wrapper = mountList();
    await flushPromises();

    expect(apiMock).toHaveBeenCalledWith(
      expect.stringContaining('/bff/api/v1/projects/p1/defects'),
    );
    expect(wrapper.text()).toContain('登录崩溃');
    expect(wrapper.text()).toContain('TD-1');
    expect(wrapper.text()).toContain('新建缺陷');
  });

  it('loads the next page when "加载更多" is clicked', async () => {
    apiMock.mockImplementation(async (path: string) => {
      if (path.includes('/defects')) return stubDefects(sampleDefects(), true, 'c2');
      return { data: {} };
    });

    const wrapper = mountList();
    await flushPromises();
    expect(apiMock).toHaveBeenCalledTimes(1);

    const moreBtn = wrapper.find('.defect-list__more v-btn');
    expect(moreBtn.exists()).toBe(true);

    await moreBtn.trigger('click');
    await flushPromises();

    expect(apiMock).toHaveBeenLastCalledWith(
      expect.stringContaining('cursor=c2'),
    );
  });

  it('renders an error alert when the first load fails', async () => {
    apiMock.mockImplementation(async () => {
      throw new Error('网关异常');
    });

    const wrapper = mountList();
    await flushPromises();

    const alert = wrapper.find('[role="alert"]');
    expect(alert.exists()).toBe(true);
    expect(alert.text()).toContain('网关异常');
  });
});
