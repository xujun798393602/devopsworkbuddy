/**
 * Test-case / test-plan domain API.  (Types + thin API surface; the
 * requirement/use-case view wiring is owned by a second engineer.)
 *
 * Contracts verified against tp-service real sources (tp_service/app.py,
 * service.py, domain.py):
 *  - list cases  `GET  /projects/{pid}/test-cases`            → `{ data:{items}, meta:{next_cursor,has_more} }`
 *  - get case     `GET  /projects/{pid}/test-cases/{id}`        → `{ data: TestCase, meta }`
 *  - create case  `POST /projects/{pid}/test-cases`             → `{ data: TestCase, meta }`
 *                 requires `Idempotency-Key`.
 *  - case version `POST /projects/{pid}/test-cases/{id}/versions`
 *  - create plan  `POST /projects/{pid}/test-plans`             → `{ data: TestPlan, meta }`
 *                 requires `Idempotency-Key`.
 *  - list plans   `GET  /projects/{pid}/test-plans`            → `{ data:{items}, meta:{next_cursor,has_more} }`
 *  - get plan     `GET  /projects/{pid}/test-plans/{id}`        → `{ data: TestPlan, meta }`
 *  - plan trans.  `POST /projects/{pid}/test-plans/{id}/transitions`
 *                 requires `Idempotency-Key` + `If-Match: "<version>"`.
 *  - list versions `GET /projects/{pid}/test-cases/{cid}/versions`
 *                → `{ data:{items}, meta:{trace_id} }` (no pagination markers).
 *  - get version  `GET /projects/{pid}/test-cases/{cid}/versions/{vid}`
 *                → `{ data: TestCaseVersion, meta }`.
 */
import { api } from './client';
import { projectPath, cursorSearch, ifMatchHeaders, type Envelope, type ListEnvelope } from './envelope';
import type {
  TestCase,
  CreateTestCaseRequest,
  CreateTestCaseVersionRequest,
  CreateTestPlanRequest,
  TestCaseVersion,
  TestPlan,
  TestPlanTransitionRequest,
} from './types/testcase';

/** Cursor-paginated test-case list for a project. */
export async function listTestCases(
  projectId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<TestCase>> {
  return api<ListEnvelope<TestCase>>(projectPath(projectId, `/test-cases${cursorSearch({ limit, cursor })}`));
}

/** Fetch a single test case. */
export async function getTestCase(projectId: string, caseId: string): Promise<TestCase> {
  const response = await api<Envelope<TestCase>>(projectPath(projectId, `/test-cases/${caseId}`));
  return response.data;
}

/**
 * Immutable-version list for a test case.
 *
 * tp-service `list_case_versions_route` returns `{ data:{items}, meta:{trace_id} }`
 * with NO pagination markers (the backend returns every version and ignores
 * `limit`/`cursor`). Consumers therefore treat it as a single finite page
 * (`meta.next_cursor`/`has_more` resolve to `null`/`false` via `??` guards).
 */
export async function listCaseVersions(
  projectId: string,
  caseId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<TestCaseVersion>> {
  return api<ListEnvelope<TestCaseVersion>>(
    projectPath(projectId, `/test-cases/${caseId}/versions${cursorSearch({ limit, cursor })}`),
  );
}

/** Fetch a single immutable case version. */
export async function getCaseVersion(
  projectId: string,
  caseId: string,
  versionId: string,
): Promise<TestCaseVersion> {
  const response = await api<Envelope<TestCaseVersion>>(
    projectPath(projectId, `/test-cases/${caseId}/versions/${versionId}`),
  );
  return response.data;
}

/** Create a test case (idempotent via `Idempotency-Key`). */
export async function createTestCase(
  projectId: string,
  payload: CreateTestCaseRequest,
  idempotencyKey?: string,
): Promise<TestCase> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<TestCase>>(projectPath(projectId, '/test-cases'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(payload),
  });
  return response.data;
}

/** Create (and publish) an immutable version of a test case. */
export async function createTestCaseVersion(
  projectId: string,
  caseId: string,
  payload: CreateTestCaseVersionRequest,
  idempotencyKey?: string,
): Promise<TestCaseVersion> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<TestCaseVersion>>(
    projectPath(projectId, `/test-cases/${caseId}/versions`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}

/** Create a test plan (idempotent via `Idempotency-Key`). */
export async function createTestPlan(
  projectId: string,
  payload: CreateTestPlanRequest,
  idempotencyKey?: string,
): Promise<TestPlan> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<TestPlan>>(projectPath(projectId, '/test-plans'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(payload),
  });
  return response.data;
}

/** Cursor-paginated test-plan list for a project. */
export async function listTestPlans(
  projectId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<TestPlan>> {
  return api<ListEnvelope<TestPlan>>(projectPath(projectId, `/test-plans${cursorSearch({ limit, cursor })}`));
}

/** Fetch a single test plan. */
export async function getTestPlan(projectId: string, planId: string): Promise<TestPlan> {
  const response = await api<Envelope<TestPlan>>(projectPath(projectId, `/test-plans/${planId}`));
  return response.data;
}

/** Apply one explicit plan lifecycle action under optimistic concurrency. */
export async function transitionTestPlan(
  projectId: string,
  planId: string,
  payload: TestPlanTransitionRequest,
  version: number,
  idempotencyKey?: string,
): Promise<TestPlan> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<TestPlan>>(
    projectPath(projectId, `/test-plans/${planId}/transitions`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...ifMatchHeaders(version) },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}
