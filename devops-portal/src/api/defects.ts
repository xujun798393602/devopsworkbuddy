/**
 * Defect domain API.  (The fully-implemented "defect line".)
 *
 * Contracts verified against td-service real sources (td_service/app.py,
 * service.py, domain.py):
 *  - list       `GET  /projects/{pid}/defects`              → `{ data:{items}, meta:{next_cursor,has_more} }`
 *  - get        `GET  /projects/{pid}/defects/{id}`          → `{ data: Defect, meta }`
 *  - create     `POST /projects/{pid}/defects`               → `{ data: Defect, meta }`
 *               requires `Idempotency-Key`.
 *  - patch      `PATCH /projects/{pid}/defects/{id}`          → `{ data: Defect, meta }`
 *               requires `If-Match: "<version>"`; body limited to `DEFECT_PATCHABLE_FIELDS`.
 *  - transition `POST /projects/{pid}/defects/{id}/transitions`
 *               requires `Idempotency-Key` + `If-Match: "<version>"`.
 *  - history    `GET  /projects/{pid}/defects/{id}/history`   → `{ data: DefectHistoryEntry[], meta:{count} }`
 *
 * Every response is wrapped in `{ data, meta }`; the ETag header is dropped by
 * the gateway, so the concurrency token is always read from `data.version`.
 */
import { api } from './client';
import {
  projectPath,
  cursorSearch,
  ifMatchHeaders,
  type Envelope,
  type ListEnvelope,
} from './envelope';
import type {
  Defect,
  CreateDefectRequest,
  UpdateDefectRequest,
  DefectTransitionRequest,
  DefectHistoryEntry,
} from './types/defect';

/** Cursor-paginated defect list for a project. */
export async function listDefects(
  projectId: string,
  limit = 20,
  cursor: string | null = null,
): Promise<ListEnvelope<Defect>> {
  return api<ListEnvelope<Defect>>(projectPath(projectId, `/defects${cursorSearch({ limit, cursor })}`));
}

/** Fetch a single defect. */
export async function getDefect(projectId: string, defectId: string): Promise<Defect> {
  const response = await api<Envelope<Defect>>(projectPath(projectId, `/defects/${defectId}`));
  return response.data;
}

/** Create a defect (idempotent via `Idempotency-Key`). */
export async function createDefect(
  projectId: string,
  payload: CreateDefectRequest,
  idempotencyKey?: string,
): Promise<Defect> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<Defect>>(projectPath(projectId, '/defects'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(payload),
  });
  return response.data;
}

/**
 * Patch a defect under optimistic concurrency. `version` becomes the quoted
 * `If-Match` header. Only `DEFECT_PATCHABLE_FIELDS` may be present in `payload`.
 */
export async function updateDefect(
  projectId: string,
  defectId: string,
  payload: UpdateDefectRequest,
  version: number,
  idempotencyKey?: string,
): Promise<Defect> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<Defect>>(projectPath(projectId, `/defects/${defectId}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...ifMatchHeaders(version) },
    body: JSON.stringify(payload),
  });
  return response.data;
}

/** Apply one explicit workflow action under optimistic concurrency. */
export async function transitionDefect(
  projectId: string,
  defectId: string,
  payload: DefectTransitionRequest,
  version: number,
  idempotencyKey?: string,
): Promise<Defect> {
  const key = idempotencyKey ?? crypto.randomUUID();
  const response = await api<Envelope<Defect>>(
    projectPath(projectId, `/defects/${defectId}/transitions`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, ...ifMatchHeaders(version) },
      body: JSON.stringify(payload),
    },
  );
  return response.data;
}

/** Fetch the append-only workflow history of a defect. */
export async function getDefectHistory(
  projectId: string,
  defectId: string,
): Promise<DefectHistoryEntry[]> {
  const response = await api<Envelope<DefectHistoryEntry[]>>(
    projectPath(projectId, `/defects/${defectId}/history`),
  );
  return response.data;
}
