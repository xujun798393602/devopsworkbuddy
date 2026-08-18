<script setup lang="ts">
/**
 * TestCaseList — the project-scoped test-case library page body.
 *
 * Cursor-paginated via `useCursorPage` (loader → `listTestCases`), rendered as a plain
 * table, owning the create dialog (`TestCaseForm`) and the inspector (`TestCaseDetail`).
 * Mirrors `DefectList` for visual / behavioural consistency.
 */
import { ref } from 'vue';
import { useCursorPage } from '../../composables/useCursorPage';
import { listTestCases } from '../../api/testcases';
import type { TestCase } from '../../api/types/testcase';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';
import TestCaseForm from './TestCaseForm.vue';
import TestCaseDetail from './TestCaseDetail.vue';

const props = defineProps<{ projectId: string }>();
const emit = defineEmits<{ open: [testCase: TestCase] }>();

const { items, loading, error, hasMore, loadMore, reload } = useCursorPage<TestCase>({
  limit: 20,
  loader: (cursor, limit) => listTestCases(props.projectId, limit, cursor),
});

const formVisible = ref(false);
const detailVisible = ref(false);
const selected = ref<TestCase | null>(null);

function openCreate(): void {
  selected.value = null;
  formVisible.value = true;
}

function openDetail(c: TestCase): void {
  selected.value = c;
  detailVisible.value = true;
  emit('open', c);
}

function openVersions(c: TestCase): void {
  selected.value = c;
  detailVisible.value = true;
}

async function onSaved(): Promise<void> {
  formVisible.value = false;
  await reload();
}
</script>

<template>
  <section class="test-case-list">
    <div class="test-case-list__toolbar">
      <h2 class="text-h6">用例库</h2>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-plus" @click="openCreate">新建用例</v-btn>
    </div>

    <AsyncSection
      :loading="loading"
      :error="error"
      :empty="items.length === 0"
      empty-text="暂无用例"
    >
      <table class="test-case-list__table">
        <thead>
          <tr>
            <th>编号</th>
            <th>标题</th>
            <th>类型</th>
            <th>优先级</th>
            <th>状态</th>
            <th>自动化</th>
            <th>负责人</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in items" :key="c.id" class="test-case-list__row" @click="openDetail(c)">
            <td>{{ c.business_no }}</td>
            <td>{{ c.title }}</td>
            <td>{{ c.type }}</td>
            <td>{{ c.priority }}</td>
            <td><StatusChip :status="c.status" /></td>
            <td>{{ c.automation_mode }}</td>
            <td>{{ c.owner_id || '—' }}</td>
            <td>
              <v-btn size="x-small" variant="text" @click.stop="openDetail(c)">查看</v-btn>
              <v-btn size="x-small" variant="text" @click.stop="openVersions(c)">版本</v-btn>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="hasMore" class="test-case-list__more">
        <v-btn :loading="loading" variant="text" @click="loadMore">加载更多</v-btn>
      </div>
    </AsyncSection>

    <TestCaseForm v-model="formVisible" :project-id="projectId" @created="onSaved" />
    <TestCaseDetail
      v-model="detailVisible"
      :project-id="projectId"
      :case-id="selected?.id ?? ''"
    />
  </section>
</template>
