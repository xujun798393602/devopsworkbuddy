/**
 * Requirement domain API.
 *
 * Contracts verified against requirement-service real sources:
 *  - list       `GET  /projects/{pid}/requirements`        → `{ data:{items}, meta:{next_cursor,has_more} }`
 *  - get        `GET  /projects/{pid}/requirements/{id}`    → `{ data: Requirement, meta }`
 *  - create     `POST /projects/{pid}/requirements`         → `{ data: Requirement, meta }`
 *               requires `Idempotency-Key`.
 *  - patch      `PATCH /projects/{pid}/requirements/{id}`    → `{ data: Requirement, meta }`
 *               requires `If-Match: "<version>"` (app.py quotes the version).
 *  - transition `POST /projects/{pid}/requirements/{id}/transitions`
 *               requires `Idempotency-Key` + `If-Match: "<version>"`.
 *  - reviews        `GET/POST /projects/{pid}/requirements/{id}/reviews`
 *               → `{ data:{items}, meta }` (list) / `{ data: RequirementReview, meta }` (single).
 *               POST requires `Idempotency-Key`.
 *  - baselines      `GET/POST /projects/{pid}/requirements/{id}/requirement-baselines`
 *               → `{ data:{items}, meta }` / `{ data: RequirementBaseline, meta }`.
 *  - change reqs    `GET/POST /projects/{pid}/requirements/{id}/change-requests`
 *               → `{ data:{items}, meta }` / `{ data: ChangeRequest, meta }`.
 *
 * Always go through `api<T>()` (never a raw `fetch`) so CSRF / 401-refresh /
 * replay are handled uniformly.
 */
import { api } from './client';
import { projectPath, cursorSearch, ifMatchHeaders, idempotencyHeaders, type Envelope, type ListEnvelope } from './envelope';
import type {
  Requirement,
  CreateRequirementRequest,
  UpdateRequirementRequest,
  RequirementTransitionRequest,
  RequirementReview,
  CreateRequirementReviewRequest,
  RequirementBaseline,
  CreateRequirementBaselineRequest,
  ChangeRequest,
  CreateChangeRequestRequest,
} from './types/requirement';

/** Cursor-paginated requirement list for a project. */
export async function listRequirements(
  projectId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<Requirement>> {
  return api<ListEnvelope<Requirement>>(
    projectPath(projectId, `/requirements${cursorSearch({ limit, cursor })}`),
  );
}

/** Fetch a single requirement. */
export async function getRequirement(projectId: string, requirementId: string): Promise<Requirement> {
  const response = await api<Envelope<Requirement>>(
    projectPath(projectId, `/requirements/${requirementId}`),
  );
  return response.data;
}

/** Create a requirement (idempotent via `Idempotency-Key`). */
export async function createRequirement(
  projectId: string,
  payload: CreateRequirementRequest,
  idempotencyKey?: string,
): Promise<Requirement> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<Requirement>>(projectPath(projectId, '/requirements'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(payload),
  });
  return response.data;
}

/**
 * Patch a requirement under optimistic concurrency. `version` becomes the
 * quoted `If-Match` header (backend compares literally against `"<version>"`).
 */
export async function updateRequirement(
  projectId: string,
  requirementId: string,
  payload: UpdateRequirementRequest,
  version: number,
  idempotencyKey?: string,
): Promise<Requirement> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<Requirement>>(
    projectPath(projectId, `/requirements/${requirementId}`),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...ifMatchHeaders(version) },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}

/** Apply one explicit lifecycle action under optimistic concurrency. */
export async function transitionRequirement(
  projectId: string,
  requirementId: string,
  payload: RequirementTransitionRequest,
  version: number,
  idempotencyKey?: string,
): Promise<Requirement> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<Requirement>>(
    projectPath(projectId, `/requirements/${requirementId}/transitions`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...ifMatchHeaders(version) },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}

/**
 * Requirement sub-module API: reviews / baselines / change-requests.
 *
 * Every sub-module shares the same contract with the requirement list itself:
 *  - list  → `GET {sub}/…`            returns the raw `ListEnvelope` (`{ data:{items}, meta }`).
 *  - create → `POST {sub}/…`          idempotent via `Idempotency-Key`; returns `response.data`.
 * Consumers paginate with `toPage()` or read `.data.items` directly.
 */

/** Cursor-paginated review list for a requirement. */
export async function listRequirementReviews(
  projectId: string,
  requirementId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<RequirementReview>> {
  return api<ListEnvelope<RequirementReview>>(
    projectPath(projectId, `/requirements/${requirementId}/reviews${cursorSearch({ limit, cursor })}`),
  );
}

/** Create a requirement review (idempotent via `Idempotency-Key`). */
export async function createRequirementReview(
  projectId: string,
  requirementId: string,
  payload: CreateRequirementReviewRequest,
  idempotencyKey?: string,
): Promise<RequirementReview> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<RequirementReview>>(
    projectPath(projectId, `/requirements/${requirementId}/reviews`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...idempotencyHeaders(key) },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}

/** Cursor-paginated baseline list for a requirement. */
export async function listRequirementBaselines(
  projectId: string,
  requirementId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<RequirementBaseline>> {
  return api<ListEnvelope<RequirementBaseline>>(
    projectPath(projectId, `/requirements/${requirementId}/requirement-baselines${cursorSearch({ limit, cursor })}`),
  );
}

/** Create a requirement baseline (idempotent via `Idempotency-Key`). */
export async function createRequirementBaseline(
  projectId: string,
  requirementId: string,
  payload: CreateRequirementBaselineRequest,
  idempotencyKey?: string,
): Promise<RequirementBaseline> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<RequirementBaseline>>(
    projectPath(projectId, `/requirements/${requirementId}/requirement-baselines`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...idempotencyHeaders(key) },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}

/** Cursor-paginated change-request list for a requirement. */
export async function listChangeRequests(
  projectId: string,
  requirementId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<ChangeRequest>> {
  return api<ListEnvelope<ChangeRequest>>(
    projectPath(projectId, `/requirements/${requirementId}/change-requests${cursorSearch({ limit, cursor })}`),
  );
}

/** Create a change request (idempotent via `Idempotency-Key`). */
export async function createChangeRequest(
  projectId: string,
  requirementId: string,
  payload: CreateChangeRequestRequest,
  idempotencyKey?: string,
): Promise<ChangeRequest> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<ChangeRequest>>(
    projectPath(projectId, `/requirements/${requirementId}/change-requests`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...idempotencyHeaders(key) },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}
