import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * TestCaseDetail — version history + version-detail drill-down.
 *
 * The transport layer is mocked at the domain-module boundary so we can both
 * control responses AND assert the exact functions the component calls. As in the
 * existing `TestCaseList.test.ts`, Vuetify is intentionally NOT registered in this
 * harness, so `v-*` tags render as raw custom elements; we assert against tag
 * selectors (`v-list-item`) and text content instead of Vuetify-rendered classes
 * (`.v-list-item`) / `<td>`.
 */
vi.mock('../../api/testcases', () => ({
  getTestCase: vi.fn(),
  createTestCaseVersion: vi.fn(),
  listCaseVersions: vi.fn(),
  getCaseVersion: vi.fn(),
}));

import { getTestCase, listCaseVersions, getCaseVersion } from '../../api/testcases';
import type { TestCase, TestCaseVersion, TestStep } from '../../api/types/testcase';
import TestCaseDetail from './TestCaseDetail.vue';

const getTestCaseMock = getTestCase as unknown as ReturnType<typeof vi.fn>;
const listCaseVersionsMock = listCaseVersions as unknown as ReturnType<typeof vi.fn>;
const getCaseVersionMock = getCaseVersion as unknown as ReturnType<typeof vi.fn>;

const caseHead: TestCase = {
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
};

const versionList: TestCaseVersion = {
  id: 'v1',
  case_id: 'c1',
  version_no: 1,
  content_hash: 'abc',
  source: 'manual',
  steps: [{ sequence: 1, action: 'A', expected: 'E' }] as TestStep[],
};

const versionDetail: TestCaseVersion = {
  id: 'v1',
  case_id: 'c1',
  version_no: 1,
  content_hash: 'abc',
  source: 'manual',
  steps: [{ sequence: 1, action: 'A', expected: 'E' }] as TestStep[],
};

function mountDetail(open: boolean) {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(TestCaseDetail, {
    props: { modelValue: open, projectId: 'p1', caseId: 'c1' },
    global: { plugins: [pinia] },
  });
}

beforeEach(() => {
  getTestCaseMock.mockReset();
  listCaseVersionsMock.mockReset();
  getCaseVersionMock.mockReset();
  // getTestCase resolves the head directly (the api module unwraps .data).
  getTestCaseMock.mockResolvedValue(caseHead);
  listCaseVersionsMock.mockResolvedValue({
    data: { items: [versionList] },
    meta: { next_cursor: null, has_more: false, trace_id: 't' },
  });
  getCaseVersionMock.mockResolvedValue(versionDetail);
});

describe('TestCaseDetail', () => {
  it('loads the version history when the dialog opens', async () => {
    const wrapper = mountDetail(false);
    await flushPromises();

    // The load is driven by the modelValue watcher, so open it explicitly.
    await wrapper.setProps({ modelValue: true });
    await flushPromises();

    expect(listCaseVersionsMock).toHaveBeenCalledWith('p1', 'c1');
    expect(wrapper.text()).toContain('历史版本');

    // one v-list-item per version (raw custom element in this harness).
    // v1 is carried on the item's `title` attribute (Vuetify renders it via a slot).
    const items = wrapper.findAll('v-list-item');
    expect(items.length).toBe(1);
    expect(items[0].attributes('title')).toContain('v1');
  });

  it('fetches a single version and opens the steps view on click', async () => {
    const wrapper = mountDetail(false);
    await flushPromises();
    await wrapper.setProps({ modelValue: true });
    await flushPromises();

    const item = wrapper.find('v-list-item');
    await item.trigger('click');
    await flushPromises();

    expect(getCaseVersionMock).toHaveBeenCalledWith('p1', 'c1', 'v1');

    // version-detail dialog renders the fetched version's steps (action 'A', expected 'E')
    expect(wrapper.text()).toContain('版本 v1');
    expect(wrapper.text()).toContain('A');
    expect(wrapper.text()).toContain('E');
  });
});
