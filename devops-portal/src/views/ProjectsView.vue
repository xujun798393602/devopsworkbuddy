<script setup lang="ts">
/**
 * ProjectsView — the `/app/projects` route body.
 *
 * The route carries no `project_id`, so this is the cross-project project collection.
 * It simply hosts `ProjectList`. (Project-scoped workspaces live under
 * `/app/projects/:project_id/...` and are wired by the second engineer.)
 */
import ProjectList from '../components/projects/ProjectList.vue';
</script>

<template>
  <div class="projects-view">
    <ProjectList />
  </div>
</template>
