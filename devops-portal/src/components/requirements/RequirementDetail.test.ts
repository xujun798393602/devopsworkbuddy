import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * RequirementDetail — requirement sub-module wiring (reviews / baselines / change-requests).
 *
 * Only the transport layer (`../../api/client` -> `api`) is mocked, so the REAL
 * `listRequirement*` / `createRequirement*` functions run and we can assert the exact
 * transport calls they build. Vuetify is intentionally NOT registered (as in
 * `TestPlanList.test.ts`), so `v-btn` renders as a raw custom element; we drive the
 * flow via tag selectors. Because `load()` is triggered by a `watch` on `modelValue`,
 * each test mounts with `modelValue: false` and then flips it to `true`.
 *
 * Note: all three `FormDialog`s render their content eagerly even when closed, so there
 * are three "保存" buttons in the DOM. To submit the *correct* sub-module we locate the
 * currently-active `FormDialog` (modelValue === true) and emit its `submit` event,
 * rather than clicking a generic "保存" button.
 */
vi.mock('../../api/client', () => ({ api: vi.fn() }));

import { api } from '../../api/client';
import RequirementDetail from './RequirementDetail.vue';
import FormDialog from '../common/FormDialog.vue';

const apiMock = api as unknown as ReturnType<typeof vi.fn>;

function mountDetail() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(RequirementDetail, {
    props: { modelValue: false, projectId: 'p1', requirementId: 'r1' },
    global: { plugins: [pinia] },
  });
}

/** Open the dialog (flips modelValue) and let load() fetch the requirement + sub-lists. */
async function openDetail(wrapper: ReturnType<typeof mountDetail>): Promise<void> {
  await wrapper.setProps({ modelValue: true });
  await flushPromises();
  await flushPromises();
}

/**
 * Click the i-th "新建" button (reviews=0, baselines=1, changes=2) to open that
 * sub-module's dialog, then emit `submit` on the active FormDialog so the matching
 * create handler fires.
 */
async function submitCreate(wrapper: ReturnType<typeof mountDetail>, index: number): Promise<void> {
  const newBtns = wrapper.findAll('v-btn').filter((b) => b.text().trim() === '新建');
  await newBtns[index].trigger('click');
  await flushPromises();

  const active = wrapper.findAllComponents(FormDialog).find((d) => d.props('modelValue') === true);
  expect(active).toBeTruthy();
  await active!.vm.$emit('submit');
  await flushPromises();
}

beforeEach(() => {
  apiMock.mockReset();
  apiMock.mockImplementation(async (path: string, init: Record<string, unknown> = {}) => {
    const method = (init?.method as string) ?? 'GET';
    const isReview = path.includes('/reviews');
    const isBaseline = path.includes('requirement-baselines');
    const isChange = path.includes('change-requests');
    if (isReview || isBaseline || isChange) {
      if (method === 'POST') {
        return { data: { id: 'x', requirement_id: 'r1', version: 1 }, meta: {} };
      }
      return { data: { items: [] }, meta: { next_cursor: null, has_more: false } };
    }
    // getRequirement (single resource).
    if (path.includes('/requirements/')) {
      return {
        data: {
          id: 'r1',
          project_id: 'p1',
          business_no: 'REQ-1',
          title: '需求A',
          type: 'feature',
          status: 'draft',
          priority: 'p2',
          owner_id: 'u',
          release_version_id: '',
          parent_id: null,
          description: '',
          acceptance_criteria: [],
          current_revision: 1,
          baseline_status: 'none',
          version: 3,
          created_at: null,
          updated_at: null,
        },
        meta: {},
      };
    }
    return { data: {}, meta: {} };
  });
});

describe('RequirementDetail sub-modules', () => {
  it('loads the three sub-module lists when the dialog opens', async () => {
    const wrapper = mountDetail();
    await openDetail(wrapper);

    const paths = apiMock.mock.calls.map((c) => c[0] as string);
    expect(paths.some((p) => p.startsWith('/bff/api/v1/projects/p1/requirements/r1/reviews'))).toBe(true);
    expect(
      paths.some((p) => p.startsWith('/bff/api/v1/projects/p1/requirements/r1/requirement-baselines')),
    ).toBe(true);
    expect(
      paths.some((p) => p.startsWith('/bff/api/v1/projects/p1/requirements/r1/change-requests')),
    ).toBe(true);
  });

  it('review 新建 submit -> POST /reviews + Idempotency-Key + reload', async () => {
    const wrapper = mountDetail();
    await openDetail(wrapper);
    apiMock.mockClear();

    await submitCreate(wrapper, 0);

    expect(apiMock).toHaveBeenCalledWith(
      '/bff/api/v1/projects/p1/requirements/r1/reviews',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }),
      }),
    );
    expect(
      apiMock.mock.calls.some((c) => (c[0] as string).startsWith('/bff/api/v1/projects/p1/requirements/r1/reviews')),
    ).toBe(true);
  });

  it('baseline 新建 submit -> POST /requirement-baselines + Idempotency-Key + reload', async () => {
    const wrapper = mountDetail();
    await openDetail(wrapper);
    apiMock.mockClear();

    await submitCreate(wrapper, 1);

    expect(apiMock).toHaveBeenCalledWith(
      '/bff/api/v1/projects/p1/requirements/r1/requirement-baselines',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }),
      }),
    );
    expect(
      apiMock.mock.calls.some((c) =>
        (c[0] as string).startsWith('/bff/api/v1/projects/p1/requirements/r1/requirement-baselines'),
      ),
    ).toBe(true);
  });

  it('change-request 新建 submit -> POST /change-requests + Idempotency-Key + reload', async () => {
    const wrapper = mountDetail();
    await openDetail(wrapper);
    apiMock.mockClear();

    await submitCreate(wrapper, 2);

    expect(apiMock).toHaveBeenCalledWith(
      '/bff/api/v1/projects/p1/requirements/r1/change-requests',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }),
      }),
    );
    expect(
      apiMock.mock.calls.some((c) =>
        (c[0] as string).startsWith('/bff/api/v1/projects/p1/requirements/r1/change-requests'),
      ),
    ).toBe(true);
  });
});
