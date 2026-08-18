<script setup lang="ts">
/**
 * TestPlanList — project-scoped test-plan list with inline create + transitions.
 *
 * Cursor-paginated via `useCursorPage` (loader → `listTestPlans`). Each row exposes a
 * transition action set derived from its current status; transitions carry the quoted
 * `If-Match` (auto-added by the api module from the plan `version`). Plan creation goes
 * through `createTestPlan` (the api module attaches the `Idempotency-Key`). Mirrors `DefectList`.
 */
import { ref } from 'vue';
import { useCursorPage } from '../../composables/useCursorPage';
import { listTestPlans, createTestPlan, transitionTestPlan } from '../../api/testcases';
import type {
  TestPlan,
  TestPlanTransitionRequest,
  CreateTestPlanRequest,
} from '../../api/types/testcase';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';
import FormDialog from '../common/FormDialog.vue';

const props = defineProps<{ projectId: string }>();
const emit = defineEmits<{ open: [plan: TestPlan] }>();

const { items, loading, error, hasMore, loadMore, reload } = useCursorPage<TestPlan>({
  limit: 20,
  loader: (cursor, limit) => listTestPlans(props.projectId, limit, cursor),
});

// requirement status → permitted plan transition actions (tp-service state machine).
// Unknown statuses fall back to the full action set so nothing valid is hidden.
const PLAN_STATUS_ACTIONS: Record<string, readonly string[]> = {
  draft: ['submit', 'freeze', 'cancel'],
  submitted: ['approve', 'reject', 'cancel'],
  approved: ['activate', 'cancel'],
  ready: ['start_execution', 'cancel'],
  active: ['start_execution', 'cancel'],
  executing: ['complete', 'cancel'],
  frozen: ['complete', 'cancel'],
  completed: ['close'],
  canceled: ['cancel'],
};
const PLAN_ACTIONS: readonly string[] = [
  'submit',
  'approve',
  'reject',
  'activate',
  'start_execution',
  'complete',
  'cancel',
  'close',
  'freeze',
];

const ACTION_LABELS: Record<string, string> = {
  submit: '提交',
  approve: '批准',
  reject: '驳回',
  activate: '激活',
  start_execution: '开始执行',
  complete: '完成',
  cancel: '取消',
  close: '关闭',
  freeze: '冻结',
};

function planActions(status: string): readonly string[] {
  return PLAN_STATUS_ACTIONS[status] ?? PLAN_ACTIONS;
}
function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}
function scopeSummary(plan: TestPlan): string {
  return plan.scope?.length ? `范围 ${plan.scope.length} 项` : '（无范围）';
}

// Inline create dialog. Plan creation goes through the shared api module
// (`createTestPlan`), which attaches the `Idempotency-Key`.
const createVisible = ref(false);
const createSubmitting = ref(false);
const createError = ref<Error | null>(null);
const createModel = ref<CreateTestPlanRequest>({ owner_id: '' });

async function onCreateSubmit(): Promise<void> {
  createSubmitting.value = true;
  createError.value = null;
  try {
    await createTestPlan(props.projectId, createModel.value);
    createVisible.value = false;
    createModel.value = { owner_id: '' };
    await reload();
  } catch (e) {
    createError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    createSubmitting.value = false;
  }
}

// Transition handling (one in-flight action per plan, keyed by id).
const transitionErrors = ref<Record<string, string>>({});
async function applyTransition(plan: TestPlan, action: string): Promise<void> {
  transitionErrors.value = { ...transitionErrors.value, [plan.id]: '' };
  try {
    const payload: TestPlanTransitionRequest = { action };
    const updated = await transitionTestPlan(props.projectId, plan.id, payload, plan.version);
    const idx = items.value.findIndex((p) => p.id === plan.id);
    if (idx >= 0) items.value[idx] = updated;
  } catch (e) {
    transitionErrors.value = {
      ...transitionErrors.value,
      [plan.id]: e instanceof Error ? e.message : String(e),
    };
  }
}
</script>

<template>
  <section class="test-plan-list">
    <div class="test-plan-list__toolbar">
      <h2 class="text-h6">测试计划</h2>
      <v-btn color="primary" variant="flat" prepend-icon="mdi-plus" @click="createVisible = true">
        新建计划
      </v-btn>
    </div>

    <AsyncSection :loading="loading" :error="error" :empty="items.length === 0" empty-text="暂无测试计划">
      <table class="test-plan-list__table">
        <thead>
          <tr>
            <th>编号</th>
            <th>负责人</th>
            <th>状态</th>
            <th>范围</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in items" :key="p.id" class="test-plan-list__row" @click="emit('open', p)">
            <td>{{ p.business_no }}</td>
            <td>{{ p.owner_id || '—' }}</td>
            <td><StatusChip :status="p.status" /></td>
            <td>{{ scopeSummary(p) }}</td>
            <td>
              <v-btn
                v-for="a in planActions(p.status)"
                :key="a"
                size="x-small"
                variant="text"
                class="ma-1"
                :disabled="!!transitionErrors[p.id]"
                @click.stop="applyTransition(p, a)"
              >
                {{ actionLabel(a) }}
              </v-btn>
              <v-alert
                v-if="transitionErrors[p.id]"
                type="error"
                variant="tonal"
                density="compact"
                class="mt-1"
              >
                {{ transitionErrors[p.id] }}
              </v-alert>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="hasMore" class="test-plan-list__more">
        <v-btn :loading="loading" variant="text" @click="loadMore">加载更多</v-btn>
      </div>
    </AsyncSection>

    <FormDialog
      v-model="createVisible"
      title="新建测试计划"
      :submitting="createSubmitting"
      :error="createError"
      @submit="onCreateSubmit"
    >
      <v-text-field v-model="createModel.business_no" label="编号" />
      <v-text-field v-model="createModel.owner_id" label="负责人 ID" />
    </FormDialog>
  </section>
</template>
