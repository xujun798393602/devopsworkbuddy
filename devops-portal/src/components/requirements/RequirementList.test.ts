import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// Always mock the transport layer so no real network call is made.
vi.mock('../../api/client', () => ({ api: vi.fn() }));

import { api } from '../../api/client';
import type { ListEnvelope } from '../../api/envelope';
import type { Requirement } from '../../api/types/requirement';
import RequirementList from './RequirementList.vue';

function sample(): Requirement[] {
  return [
    {
      id: 'r1',
      project_id: 'p1',
      business_no: 'REQ-1',
      title: '登录需求',
      type: 'feature',
      status: 'draft',
      priority: 'p1',
      owner_id: 'u',
      release_version_id: '',
      parent_id: null,
      description: '',
      acceptance_criteria: [],
      current_revision: 1,
      baseline_status: 'unbaselined',
      version: 1,
      created_at: null,
      updated_at: null,
    },
    {
      id: 'r2',
      project_id: 'p1',
      business_no: 'REQ-2',
      title: '支付需求',
      type: 'epic',
      status: 'approved',
      priority: 'p0',
      owner_id: 'a',
      release_version_id: '',
      parent_id: null,
      description: '',
      acceptance_criteria: [],
      current_revision: 1,
      baseline_status: 'baselined',
      version: 2,
      created_at: null,
      updated_at: null,
    },
  ];
}

function stub(items: Requirement[], hasMore = false, nextCursor: string | null = null): ListEnvelope<Requirement> {
  return { data: { items }, meta: { next_cursor: nextCursor, has_more: hasMore, trace_id: 't' } };
}

function mountList() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(RequirementList, {
    props: { projectId: 'p1' },
    global: { plugins: [pinia] },
  });
}

const apiMock = api as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string) => {
    if (path.includes('/requirements')) return stub(sample());
    return { data: {} };
  });
});

describe('RequirementList', () => {
  it('lists requirements fetched from the API', async () => {
    const wrapper = mountList();
    await flushPromises();

    expect(apiMock).toHaveBeenCalledWith(
      expect.stringContaining('/bff/api/v1/projects/p1/requirements'),
    );
    expect(wrapper.text()).toContain('登录需求');
    expect(wrapper.text()).toContain('REQ-1');
    expect(wrapper.text()).toContain('新建需求');
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
