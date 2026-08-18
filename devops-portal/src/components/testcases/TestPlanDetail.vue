<script setup lang="ts">
/**
 * TestPlanDetail — test plan inspector + transition region.
 *
 * Fetches the plan via `getTestPlan` and exposes the same status-derived transition
 * actions as `TestPlanList`. The shared api module attaches the quoted `If-Match` and
 * the `Idempotency-Key`; this view only forwards the `version`.
 */
import { ref, watch } from 'vue';
import { getTestPlan, transitionTestPlan } from '../../api/testcases';
import type { TestPlan, TestPlanTransitionRequest } from '../../api/types/testcase';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';

const props = defineProps<{ modelValue: boolean; projectId: string; planId: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; updated: [plan: TestPlan] }>();

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

const detail = ref<TestPlan | null>(null);
const loading = ref(false);
const error = ref<Error | null>(null);
const transitionError = ref<string | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    detail.value = await getTestPlan(props.projectId, props.planId);
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    loading.value = false;
  }
}

async function applyTransition(action: string): Promise<void> {
  if (!detail.value) return;
  transitionError.value = null;
  try {
    const payload: TestPlanTransitionRequest = { action };
    const updated = await transitionTestPlan(props.projectId, detail.value.id, payload, detail.value.version);
    detail.value = updated;
    emit('updated', updated);
  } catch (e) {
    transitionError.value = e instanceof Error ? e.message : String(e);
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      detail.value = null;
      void load();
    }
  },
);
</script>

<template>
  <v-dialog
    :model-value="props.modelValue"
    max-width="720"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <v-card>
      <v-card-title v-if="detail">{{ detail.business_no }}</v-card-title>
      <v-card-text>
        <AsyncSection :loading="loading" :error="error">
          <template v-if="detail">
            <div class="tp-detail__meta">
              <StatusChip :status="detail.status" />
              <span>负责人：{{ detail.owner_id || '—' }}</span>
              <span>版本：{{ detail.version }}</span>
            </div>
            <p class="text-caption">范围摘要：{{ detail.scope?.length ?? 0 }} 项</p>

            <h4 class="mt-3">流转</h4>
            <div class="tp-detail__transitions">
              <v-btn
                v-for="a in planActions(detail.status)"
                :key="a"
                size="small"
                variant="outlined"
                class="ma-1"
                @click="applyTransition(a)"
              >
                {{ actionLabel(a) }}
              </v-btn>
            </div>
            <v-alert v-if="transitionError" type="error" variant="tonal" class="mt-2" role="alert">
              {{ transitionError }}
            </v-alert>
          </template>
        </AsyncSection>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="emit('update:modelValue', false)">关闭</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
