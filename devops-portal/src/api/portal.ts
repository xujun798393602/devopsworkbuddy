/**
 * Portal dashboard API: the single source of truth for dashboard TypeScript
 * types and the only place the cross-project permission / scope literals live.
 *
 * NOTE: never hard-code `portal:cross-project-view`, `mine` or `cross-project`
 * anywhere else in the frontend — import the constants below. The backend
 * response contract is frozen in docs/architecture-portal-dashboard.md §3.1.
 */
import { api } from './client';

/** Backend permission gate for the cross-project (全平台) scope. */
export const PERMISSION_CROSS_PROJECT_VIEW = 'portal:cross-project-view';

/** Frontend-requested scopes (the gateway is the final authority). */
export const SCOPE_MINE = 'mine';
export const SCOPE_CROSS_PROJECT = 'cross-project';

export type Scope = typeof SCOPE_MINE | typeof SCOPE_CROSS_PROJECT;

export interface IterationSummary {
  id: string;
  name: string;
  status: string;
  start_date: string;
  end_date: string;
}

export interface VersionSummary {
  id: string;
  name: string;
  status: string;
  planned_release_date: string;
}

export interface ProjectSummary {
  id: string;
  business_no: string;
  name: string;
  status: string;
  progress_percent: number | null;
  current_iteration: IterationSummary | null;
  current_version: VersionSummary | null;
  my_open_task_count: number;
}

export interface ProjectsBlock {
  total: number;
  items: ProjectSummary[];
}

export interface PendingRequirementReview {
  id: string;
  project_id: string;
  business_no: string;
  title: string;
  status: string;
  updated_at: string;
}

export interface MyOpenDefect {
  id: string;
  project_id: string;
  business_no: string;
  title: string;
  severity: string;
  priority: string;
  status: string;
  sla_breached: boolean;
}

export interface PendingTestExecution {
  id: string;
  project_id: string;
  plan_id: string;
  name: string;
  status: string;
  planned_at: string | null;
}

export interface PendingWorkflowApproval {
  id: string;
  project_id: string;
  business_object_type: string;
  business_object_id: string;
  current_state: string;
  started_at: string | null;
}

export interface MyWorkBlock {
  pending_requirement_reviews: { count: number; items: PendingRequirementReview[] };
  my_open_defects: { count: number; items: MyOpenDefect[] };
  pending_test_executions: { count: number; items: PendingTestExecution[] };
  pending_workflow_approvals: { count: number; items: PendingWorkflowApproval[] };
}

export interface RequirementStats {
  total: number;
  by_status: Record<string, number>;
  baseline_total: number;
}

export interface TpStats {
  case_total: number;
  plan_total: number;
  execution_total: number;
  execution_by_status: Record<string, number>;
  pass_rate: number | null;
}

export interface TdStats {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  sla_breached: number;
}

export interface ActivityItem {
  id: string;
  occurred_at: string;
  actor_id: string;
  actor_name: string;
  action: string;
  resource_type: string;
  resource_id: string;
  project_id: string;
  summary: string;
}

export interface ActivityBlock {
  source: 'audit' | 'notification';
  items: ActivityItem[];
}

export interface Degradation {
  domain: string;
  reason: string;
}

export interface DashboardData {
  scope: Scope;
  scope_requested: Scope;
  scope_downgraded: boolean;
  can_cross_project: boolean;
  generated_at: string;
  projects: ProjectsBlock;
  my_work: MyWorkBlock;
  requirement_stats: RequirementStats;
  tp_stats: TpStats;
  td_stats: TdStats;
  recent_activities: ActivityBlock;
  degraded: Degradation[];
}

export interface DashboardResponse {
  data: DashboardData;
  meta: { trace_id: string; took_ms: number };
}

/**
 * Fetch the portal dashboard for a requested scope.
 *
 * Always goes through `api<T>()` so 401 auto-refresh, replay and CSRF are
 * handled uniformly — never use a raw `fetch` here.
 */
export async function fetchDashboard(scope: Scope): Promise<DashboardData> {
  const response = await api<DashboardResponse>(`/bff/api/portal/dashboard?scope=${scope}`);
  return response.data;
}
