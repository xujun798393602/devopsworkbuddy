import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

import Shell from '../layouts/AppShell.vue';
import { useAuthStore } from '../stores/auth';
import Login from '../views/LoginView.vue';
import Simple from '../views/SimpleView.vue';
import ProjectsView from '../views/ProjectsView.vue';

/** Path pattern of the terminal catch-all record that renders "Not found". */
export const CATCH_ALL_PATH = '/:pathMatch(.*)*';

/** Landing route for an authenticated session. */
export const DEFAULT_AUTHENTICATED_PATH = '/app/home';

/**
 * Production route table.
 *
 * Exported so that route-shape regressions can be asserted in isolation,
 * without installing the network-dependent navigation guard below.
 */
export const routes: RouteRecordRaw[] = [
  // The site root must resolve to a real destination. Without this record the
  // bare origin (http://host:18081/) matched nothing but the catch-all and
  // rendered "Not found". Unauthenticated visitors are then bounced to /login
  // by the navigation guard below, which is the intended entry flow.
  { path: '/', redirect: DEFAULT_AUTHENTICATED_PATH },
  { path: '/login', component: Login },
  { path: '/emergency-login', component: () => import('../views/EmergencyLoginView.vue') },
  {
    path: '/app',
    component: Shell,
    meta: { requiresAuth: true },
    children: [
      // Default child so that the shell root (/app) is a valid destination
      // rather than falling through to the catch-all.
      { path: '', redirect: DEFAULT_AUTHENTICATED_PATH },
      {
        path: 'home',
        // The portal dashboard is reachable for any authenticated user; the
        // gateway resolves the effective scope (mine vs cross-project) from the
        // caller's permissions, so no route-level permission gate is used here.
        component: () => import('../views/HomeView.vue'),
      },
      // Project collection (cross-project). Replaces the Simple placeholder.
      { path: 'projects', component: ProjectsView, meta: { requiresAuth: true } },
      // Workspace root: four-tab container for a single project.
      {
        path: 'projects/:project_id',
        component: () => import('../views/ProjectWorkspaceView.vue'),
        // TODO: 待 IAM 注册后启用写级门禁，例如 meta: { requiresAuth: true, permission: 'project.write' }
        meta: { requiresAuth: true },
      },
      {
        path: 'projects/:project_id/requirements',
        component: () => import('../views/RequirementsTab.vue'),
        // TODO: 待 IAM 注册后启用 meta.permission: 'requirement.write'
        meta: { requiresAuth: true },
      },
      {
        path: 'projects/:project_id/defects',
        component: () => import('../views/DefectsTab.vue'),
        // TODO: 待 IAM 注册后启用 meta.permission: 'defect.write'
        meta: { requiresAuth: true },
      },
      {
        path: 'projects/:project_id/test-cases',
        // 原 `testing` 路由已删除，统一为 `test-cases`（对应 tp-service 网关路由 key）。
        component: () => import('../views/TestCasesTab.vue'),
        // TODO: 待 IAM 注册后启用 meta.permission: 'testcase.write'
        meta: { requiresAuth: true },
      },
      {
        path: 'projects/:project_id/traceability',
        component: () => import('../views/TraceabilityTab.vue'),
        // TODO: 待 IAM 注册后启用 meta.permission: 'project.read'
        meta: { requiresAuth: true },
      },
      { path: 'workflows', component: Simple, props: { title: 'Workflows' } },
      { path: 'notifications', component: Simple, props: { title: 'Notifications' } },
      { path: 'settings/profile', component: Simple, props: { title: 'Profile' } },
      { path: 'settings/appearance', component: () => import('../views/AppearanceView.vue') },
      {
        path: 'settings/notifications',
        component: Simple,
        props: { title: 'Notification preferences' },
      },
      {
        path: 'audit',
        component: Simple,
        props: { title: 'Audit' },
        meta: { permission: 'audit.read' },
      },
    ],
  },
  { path: '/403', component: Simple, props: { title: 'Forbidden' } },
  { path: '/session-expired', component: Simple, props: { title: 'Session expired' } },
  { path: CATCH_ALL_PATH, component: Simple, props: { title: 'Not found' } },
];

const router = createRouter({ history: createWebHistory(), routes });

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.initialized) await auth.initialize();
  if (to.meta.requiresAuth && !auth.authenticated) return { path: '/login' };
  const permission = to.meta.permission as string | undefined;
  if (permission && !auth.has(permission)) return { path: '/403' };
  return true;
});

export default router;
