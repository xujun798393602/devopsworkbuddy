/**
 * Requirement domain types.
 *
 * Fields mirror the requirement-service serialisers, verified against the real
 * sources (NOT the architecture document):
 *  - `Requirement`       → requirement-service/src/requirement_service/app.py
 *                         `_requirement_data` (single + list shape).
 *  - `RequirementType` / `RequirementStatus` → .../domain.py `RequirementType`,
 *                         `RequirementStatus`.
 *  - create / transition bodies → .../app.py `create_requirement` &
 *                         `transition_requirement`.
 *
 * Naming stays snake_case so the TypeScript shape equals the JSON shape.
 */

/** Requirement taxonomy (domain.py `RequirementType`). */
export type RequirementType =
  | 'epic'
  | 'feature'
  | 'user_story'
  | 'fr'
  | 'nfr'
  | 'ac';

/** Requirement lifecycle (domain.py `RequirementStatus`). */
export type RequirementStatus =
  | 'draft'
  | 'in_review'
  | 'rejected'
  | 'approved'
  | 'active'
  | 'completed'
  | 'canceled';

/** Priority ladder shared with defects / test cases. */
export type RequirementPriority = 'p0' | 'p1' | 'p2' | 'p3';

/** A single acceptance-criterion row (kept as an open record for forward-compat). */
export type AcceptanceCriterion = Record<string, string>;

/** Requirement aggregate as returned inside `data` everywhere. */
export interface Requirement {
  id: string;
  project_id: string;
  business_no: string;
  title: string;
  type: RequirementType | string;
  status: RequirementStatus | string;
  priority: RequirementPriority | string;
  owner_id: string;
  release_version_id: string;
  parent_id: string | null;
  description: string;
  acceptance_criteria: AcceptanceCriterion[];
  current_revision: number;
  baseline_status: string;
  version: number;
  /** Persisted as `null` until the schema migration lands (app.py note). */
  created_at: string | null;
  updated_at: string | null;
}

/** Create payload for `POST /requirements` (app.py `create_requirement`). */
export interface CreateRequirementRequest {
  title: string;
  type: RequirementType | string;
  owner_id: string;
  release_version_id: string;
  description?: string;
  priority?: RequirementPriority | string;
  acceptance_criteria?: AcceptanceCriterion[];
}

/** Patch payload for `PATCH /requirements/{id}` (service `PATCHABLE_FIELDS`). */
export interface UpdateRequirementRequest {
  title?: string;
  description?: string;
  priority?: RequirementPriority | string;
  owner_id?: string;
  release_version_id?: string;
  parent_id?: string | null;
  acceptance_criteria?: AcceptanceCriterion[];
  tags?: string[];
}

/** Transition body for `POST /requirements/{id}/transitions`. */
export interface RequirementTransitionRequest {
  action: string;
  approved_review?: boolean;
  baselined?: boolean;
  completion_evidence?: boolean;
  privileged?: boolean;
  reason?: string;
}

/** The eight explicit lifecycle actions (domain.py `Requirement.transition`). */
export const REQUIREMENT_ACTIONS: readonly string[] = [
  'submit_review',
  'approve',
  'reject',
  'return_to_draft',
  'activate',
  'complete',
  'cancel',
  'reopen',
];

/** Actions whose `reason` is mandatory (app.py `REASON_REQUIRED_ACTIONS`). */
export const REASON_REQUIRED_ACTIONS: readonly string[] = ['reopen'];

/**
 * Requirement sub-module view models (reviews / baselines / change-requests).
 *
 * Field names stay snake_case to match the JSON. Envelope + path contracts were
 * verified against the requirement-service real routes (the requirement line is
 * implemented in tp-service / requirement-service). Single resources arrive as
 * `{ data: T, meta }`; lists as `{ data: { items: T[] }, meta }`.
 */

/** A review record attached to a requirement (reviews sub-module). */
export interface RequirementReview {
  id: string;
  requirement_id: string;
  reviewer_id: string;
  decision: 'approved' | 'rejected' | 'pending';
  comment?: string;
  version: number;
}

/** Create payload for `POST /requirements/{rid}/reviews`. */
export interface CreateRequirementReviewRequest {
  reviewer_id: string;
  decision: 'approved' | 'rejected' | 'pending';
  comment?: string;
}

/** A baseline snapshot of a requirement (baselines sub-module). */
export interface RequirementBaseline {
  id: string;
  requirement_id: string;
  baseline_no: string;
  status: string;
  version: number;
}

/** Create payload for `POST /requirements/{rid}/requirement-baselines`. */
export interface CreateRequirementBaselineRequest {
  baseline_no: string;
  status?: string;
}

/** A change request against a requirement (change-requests sub-module). */
export interface ChangeRequest {
  id: string;
  requirement_id: string;
  title: string;
  status: string;
  version: number;
}

/** Create payload for `POST /requirements/{rid}/change-requests`. */
export interface CreateChangeRequestRequest {
  title: string;
  status?: string;
}
