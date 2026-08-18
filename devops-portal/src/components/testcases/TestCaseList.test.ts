import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Always mock the transport layer so no real network call is made.
vi.mock('../../api/client', () => ({ api: vi.fn() }));

import { api } from '../../api/client';
import type { ListEnvelope } from '../../api/envelope';
import type { TestCase } from '../../api/types/testcase';
import TestCaseList from './TestCaseList.vue';

function sample(): TestCase[] {
  return [
    {
      id: 'c1',
      project_id: 'p1',
      business_no: 'TC-1',
      folder_id: '',
      title: '登录用例',
      owner_id: 'u',
      type: 'functional',
      priority: 'p2',
      status: 'draft',
      automation_mode: 'manual',
      current_version_id: null,
      requirement_refs: [],
      version: 1,
    },
    {
      id: 'c2',
      project_id: 'p1',
      business_no: 'TC-2',
      folder_id: '',
      title: '支付用例',
      owner_id: 'a',
      type: 'api',
      priority: 'p0',
      status: 'active',
      automation_mode: 'automated',
      current_version_id: 'v2',
      requirement_refs: ['r1'],
      version: 2,
    },
  ];
}

function stub(items: TestCase[], hasMore = false, nextCursor: string | null = null): ListEnvelope<TestCase> {
  return { data: { items }, meta: { next_cursor: nextCursor, has_more: hasMore, trace_id: 't' } };
}

function mountList() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(TestCaseList, {
    props: { projectId: 'p1' },
    global: { plugins: [pinia] },
  });
}

const apiMock = api as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) => {
    if (path.includes('/test-cases')) return stub(sample());
    return { data: {} };
  });
});

describe('TestCaseList', () => {
  it('lists test cases fetched from the API', async () => {
    const wrapper = mountList();
    await flushPromises();

    expect(apiMock).toHaveBeenCalledWith(
      expect.stringContaining('/bff/api/v1/projects/p1/test-cases'),
    );
    expect(wrapper.text()).toContain('登录用例');
    expect(wrapper.text()).toContain('TC-1');
    expect(wrapper.text()).toContain('新建用例');
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
