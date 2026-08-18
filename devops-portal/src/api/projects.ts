/**
 * Project domain API.
 *
 * Contracts verified against project-service/src/project_service/projects/api.py:
 *  - list   `GET  /api/v1/projects`           → `{ data: Project[],             meta }`
 *  - get    `GET  /api/v1/projects/{id}`       → `{ data: Project,             meta }`
 *  - create `POST /api/v1/projects`            → `{ data: Project,             meta }`,
 *           requires the `Idempotency-Key` header (app.py `require_idempotency_key`).
 *
 * The service exposes NO patch/update endpoint, so only create is provided here.
 * `api<T>()` passes the path verbatim, so every path carries the `/bff/api` prefix
 * (see src/api/envelope.ts for the rule and the dropped-ETag-header caveat).
 */
import { api } from './client';
import type { Envelope } from './envelope';
import type { Project, CreateProjectRequest } from './types/project';

/** Fetch every project visible to the caller (no pagination upstream). */
export async function listProjects(): Promise<Project[]> {
  const response = await api<Envelope<Project[]>>('/bff/api/v1/projects');
  return response.data;
}

/** Fetch a single project by id. */
export async function getProject(projectId: string): Promise<Project> {
  const response = await api<Envelope<Project>>(`/bff/api/v1/projects/${projectId}`);
  return response.data;
}

/**
 * Create a project. An `Idempotency-Key` is generated when the caller omits one
 * (the upstream rejects the request without it). `owner_id` defaults upstream
 * to the gateway-resolved actor when omitted from the payload.
 */
export async function createProject(
  payload: CreateProjectRequest,
  idempotencyKey?: string,
): Promise<Project> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<Project>>('/bff/api/v1/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(payload),
  });
  return response.data;
}
