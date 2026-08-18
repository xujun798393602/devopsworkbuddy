<script setup lang="ts">
/**
 * ProjectWorkspaceView — the four-tab workspace root for `/app/projects/:project_id`.
 *
 * Resolves the project id from the route via `useProjectContext`, loads the project
 * base info through `getProject`, and renders four tabs (Requirements / Defects /
 * TestCases / Traceability). The active tab component is swapped with `<component :is>`
 * and kept alive so list state survives tab switches. Tab components read the same
 * `project_id` from the route, so no prop drilling is needed.
 */
import { computed, onMounted, ref } from 'vue';
import { useProjectContext } from '../composables/useProjectContext';
import { getProject } from '../api/projects';
import type { Project } from '../api/types/project';
import AsyncSection from '../components/common/AsyncSection.vue';
import StatusChip from '../components/common/StatusChip.vue';
import RequirementsTab from '../views/RequirementsTab.vue';
import DefectsTab from '../views/DefectsTab.vue';
import TestCasesTab from '../views/TestCasesTab.vue';
import TraceabilityTab from '../views/TraceabilityTab.vue';

const { projectId, project, setProject } = useProjectContext();

const TABS = [
  { key: 'requirements', label: '需求', component: RequirementsTab },
  { key: 'defects', label: '缺陷', component: DefectsTab },
  { key: 'test-cases', label: '用例', component: TestCasesTab },
  { key: 'traceability', label: '追溯', component: TraceabilityTab },
] as const;

const activeTab = ref<string>('requirements');
const headerLoading = ref(false);
const headerError = ref<Error | null>(null);

const activeComponent = computed(
  () => TABS.find((t) => t.key === activeTab.value)?.component ?? RequirementsTab,
);

async function loadProject(): Promise<void> {
  if (!projectId.value) return;
  headerLoading.value = true;
  headerError.value = null;
  try {
    const proj: Project = await getProject(projectId.value);
    setProject(proj);
  } catch (e) {
    headerError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    headerLoading.value = false;
  }
}

onMounted(loadProject);
</script>

<template>
  <section class="project-workspace">
    <AsyncSection :loading="headerLoading" :error="headerError">
      <header v-if="project" class="project-workspace__header">
        <div>
          <p class="eyebrow">项目 {{ project.business_no }}</p>
          <h1>{{ project.name }}</h1>
        </div>
        <StatusChip :status="project.status" />
      </header>
      <p v-else-if="projectId" class="text-caption">未找到项目信息（ID: {{ projectId }}）</p>
    </AsyncSection>

    <v-tabs v-model="activeTab" color="primary" class="project-workspace__tabs" role="tablist">
      <v-tab v-for="t in TABS" :key="t.key" :value="t.key" role="tab">{{ t.label }}</v-tab>
    </v-tabs>

    <KeepAlive>
      <component :is="activeComponent" :key="activeTab" />
    </KeepAlive>
  </section>
</template>

<style scoped>
.project-workspace__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.5rem;
}
.project-workspace__header h1 {
  font-size: 1.5rem;
  margin: 0.25rem 0 0;
}
.eyebrow {
  font-weight: 700;
  color: rgb(var(--v-theme-primary));
}
.project-workspace__tabs {
  margin-bottom: 1rem;
}
</style>
