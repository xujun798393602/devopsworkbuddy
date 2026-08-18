import { describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ api: vi.fn() }));

import { api } from '../api/client';
import {
  fetchDashboard,
  PERMISSION_CROSS_PROJECT_VIEW,
  SCOPE_CROSS_PROJECT,
  SCOPE_MINE,
} from './portal';

describe('portal api', () => {
  it('centralises the cross-project permission and scope literals', () => {
    expect(PERMISSION_CROSS_PROJECT_VIEW).toBe('portal:cross-project-view');
    expect(SCOPE_MINE).toBe('mine');
    expect(SCOPE_CROSS_PROJECT).toBe('cross-project');
  });

  it('requests the dashboard endpoint with the requested scope', async () => {
    const apiMock = api as unknown as ReturnType<typeof vi.fn>;
    apiMock.mockResolvedValue({ data: { scope: 'mine', degraded: [] } });

    const result = await fetchDashboard(SCOPE_MINE);

    expect(apiMock).toHaveBeenCalledWith('/bff/api/portal/dashboard?scope=mine');
    expect(result).toEqual({ scope: 'mine', degraded: [] });
  });

  it('passes the cross-project scope verbatim', async () => {
    const apiMock = api as unknown as ReturnType<typeof vi.fn>;
    apiMock.mockResolvedValue({ data: { scope: 'cross-project', degraded: [] } });

    const result = await fetchDashboard(SCOPE_CROSS_PROJECT);

    expect(apiMock).toHaveBeenCalledWith('/bff/api/portal/dashboard?scope=cross-project');
    expect(result.scope).toBe('cross-project');
  });
});
