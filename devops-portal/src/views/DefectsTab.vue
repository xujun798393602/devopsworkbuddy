<script setup lang="ts">
/**
 * DefectsTab — the `/app/projects/:project_id/defects` workspace tab.
 *
 * Thin host for `DefectList` (the full defect line is owned by the first engineer).
 * Created here so the workspace router resolves concretely; replace freely if a richer
 * `DefectsTab` is delivered by the defects workstream.
 */
import { useProjectContext } from '../composables/useProjectContext';
import DefectList from '../components/defects/DefectList.vue';

const { projectId } = useProjectContext();
</script>

<template>
  <section class="defects-tab">
    <DefectList v-if="projectId" :project-id="projectId" />
    <p v-else class="text-caption">未找到项目上下文</p>
  </section>
</template>
