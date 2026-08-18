<script setup lang="ts">
/**
 * DefectList — the project-scoped defect management page body.
 *
 * Drives a cursor-paginated list through `useCursorPage` (loader → `listDefects`),
 * renders it as a plain table for robust styling, and owns the create dialog
 * (`DefectForm`) and the inspector dialog (`DefectDetail`). A row click opens the
 * inspector and also emits `open` so a parent workspace can react. `AsyncSection`
 * provides the shared loading / error / empty UX.
 */
import { ref } from 'vue';
import { useCursorPage } from '../../composables/useCursorPage';
import { listDefects } from '../../api/defects';
import type { Defect } from '../../api/types/defect';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';
import DefectForm from './DefectForm.vue';
import DefectDetail from './DefectDetail.vue';

const props = defineProps<{ projectId: string }>();
const emit = defineEmits<{ open: [defect: Defect] }>();

const { items, loading, error, hasMore, loadMore, reload } = useCursorPage<Defect>({
  limit: 20,
  loader: (cursor, limit) => listDefects(props.projectId, limit, cursor),
});

const formVisible = ref(false);
const detailVisible = ref(false);
const selected = ref<Defect | null>(null);

function openCreate(): void {
  selected.value = null;
  formVisible.value = true;
}

function openDetail(defect: Defect): void {
  selected.value = defect;
  detailVisible.value = true;
  emit('open', defect);
}

async function onSaved(): Promise<void> {
  formVisible.value = false;
  await reload();
}
</script>

<template>
  <section class="defect-list">
    <div class="defect-list__toolbar">
      <h2 class="text-h6">缺陷</h2>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-plus" @click="openCreate">新建缺陷</v-btn>
    </div>

    <AsyncSection :loading="loading" :error="error" :empty="items.length === 0" empty-text="暂无缺陷">
      <table class="defect-list__table">
        <thead>
          <tr>
            <th>编号</th>
            <th>标题</th>
            <th>严重度</th>
            <th>优先级</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in items" :key="d.id" class="defect-list__row" @click="openDetail(d)">
            <td>{{ d.business_no }}</td>
            <td>{{ d.title }}</td>
            <td>{{ d.severity }}</td>
            <td>{{ d.priority }}</td>
            <td><StatusChip :status="d.status" /></td>
          </tr>
        </tbody>
      </table>

      <div v-if="hasMore" class="defect-list__more">
        <v-btn :loading="loading" variant="text" @click="loadMore">加载更多</v-btn>
      </div>
    </AsyncSection>

    <DefectForm v-model="formVisible" :project-id="projectId" :defect="selected" @saved="onSaved" />
    <DefectDetail v-model="detailVisible" :project-id="projectId" :defect="selected" />
  </section>
</template>
