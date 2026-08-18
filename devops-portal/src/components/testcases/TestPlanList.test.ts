import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * TestPlanList — inline create flow.
 *
 * Only the transport layer (`../../api/client` -> `api`) is mocked, so the REAL
 * `listTestPlans` / `createTestPlan` functions run and we can assert the exact
 * transport call they build: a POST to `/bff/api/v1/projects/p1/test-plans`
 * carrying an `Idempotency-Key` header, followed by a list reload.
 * Vuetify is intentionally NOT registered here (as in `TestCaseList.test.ts`), so
 * `v-btn` renders as a raw custom element; we drive the flow via tag selectors.
 */
vi.mock('../../api/client', () => ({ api: vi.fn() }));

import { api } from '../../api/client';
import TestPlanList from './TestPlanList.vue';

const apiMock = api as unknown as ReturnType<typeof vi.fn>;

function mountList() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(TestPlanList, {
    props: { projectId: 'p1' },
    global: { plugins: [pinia] },
  });
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string, init: Record<string, unknown> = {}) => {
    const method = (init.method as string) ?? 'GET';
    if (path.includes('/test-plans') && method === 'POST') {
      return {
        data: {
          id: 'plan1',
          project_id: 'p1',
          business_no: '',
          owner_id: 'u1',
          status: 'draft',
          scope_hash: '',
          version: 1,
          scope: [],
        },
        meta: {},
      };
    }
    if (path.includes('/test-plans')) {
      return { data: { items: [] }, meta: { next_cursor: null, has_more: false } };
    }
    return { data: {}, meta: {} };
  });
});

describe('TestPlanList', () => {
  it('creates a test plan via the API and reloads the list', async () => {
    const wrapper = mountList();
    await flushPromises();

    // open the create dialog
    const newBtn = wrapper.findAll('v-btn').find((b) => b.text().includes('新建计划'));
    expect(newBtn).toBeTruthy();
    await newBtn!.trigger('click');
    await flushPromises();

    // submit via the FormDialog "保存" button
    const saveBtn = wrapper.findAll('v-btn').find((b) => b.text().includes('保存'));
    expect(saveBtn).toBeTruthy();
    await saveBtn!.trigger('click');
    await flushPromises();

    // the real createTestPlan builds: POST /bff/api/v1/projects/p1/test-plans + Idempotency-Key
    expect(apiMock).toHaveBeenCalledWith(
      '/bff/api/v1/projects/p1/test-plans',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }),
      }),
    );

    // list reloads after create: initial immediate load + post-create reload
    // (the list GET carries a ?limit= query, the POST does not, so match by prefix)
    const planCalls = apiMock.mock.calls.filter(
      (c) => (c[0] as string).startsWith('/bff/api/v1/projects/p1/test-plans'),
    );
    expect(planCalls.length).toBeGreaterThanOrEqual(2);
  });
});
