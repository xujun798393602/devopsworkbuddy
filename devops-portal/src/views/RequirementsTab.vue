<script setup lang="ts">
/**
 * RequirementsTab — the `/app/projects/:project_id/requirements` workspace tab.
 *
 * Thin host for `RequirementList`; project scoping is resolved from the route via
 * `useProjectContext` so every workspace tab shares one project id.
 */
import { useProjectContext } from '../composables/useProjectContext';
import RequirementList from '../components/requirements/RequirementList.vue';

const { projectId } = useProjectContext();
</script>

<template>
  <section class="requirements-tab">
    <RequirementList v-if="projectId" :project-id="projectId" />
    <p v-else class="text-caption">未找到项目上下文</p>
  </section>
</template>
