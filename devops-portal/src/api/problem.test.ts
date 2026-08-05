import { describe, expect, it } from 'vitest';

import { ApiProblem, type ProblemDetails } from './problem';

describe('ApiProblem', () => {
  it('preserves RFC 9457 fields for presentation', () => {
    const details: ProblemDetails = {
      type: 'about:blank',
      title: 'PERMISSION_DENIED',
      status: 403,
      detail: 'Permission denied',
      error_code: 'PERMISSION_DENIED',
      trace_id: 'trace-1',
    };
    const error = new ApiProblem(details);
    expect(error.message).toBe('Permission denied');
    expect(error.problem.trace_id).toBe('trace-1');
  });
});
