<script setup lang="ts">
/**
 * TestCasesTab — the `/app/projects/:project_id/test-cases` workspace tab.
 *
 * Thin host for `TestCaseList`; project scoping is resolved from the route via
 * `useProjectContext`.
 */
import { useProjectContext } from '../composables/useProjectContext';
import TestCaseList from '../components/testcases/TestCaseList.vue';

const { projectId } = useProjectContext();
</script>

<template>
  <section class="test-cases-tab">
    <TestCaseList v-if="projectId" :project-id="projectId" />
    <p v-else class="text-caption">未找到项目上下文</p>
  </section>
</template>
