import { beforeEach, describe, expect, it, vi } from 'vitest';

// Always mock the transport layer so no real network call is made.
vi.mock('../api/client', () => ({ api: vi.fn() }));

import { api } from '../api/client';
import type { ListEnvelope } from '../api/envelope';
import type { TestCase, TestPlan, TestCaseVersion } from './types/testcase';
import {
  listTestCases,
  createTestCase,
  createTestCaseVersion,
  createTestPlan,
  listCaseVersions,
  getCaseVersion,
  transitionTestPlan,
} from './testcases';

function sampleCase(): TestCase {
  return {
    id: 'c1',
    project_id: 'p1',
    business_no: 'TC-1',
    folder_id: '',
    title: '用例A',
    owner_id: 'u',
    type: 'functional',
    priority: 'p2',
    status: 'draft',
    automation_mode: 'manual',
    current_version_id: null,
    requirement_refs: [],
    version: 1,
  };
}

function samplePlan(): TestPlan {
  return {
    id: 'pl1',
    project_id: 'p1',
    business_no: 'TP-1',
    owner_id: 'u',
    status: 'draft',
    scope_hash: '',
    version: 1,
    scope: [],
  };
}

function sampleVersion(): TestCaseVersion {
  return {
    id: 'v1',
    case_id: 'c1',
    version_no: 1,
    content_hash: 'abc123',
    source: 'manual',
    steps: [{ sequence: 1, action: 'a', expected: 'e' }],
  };
}

function stubList<T>(items: T[]): ListEnvelope<T> {
  return { data: { items }, meta: { next_cursor: null, has_more: false, trace_id: 't' } };
}

const apiMock = api as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  apiMock.mockReset();
});

describe('testcases api', () => {
  it('listTestCases resolves the cursor envelope from /test-cases', async () => {
    apiMock.mockResolvedValue(stubList([sampleCase()]));
    const res = await listTestCases('p1');
    expect(apiMock).toHaveBeenCalledWith('/bff/api/v1/projects/p1/test-cases?limit=20');
    expect(res.data.items).toHaveLength(1);
    expect(res.meta.has_more).toBe(false);
  });

  it('createTestCase POSTs to /test-cases with an Idempotency-Key', async () => {
    apiMock.mockResolvedValue({ data: sampleCase(), meta: {} });
    await createTestCase('p1', { title: 'x', owner_id: 'u' });
    const [path, init] = apiMock.mock.calls[0];
    expect(path).toBe('/bff/api/v1/projects/p1/test-cases');
    expect(init.method).toBe('POST');
    expect(init.headers['Idempotency-Key']).toBeTruthy();
  });

  it('createTestCaseVersion POSTs steps + source to /versions with Idempotency-Key', async () => {
    apiMock.mockResolvedValue({
      data: { id: 'v1', case_id: 'c1', version_no: 2, content_hash: 'h', source: 'manual', steps: [] },
      meta: {},
    });
    await createTestCaseVersion('p1', 'c1', {
      steps: [{ sequence: 1, action: 'a', expected: 'e' }],
      source: 'manual',
    });
    const [path, init] = apiMock.mock.calls[0];
    expect(path).toBe('/bff/api/v1/projects/p1/test-cases/c1/versions');
    expect(init.method).toBe('POST');
    expect(init.headers['Idempotency-Key']).toBeTruthy();
    const body = JSON.parse(init.body);
    expect(body.steps).toHaveLength(1);
    expect(body.source).toBe('manual');
  });

  it('transitionTestPlan POSTs to /transitions with quoted If-Match + Idempotency-Key', async () => {
    apiMock.mockResolvedValue({ data: samplePlan(), meta: {} });
    await transitionTestPlan('p1', 'pl1', { action: 'freeze' }, 4);
    const [path, init] = apiMock.mock.calls[0];
    expect(path).toBe('/bff/api/v1/projects/p1/test-plans/pl1/transitions');
    expect(init.method).toBe('POST');
    expect(init.headers['If-Match']).toBe('"4"');
    expect(init.headers['Idempotency-Key']).toBeTruthy();
  });

  it('createTestPlan POSTs to /test-plans with an Idempotency-Key', async () => {
    apiMock.mockResolvedValue({ data: samplePlan(), meta: {} });
    await createTestPlan('p1', { owner_id: 'u', business_no: 'TP-2' });
    const [path, init] = apiMock.mock.calls[0];
    expect(path).toBe('/bff/api/v1/projects/p1/test-plans');
    expect(init.method).toBe('POST');
    expect(init.headers['Idempotency-Key']).toBeTruthy();
    const body = JSON.parse(init.body);
    expect(body.owner_id).toBe('u');
    expect(body.business_no).toBe('TP-2');
  });

  it('listCaseVersions resolves the version envelope from /test-cases/{cid}/versions', async () => {
    apiMock.mockResolvedValue(stubList([sampleVersion()]));
    const res = await listCaseVersions('p1', 'c1');
    expect(apiMock).toHaveBeenCalledWith('/bff/api/v1/projects/p1/test-cases/c1/versions?limit=20');
    expect(res.data.items).toHaveLength(1);
    expect(res.data.items[0].version_no).toBe(1);
  });

  it('getCaseVersion GETs a single version from /versions/{vid}', async () => {
    apiMock.mockResolvedValue({ data: sampleVersion(), meta: {} });
    const v = await getCaseVersion('p1', 'c1', 'v1');
    expect(apiMock).toHaveBeenCalledWith('/bff/api/v1/projects/p1/test-cases/c1/versions/v1');
    expect(v.id).toBe('v1');
    expect(v.steps).toHaveLength(1);
  });
});
