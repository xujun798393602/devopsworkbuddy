import { beforeEach, describe, expect, it } from 'vitest';
import { createMemoryHistory, createRouter, type Router } from 'vue-router';

import { CATCH_ALL_PATH, DEFAULT_AUTHENTICATED_PATH, routes } from './index';

/**
 * Builds a guard-free router over the production route table.
 *
 * The navigation guard installed in `./index` performs a network session
 * lookup, which is out of scope here. These tests assert the *shape* of the
 * route table only: that real entry points resolve to concrete records and
 * that genuinely unknown URLs still fall through to the catch-all.
 */
function createTestRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes });
}

/** True when a resolved location terminates on the "Not found" catch-all. */
function isCatchAll(matched: readonly { path: string }[]): boolean {
  return matched.some((record) => record.path === CATCH_ALL_PATH);
}

describe('portal route table', () => {
  let router: Router = createTestRouter();

  beforeEach(() => {
    router = createTestRouter();
  });

  it('resolves the site root to a real record instead of the catch-all', () => {
    const resolved = router.resolve('/');
    expect(isCatchAll(resolved.matched)).toBe(false);
  });

  it('navigates the site root through to the authenticated home view', async () => {
    await router.push('/');
    const current = router.currentRoute.value;
    expect(current.fullPath).toBe(DEFAULT_AUTHENTICATED_PATH);
    expect(isCatchAll(current.matched)).toBe(false);
  });

  it('resolves the /app shell root to a real record instead of the catch-all', () => {
    const resolved = router.resolve('/app');
    expect(isCatchAll(resolved.matched)).toBe(false);
  });

  it('navigates /app through to the authenticated home view', async () => {
    await router.push('/app');
    const current = router.currentRoute.value;
    expect(current.fullPath).toBe(DEFAULT_AUTHENTICATED_PATH);
    expect(isCatchAll(current.matched)).toBe(false);
  });

  it('still falls back to the catch-all for genuinely unknown paths', async () => {
    const unknownPath = '/definitely-not-a-real-path';
    const resolved = router.resolve(unknownPath);
    expect(isCatchAll(resolved.matched)).toBe(true);

    await router.push(unknownPath);
    const current = router.currentRoute.value;
    expect(current.fullPath).toBe(unknownPath);
    expect(isCatchAll(current.matched)).toBe(true);
    expect(current.matched[0]?.props.default).toEqual({ title: 'Not found' });
  });

  it('keeps the unauthenticated entry points reachable', () => {
    expect(isCatchAll(router.resolve('/login').matched)).toBe(false);
    expect(isCatchAll(router.resolve('/emergency-login').matched)).toBe(false);
    expect(isCatchAll(router.resolve('/403').matched)).toBe(false);
    expect(isCatchAll(router.resolve('/session-expired').matched)).toBe(false);
  });

  /* ── QA 补充用例（覆盖工程师原测试未触及的边界） ── */

  it('places the catch-all record at the end of the route table (regression guard)', () => {
    const lastRoute = routes[routes.length - 1];
    expect(lastRoute.path).toBe(CATCH_ALL_PATH);
  });

  it('exports DEFAULT_AUTHENTICATED_PATH matching the redirect target', () => {
    expect(DEFAULT_AUTHENTICATED_PATH).toBe('/app/home');
  });

  it('resolves authenticated child routes without hitting catch-all', () => {
    const children = ['/app/home', '/app/projects', '/app/workflows',
      '/app/notifications', '/app/settings/profile', '/app/settings/appearance'];
    for (const p of children) {
      expect(isCatchAll(router.resolve(p).matched)).toBe(false);
    }
  });

  it('root route is a redirect record (not a component)', () => {
    const root = routes.find((r) => r.path === '/');
    expect(root).toBeDefined();
    expect(root!.redirect).toBeDefined();
    expect(root!.component).toBeUndefined();
  });

  it('app default child is a redirect record', () => {
    const app = routes.find((r) => r.path === '/app');
    expect(app).toBeDefined();
    const defaultChild = app!.children?.find((c) => c.path === '');
    expect(defaultChild).toBeDefined();
    expect(defaultChild!.redirect).toBeDefined();
  });

  it('exposes /app/home as the portal dashboard without a route-level permission gate', () => {
    const app = routes.find((r) => r.path === '/app');
    const home = app?.children?.find((c) => c.path === 'home');
    expect(home).toBeDefined();
    expect(home!.meta?.permission).toBeUndefined();
    // Lazy component (code-split), not a statically imported view.
    expect(typeof home!.component).toBe('function');
  });
});

/* ── 工作区 / 四个管理页面路由（T-FE-6）── */

describe('workspace + management routes', () => {
  const router = createRouter({ history: createMemoryHistory(), routes });

  it('resolves /app/projects to the ProjectsView (not the catch-all)', () => {
    expect(isCatchAll(router.resolve('/app/projects').matched)).toBe(false);
    const app = routes.find((r) => r.path === '/app');
    const child = app?.children?.find((c) => c.path === 'projects');
    expect(child).toBeDefined();
    expect(child!.meta?.requiresAuth).toBe(true);
  });

  it('exposes the four workspace tab routes with requiresAuth and no write permission gate', () => {
    const app = routes.find((r) => r.path === '/app');
    const paths = [
      'projects/:project_id',
      'projects/:project_id/requirements',
      'projects/:project_id/defects',
      'projects/:project_id/test-cases',
      'projects/:project_id/traceability',
    ];
    for (const p of paths) {
      const child = app?.children?.find((c) => c.path === p);
      expect(child, p).toBeDefined();
      expect(child!.meta?.requiresAuth, p).toBe(true);
      // P0 临时放宽：写级 meta.permission 以注释预留，路由不挂。
      expect(child!.meta?.permission, p).toBeUndefined();
      // Lazy component (code-split).
      expect(typeof child!.component).toBe('function');
    }
  });

  it('no longer defines the legacy `testing` route', () => {
    const app = routes.find((r) => r.path === '/app');
    const legacy = app?.children?.find((c) => c.path === 'projects/:project_id/testing');
    expect(legacy).toBeUndefined();
  });

  it('resolves each workspace tab route without hitting the catch-all', () => {
    const samples = [
      '/app/projects/p1',
      '/app/projects/p1/requirements',
      '/app/projects/p1/defects',
      '/app/projects/p1/test-cases',
      '/app/projects/p1/traceability',
    ];
    for (const s of samples) {
      expect(isCatchAll(router.resolve(s).matched), s).toBe(false);
    }
  });
});
