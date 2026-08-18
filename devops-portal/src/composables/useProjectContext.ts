/**
 * Bind the project context store to the active route.
 *
 * Domain workspace routes are `/app/projects/:project_id/...`, so this composable
 * watches `route.params.project_id` and keeps `useProjectContextStore` in sync. When
 * the project changes it clears the cached detail (the workspace refetches it). It also
 * exposes `setProject` so a workspace can publish the loaded `Project` for siblings.
 */
import { watch } from 'vue';
import { useRoute } from 'vue-router';
import { storeToRefs } from 'pinia';
import { useProjectContextStore } from '../stores/projectContext';
import type { Project } from '../api/types/project';

/** Reactive project context derived from the route. */
export function useProjectContext() {
  const route = useRoute();
  const store = useProjectContextStore();
  const { projectId, project } = storeToRefs(store);

  /** Push the current route's `project_id` into the store. */
  function syncFromRoute(): void {
    const id = (route.params.project_id as string | undefined) ?? null;
    if (id !== store.projectId) {
      // Detail is project-scoped; drop the stale one on navigation.
      store.setContext(id);
    }
  }

  watch(() => route.params.project_id, syncFromRoute, { immediate: true });

  /** Publish a fully-loaded project for sibling components. */
  function setProject(proj: Project): void {
    store.setProject(proj);
  }

  return { projectId, project, syncFromRoute, setProject };
}
