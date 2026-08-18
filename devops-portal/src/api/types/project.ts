/**
 * Project domain types.
 *
 * Fields mirror the real serialisers, in declaration order:
 *  - `Project`           → project-service/src/project_service/projects/models.py `Project.to_dict`
 *  - `ProjectMembership` → .../collaboration/models.py `ProjectMembership.to_dict`
 *  - `ReleaseVersion`    → .../collaboration/models.py `ReleaseVersion.to_dict`
 *  - `Iteration`         → .../collaboration/models.py `Iteration.to_dict`
 *  - `Task`              → .../tasks/models.py `Task.to_dict`
 *
 * Naming stays snake_case so the TypeScript shape is the JSON shape.
 */

/** Project lifecycle status produced by the backend (`active` on create). */
export type ProjectStatus = 'active' | 'archived';

/** Membership role; `owner` can only change through an owner transfer. */
export type ProjectRole = 'owner' | 'admin' | 'member' | 'viewer';

/** Release version lifecycle (`_VERSION_TRANSITIONS`). */
export type ReleaseVersionStatus = 'planned' | 'active' | 'released' | 'archived' | 'canceled';

/** Iteration lifecycle (`_ITERATION_TRANSITIONS`). */
export type IterationStatus = 'planned' | 'active' | 'completed' | 'canceled';

/**
 * Project aggregate as returned by `GET /bff/api/v1/projects` (array) and
 * `GET /bff/api/v1/projects/{id}` (single object), both inside `data`.
 */
export interface Project {
  id: string;
  business_no: string;
  name: string;
  description: string;
  owner_id: string;
  status: ProjectStatus | string;
  /** Optimistic-concurrency token source; feed to `formatIfMatch`. */
  version: number;
  created_at: string;
  updated_at: string;
}

/**
 * Create payload for `POST /bff/api/v1/projects`.
 *
 * `normalize_create_payload` accepts EXACTLY `name` / `description` /
 * `owner_id` and rejects any other key with 422 `VALIDATION_FAILED`.
 * `owner_id` defaults to the gateway-resolved actor when omitted.
 */
export interface CreateProjectRequest {
  name: string;
  description?: string;
  owner_id?: string;
}

/** Dashboard-oriented projection (portal projects-overview block). */
export interface ProjectSummary {
  id: string;
  business_no: string;
  name: string;
  status: string;
  progress_percent: number | null;
  current_iteration: string | null;
  current_version: string | null;
  my_open_task_count: number;
}

/** Project membership row. */
export interface ProjectMembership {
  id: string;
  project_id: string;
  user_id: string;
  role: ProjectRole | string;
  status: string;
  joined_at: string;
  joined_by: string;
  removed_at: string | null;
  removed_by: string | null;
  version: number;
}

/** Release version row. */
export interface ReleaseVersion {
  id: string;
  project_id: string;
  business_no: string;
  name: string;
  description: string;
  status: ReleaseVersionStatus | string;
  planned_release_date: string | null;
  release_date: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Iteration row. */
export interface Iteration {
  id: string;
  project_id: string;
  business_no: string;
  name: string;
  goal: string;
  start_date: string;
  end_date: string;
  capacity_minutes: number | null;
  status: IterationStatus | string;
  version: number;
  created_at: string;
  updated_at: string;
}

/** Project task row (`after` + `limit` offset pagination). */
export interface Task {
  id: string;
  business_no: string;
  project_id: string;
  title: string;
  description: string;
  task_type: string;
  priority: string;
  status: string;
  creator_id: string;
  assignee_id: string | null;
  release_version_id: string | null;
  iteration_id: string | null;
  estimated_minutes: number;
  planned_start_at: string | null;
  planned_end_at: string | null;
  actual_start_at: string | null;
  actual_end_at: string | null;
  workflow_template_key: string;
  workflow_version: number;
  version: number;
  created_at: string;
  updated_at: string;
  participant_ids: string[];
  actual_minutes: number;
}
