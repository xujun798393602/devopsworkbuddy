/**
 * Test-case / test-plan domain types.
 *
 * Verified against tp-service real sources:
 *  - `TestCase` / `TestCaseVersion` serialize → tp_service/app.py `_case`, `_version`.
 *  - `TestPlan` serialize                 → tp_service/app.py `_plan`.
 *  - case create body                     → tp_service/app.py `create_case_route`.
 *  - plan transition actions              → tp_service/service.py `PLAN_TRANSITION_ACTIONS`.
 *  - enums (`TestCaseType`, `automation_mode`, step `source`)
 *                                        → tp_service/domain.py `TestCase`,
 *                                          `TestCaseVersion.create`.
 *
 * Naming stays snake_case so the TypeScript shape equals the JSON shape.
 */

/** Test-case classification (domain.py `TestCase.__post_init__`). */
export type TestCaseType =
  | 'functional'
  | 'api'
  | 'ui'
  | 'android'
  | 'android_tv'
  | 'other';

/** Priority ladder shared with requirement / defect. */
export type TestCasePriority = 'p0' | 'p1' | 'p2' | 'p3';

/** Automation mode (domain.py `TestCase.__post_init__`). */
export type TestCaseAutomationMode = 'manual' | 'automated' | 'candidate';

/** Test-case head as returned inside `data` (app.py `_case`). */
export interface TestCase {
  id: string;
  project_id: string;
  business_no: string;
  folder_id: string;
  title: string;
  owner_id: string;
  type: TestCaseType | string;
  priority: TestCasePriority | string;
  status: string;
  automation_mode: TestCaseAutomationMode | string;
  current_version_id: string | null;
  requirement_refs: string[];
  version: number;
}

/** Create payload for `POST /test-cases` (app.py `create_case_route`). */
export interface CreateTestCaseRequest {
  title: string;
  owner_id: string;
  folder_id?: string;
  business_no?: string;
  type?: TestCaseType | string;
  priority?: TestCasePriority | string;
  automation_mode?: TestCaseAutomationMode | string;
  requirement_refs?: string[];
}

/** One immutable step inside a case version (domain.py `TestStep`). */
export interface TestStep {
  sequence: number;
  action: string;
  expected: string;
  test_data?: string;
}

/** Immutable case version (app.py `_version`). */
export interface TestCaseVersion {
  id: string;
  case_id: string;
  version_no: number;
  content_hash: string;
  source: 'design' | 'manual' | 'import' | 'automation';
  steps: TestStep[];
}

/** Create payload for `POST /test-cases/{id}/versions`. */
export interface CreateTestCaseVersionRequest {
  steps: TestStep[];
  source?: 'design' | 'manual' | 'import' | 'automation';
}

/** Create payload for `POST /test-plans` (app.py `create_plan` reads `owner_id` & `business_no`). */
export interface CreateTestPlanRequest {
  owner_id: string;
  business_no?: string;
}

/** One frozen scope line of a test plan (app.py `_plan`). */
export interface TestPlanScopeItem {
  requirement_ref: string;
  requirement_revision: number;
  requirement_hash: string;
  case_version_ref: string;
  environment_id: string;
}

/** Test plan as returned inside `data` (app.py `_plan`). */
export interface TestPlan {
  id: string;
  project_id: string;
  business_no: string;
  owner_id: string;
  status: string;
  scope_hash: string;
  version: number;
  scope: TestPlanScopeItem[];
}

/** Transition body for `POST /test-plans/{id}/transitions`. */
export interface TestPlanTransitionRequest {
  action: string;
  scope?: TestPlanScopeItem[];
  valid_case_versions?: string[];
  reason?: string;
}

/** Plan lifecycle actions (service.py `PLAN_TRANSITION_ACTIONS`). */
export const PLAN_TRANSITION_ACTIONS: readonly string[] = [
  'freeze',
  'start_execution',
  'complete',
  'cancel',
  'close',
];
