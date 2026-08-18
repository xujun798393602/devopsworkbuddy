import { beforeEach, describe, expect, it, vi } from 'vitest';

// Always mock the transport layer so no real network call is made.
vi.mock('../api/client', () => ({ api: vi.fn() }));

import { api } from '../api/client';
import type { ListEnvelope } from '../api/envelope';
import type { Requirement } from './types/requirement';
import {
  listRequirements,
  getRequirement,
  createRequirement,
  updateRequirement,
  transitionRequirement,
} from './requirements';

function sampleRequirement(): Requirement {
  return {
    id: 'r1',
    project_id: 'p1',
    business_no: 'REQ-1',
    title: '需求A',
    type: 'feature',
    status: 'draft',
    priority: 'p1',
    owner_id: 'u1',
    release_version_id: '',
    parent_id: null,
    description: '',
    acceptance_criteria: [],
    current_revision: 1,
    baseline_status: 'unbaselined',
    version: 2,
    created_at: null,
    updated_at: null,
  };
}

function stubList(items: Requirement[], hasMore = false, nextCursor: string | null = null): ListEnvelope<Requirement> {
  return { data: { items }, meta: { next_cursor: nextCursor, has_more: hasMore, trace_id: 't' } };
}

const apiMock = api as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  apiMock.mockReset();
});

describe('requirements api', () => {
  it('listRequirements resolves the cursor envelope (data.items + meta)', async () => {
    apiMock.mockResolvedValue(stubList([sampleRequirement()], true, 'c2'));
    const res = await listRequirements('p1', 20, null);
    expect(apiMock).toHaveBeenCalledWith('/bff/api/v1/projects/p1/requirements?limit=20');
    expect(res.data.items).toHaveLength(1);
    expect(res.meta.has_more).toBe(true);
    expect(res.meta.next_cursor).toBe('c2');
  });

  it('getRequirement returns the requirement body; version is read from data', async () => {
    apiMock.mockResolvedValue({ data: sampleRequirement(), meta: {} });
    const req = await getRequirement('p1', 'r1');
    expect(apiMock).toHaveBeenCalledWith('/bff/api/v1/projects/p1/requirements/r1');
    expect(req.id).toBe('r1');
    // Concurrency token comes from the body (the gateway drops the ETag header).
    expect(req.version).toBe(2);
  });

  it('createRequirement POSTs and attaches an Idempotency-Key', async () => {
    apiMock.mockResolvedValue({ data: sampleRequirement(), meta: {} });
    await createRequirement('p1', { title: 'x', type: 'feature', owner_id: 'u', release_version_id: '' });
    const [path, init] = apiMock.mock.calls[0];
    expect(path).toBe('/bff/api/v1/projects/p1/requirements');
    expect(init.method).toBe('POST');
    expect(init.headers['Idempotency-Key']).toBeTruthy();
  });

  it('updateRequirement PATCHes with the quoted If-Match header', async () => {
    apiMock.mockResolvedValue({ data: sampleRequirement(), meta: {} });
    await updateRequirement('p1', 'r1', { title: 'y' }, 3);
    const [path, init] = apiMock.mock.calls[0];
    expect(path).toBe('/bff/api/v1/projects/p1/requirements/r1');
    expect(init.method).toBe('PATCH');
    // The api module quotes the version: If-Match: "3". A bare 3 would 412.
    expect(init.headers['If-Match']).toBe('"3"');
    expect(init.headers['Idempotency-Key']).toBeTruthy();
  });

  it('transitionRequirement POSTs to /transitions with If-Match quoted', async () => {
    apiMock.mockResolvedValue({ data: sampleRequirement(), meta: {} });
    await transitionRequirement('p1', 'r1', { action: 'submit_review' }, 5);
    const [path, init] = apiMock.mock.calls[0];
    expect(path).toBe('/bff/api/v1/projects/p1/requirements/r1/transitions');
    expect(init.method).toBe('POST');
    expect(init.headers['If-Match']).toBe('"5"');
    expect(init.headers['Idempotency-Key']).toBeTruthy();
  });
});
