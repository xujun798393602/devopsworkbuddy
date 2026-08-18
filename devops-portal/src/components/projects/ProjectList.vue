<script setup lang="ts">
/**
 * ProjectList — the project collection page body.
 *
 * Loads every project visible to the caller (the upstream returns a flat array, no
 * pagination) and renders a plain table. The "新建项目" button opens `ProjectForm`;
 * on `saved` the list reloads. Async states go through `AsyncSection` so the loading /
 * error / empty UX matches the rest of the portal.
 */
import { onMounted, ref } from 'vue';
import { listProjects } from '../../api/projects';
import type { Project } from '../../api/types/project';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';
import ProjectForm from './ProjectForm.vue';

const projects = ref<Project[]>([]);
const loading = ref(false);
const error = ref<Error | null>(null);
const formVisible = ref(false);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    projects.value = await listProjects();
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function onSaved(): void {
  formVisible.value = false;
  void load();
}
</script>

<template>
  <section class="project-list">
    <div class="project-list__toolbar">
      <h2 class="text-h6">项目</h2>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-plus" @click="formVisible = true">
        新建项目
      </v-btn>
    </div>

    <AsyncSection :loading="loading" :error="error" :empty="projects.length === 0" empty-text="还没有项目">
      <table class="project-list__table">
        <thead>
          <tr>
            <th>编号</th>
            <th>名称</th>
            <th>状态</th>
            <th>负责人</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in projects" :key="p.id">
            <td>{{ p.business_no }}</td>
            <td>{{ p.name }}</td>
            <td><StatusChip :status="p.status" /></td>
            <td>{{ p.owner_id }}</td>
          </tr>
        </tbody>
      </table>
    </AsyncSection>

    <ProjectForm v-model="formVisible" @saved="onSaved" />
  </section>
</template>
