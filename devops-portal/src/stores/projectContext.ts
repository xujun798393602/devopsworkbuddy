/**
 * Project context store.
 *
 * Holds the project currently in scope so every domain workspace (requirements,
 * defects, testing, traceability) reads the `project_id` from one place instead of
 * re-parsing the route. The route integration lives in `useProjectContext`; this store
 * is the single source of truth the components bind to.
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { Project } from '../api/types/project';

export const useProjectContextStore = defineStore('projectContext', () => {
  /** Active project id (from the route param `project_id`), or `null`. */
  const projectId = ref<string | null>(null);
  /** Cached project detail, when the workspace has loaded it. */
  const project = ref<Project | null>(null);

  /** Set the active project id, optionally with the loaded detail. */
  function setContext(id: string | null, proj: Project | null = null): void {
    projectId.value = id;
    project.value = proj;
  }

  /** Adopt a fully-loaded project (sets id + detail together). */
  function setProject(proj: Project): void {
    project.value = proj;
    projectId.value = proj.id;
  }

  /** Clear the context (e.g. navigating away from a workspace). */
  function clear(): void {
    projectId.value = null;
    project.value = null;
  }

  return { projectId, project, setContext, setProject, clear };
});
