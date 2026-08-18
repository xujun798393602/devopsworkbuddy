<script setup lang="ts">
/**
 * RequirementList — the project-scoped requirement management page body.
 *
 * Drives a cursor-paginated list through `useCursorPage` (loader → `listRequirements`),
 * renders it as a plain table for robust styling, and owns the create dialog
 * (`RequirementForm`) and the inspector dialog (`RequirementDetail`). Mirrors
 * `DefectList` for visual / behavioural consistency.
 */
import { ref } from 'vue';
import { useCursorPage } from '../../composables/useCursorPage';
import { listRequirements } from '../../api/requirements';
import type { Requirement } from '../../api/types/requirement';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';
import RequirementForm from './RequirementForm.vue';
import RequirementDetail from './RequirementDetail.vue';

const props = defineProps<{ projectId: string }>();
const emit = defineEmits<{ open: [requirement: Requirement] }>();

const { items, loading, error, hasMore, loadMore, reload } = useCursorPage<Requirement>({
  limit: 20,
  loader: (cursor, limit) => listRequirements(props.projectId, limit, cursor),
});

const formVisible = ref(false);
const detailVisible = ref(false);
const selected = ref<Requirement | null>(null);

function openCreate(): void {
  selected.value = null;
  formVisible.value = true;
}

function openDetail(req: Requirement): void {
  selected.value = req;
  detailVisible.value = true;
  emit('open', req);
}

async function onSaved(): Promise<void> {
  formVisible.value = false;
  await reload();
}

async function onUpdated(): Promise<void> {
  await reload();
}
</script>

<template>
  <section class="requirement-list">
    <div class="requirement-list__toolbar">
      <h2 class="text-h6">需求</h2>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-plus" @click="openCreate">新建需求</v-btn>
    </div>

    <AsyncSection
      :loading="loading"
      :error="error"
      :empty="items.length === 0"
      empty-text="暂无需求"
    >
      <table class="requirement-list__table">
        <thead>
          <tr>
            <th>编号</th>
            <th>标题</th>
            <th>类型</th>
            <th>状态</th>
            <th>优先级</th>
            <th>负责人</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in items" :key="r.id" class="requirement-list__row" @click="openDetail(r)">
            <td>{{ r.business_no }}</td>
            <td>{{ r.title }}</td>
            <td>{{ r.type }}</td>
            <td><StatusChip :status="r.status" /></td>
            <td>{{ r.priority }}</td>
            <td>{{ r.owner_id || '—' }}</td>
            <td>
              <v-btn size="x-small" variant="text" @click.stop="openDetail(r)">查看</v-btn>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="hasMore" class="requirement-list__more">
        <v-btn :loading="loading" variant="text" @click="loadMore">加载更多</v-btn>
      </div>
    </AsyncSection>

    <RequirementForm v-model="formVisible" :project-id="projectId" @created="onSaved" />
    <RequirementDetail
      v-model="detailVisible"
      :project-id="projectId"
      :requirement-id="selected?.id ?? ''"
      @updated="onUpdated"
    />
  </section>
</template>
