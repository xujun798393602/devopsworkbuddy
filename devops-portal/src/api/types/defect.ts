/**
 * Defect domain types.
 *
 * Verified against td-service real sources:
 *  - `Defect` serialize shape      → td_service/app.py `_serialize`.
 *  - `DefectStatus` / severity / type sets → td_service/domain.py
 *    (`DefectStatus`, `_SLA_HOURS`, `_DEFECT_TYPES`).
 *  - `DEFECT_PATCHABLE_FIELDS`     → td_service/service.py.
 *  - transition body + history row → td_service/app.py `transition_defect` &
 *    `get_history`; history `from`/`to` are status values (NOT `from_status`).
 *  - evidence shapes               → td_service/domain.py `FixEvidence` /
 *    `VerificationEvidence`.
 *
 * Naming stays snake_case so the TypeScript shape equals the JSON shape.
 */

/** Nine-state defect workflow (domain.py `DefectStatus`). */
export type DefectStatus =
  | 'new'
  | 'assigned'
  | 'in_progress'
  | 'fixed'
  | 'pending_verification'
  | 'closed'
  | 'reopened'
  | 'rejected'
  | 'duplicate';

/** Severity ladder (domain.py `_SLA_HOURS` keys). */
export type DefectSeverity =
  | 'blocker'
  | 'critical'
  | 'major'
  | 'minor'
  | 'trivial';

/** Defect classification (domain.py `_DEFECT_TYPES`). */
export type DefectType =
  | 'functional'
  | 'performance'
  | 'security'
  | 'compatibility'
  | 'usability'
  | 'data'
  | 'configuration'
  | 'other';

/** Priority ladder shared with requirement / test case. */
export type DefectPriority = 'p0' | 'p1' | 'p2' | 'p3';

/** Creation-time SLA snapshot attached to every defect (app.py `_serialize`). */
export interface DefectSla {
  policy_key: string;
  policy_version: string;
  response_due_at: string;
  resolution_due_at: string;
  response_breached: boolean;
  resolution_breached: boolean;
}

/** Defect aggregate as returned inside `data` everywhere. */
export interface Defect {
  id: string;
  project_id: string;
  business_no: string;
  title: string;
  description: string;
  severity: DefectSeverity | string;
  priority: DefectPriority | string;
  defect_type: DefectType | string;
  status: DefectStatus | string;
  reporter_id: string;
  assignee_id: string | null;
  verifier_id: string | null;
  reopen_count: number;
  /** Optimistic-concurrency token source; feed to `formatIfMatch`. */
  version: number;
  sla: DefectSla | null;
}

/** Create payload for `POST /defects` (service.py `DefectService.create`). */
export interface CreateDefectRequest {
  title: string;
  description?: string;
  severity?: DefectSeverity | string;
  priority?: DefectPriority | string;
  defect_type?: DefectType | string;
  expected_result?: string;
  actual_result?: string;
  reproduction_steps?: string[];
}

/** Patch payload — MUST stay within `DEFECT_PATCHABLE_FIELDS` (service.py). */
export interface UpdateDefectRequest {
  title?: string;
  description?: string;
  severity?: DefectSeverity | string;
  priority?: DefectPriority | string;
  defect_type?: DefectType | string;
  expected_result?: string;
  actual_result?: string;
  reproduction_steps?: string[];
}

/** Immutable repair-evidence reference (domain.py `FixEvidence`). */
export interface FixEvidence {
  type: 'mr' | 'commit' | 'patch' | 'other';
  external_ref: string;
  summary: string;
}

/** Immutable human verification evidence (domain.py `VerificationEvidence`). */
export interface VerificationEvidence {
  environment_ref: string;
  conclusion: 'passed' | 'failed';
  evidence_refs: string[];
}

/** Transition body for `POST /defects/{id}/transitions` (app.py). */
export interface DefectTransitionRequest {
  action: string;
  privileged?: boolean;
  assignee_id?: string | null;
  verifier_id?: string | null;
  reason?: string;
  fix_version_id?: string | null;
  fix_evidence?: FixEvidence | null;
  verification?: VerificationEvidence | null;
  root_cause?: string;
  duplicate_of_id?: string | null;
}

/** One workflow-history row (app.py `get_history`). `from`/`to` are statuses. */
export interface DefectHistoryEntry {
  sequence_no: number;
  action: string;
  actor_id: string;
  from: string;
  to: string;
  reason: string;
}

/** The only fields a direct PATCH may mutate (service.py `DEFECT_PATCHABLE_FIELDS`). */
export const DEFECT_PATCHABLE_FIELDS: readonly string[] = [
  'title',
  'description',
  'severity',
  'priority',
  'defect_type',
  'expected_result',
  'actual_result',
  'reproduction_steps',
];

/** Explicit defect transition actions (domain.py `Defect.transition`). */
export const DEFECT_TRANSITION_ACTIONS: readonly string[] = [
  'assign',
  'start',
  'reject',
  'mark_fixed',
  'submit_verification',
  'verify_close',
  'verify_fail',
  'manual_reopen',
  'mark_duplicate',
];
