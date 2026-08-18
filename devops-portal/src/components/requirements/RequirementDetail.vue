<script setup lang="ts">
/**
 * RequirementDetail — read-only inspector + inline edit (PATCH) + workflow transitions.
 *
 * Opens only when `modelValue` flips true, then fetches the full requirement via
 * `getRequirement`. The optimistic-concurrency token is read from `data.version`
 * (the gateway drops the ETag header, so the token always comes from the body —
 * see src/api/envelope.ts).
 *
 * PATCH / transitions are sent through the api module, which attaches the quoted
 * `If-Match` header and the `Idempotency-Key` automatically — this view only forwards
 * the `version` number. The review / baseline / change-request sub-modules are wired
 * to the shared api module (`list*` on open, `create*` on submit); the module attaches
 * the `Idempotency-Key` to every create call.
 */
import { ref, watch } from 'vue';
import {
  getRequirement,
  updateRequirement,
  transitionRequirement,
  listRequirementReviews,
  createRequirementReview,
  listRequirementBaselines,
  createRequirementBaseline,
  listChangeRequests,
  createChangeRequest,
} from '../../api/requirements';
import type {
  Requirement,
  UpdateRequirementRequest,
  RequirementTransitionRequest,
  RequirementStatus,
  RequirementReview,
  CreateRequirementReviewRequest,
  RequirementBaseline,
  CreateRequirementBaselineRequest,
  ChangeRequest,
  CreateChangeRequestRequest,
} from '../../api/types/requirement';
import { REASON_REQUIRED_ACTIONS } from '../../api/types/requirement';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';
import FormDialog from '../common/FormDialog.vue';
import { useResourceForm } from '../../composables/useResourceForm';

const props = defineProps<{ modelValue: boolean; projectId: string; requirementId: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; updated: [requirement: Requirement] }>();

// requirement status → permitted transition actions (source of truth:
// requirement_service/domain.py `Requirement.transition`). Unknown statuses fall back
// to the full action set so no valid transition is ever hidden.
const REQUIREMENT_STATUS_ACTIONS: Record<RequirementStatus | string, readonly string[]> = {
  draft: ['submit_review', 'cancel'],
  in_review: ['approve', 'reject', 'cancel'],
  rejected: ['return_to_draft', 'reopen'],
  approved: ['activate', 'complete', 'cancel'],
  active: ['complete', 'reopen', 'cancel'],
  completed: ['reopen'],
  canceled: ['reopen'],
};
const ALL_ACTIONS: readonly string[] = [
  'submit_review',
  'approve',
  'reject',
  'return_to_draft',
  'activate',
  'complete',
  'cancel',
  'reopen',
];

const ACTION_LABELS: Record<string, string> = {
  submit_review: '提交评审',
  approve: '批准',
  reject: '驳回',
  return_to_draft: '退回草稿',
  activate: '激活',
  complete: '完成',
  cancel: '取消',
  reopen: '重新打开',
};

const detail = ref<Requirement | null>(null);
const loading = ref(false);
const error = ref<Error | null>(null);

// Inline edit region (PATCH). The api module adds the quoted If-Match from `version`.
const edit = useResourceForm<UpdateRequirementRequest, Requirement>({
  empty: () => ({
    title: '',
    description: '',
    priority: 'p2',
    owner_id: '',
    release_version_id: '',
    parent_id: null,
    acceptance_criteria: [],
  }),
  toResource: (r) => ({
    title: r.title,
    description: r.description,
    priority: r.priority,
    owner_id: r.owner_id,
    release_version_id: r.release_version_id,
    parent_id: r.parent_id,
    acceptance_criteria: r.acceptance_criteria,
  }),
  versionOf: (r) => r.version,
  create: async () => {
    throw new Error('create not supported in detail');
  },
  update: (payload, version) => updateRequirement(props.projectId, props.requirementId, payload, version),
});

const {
  visible: editVisible,
  model: editModel,
  submitting: editSubmitting,
  error: editError,
  openEdit,
  close: closeEdit,
} = edit;

// Transition dialog (reopen requires a mandatory reason).
const transitionDialog = ref(false);
const transitionReason = ref('');
const transitionSubmitting = ref(false);
const transitionError = ref<Error | null>(null);
const transitionAction = ref<string | null>(null);

function availableActions(status: RequirementStatus | string): readonly string[] {
  return REQUIREMENT_STATUS_ACTIONS[status] ?? ALL_ACTIONS;
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    detail.value = await getRequirement(props.projectId, props.requirementId);
    await Promise.all([loadReviews(), loadBaselines(), loadChanges()]);
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    loading.value = false;
  }
}

function startEdit(): void {
  if (detail.value) openEdit(detail.value);
}

async function onEditSubmit(): Promise<void> {
  const result = await edit.submit();
  if (result) {
    detail.value = result;
    emit('updated', result);
  }
}

function openTransition(action: string): void {
  transitionReason.value = '';
  transitionError.value = null;
  if (REASON_REQUIRED_ACTIONS.includes(action)) {
    transitionAction.value = action;
    transitionDialog.value = true;
  } else {
    void applyTransition(action, '');
  }
}

async function applyTransition(action: string, reason: string): Promise<void> {
  if (!detail.value) return;
  transitionSubmitting.value = true;
  transitionError.value = null;
  try {
    const payload: RequirementTransitionRequest = { action };
    if (reason) payload.reason = reason;
    if (action === 'reopen') payload.privileged = true;
    const updated = await transitionRequirement(props.projectId, props.requirementId, payload, detail.value.version);
    detail.value = updated;
    emit('updated', updated);
    transitionDialog.value = false;
  } catch (e) {
    transitionError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    transitionSubmitting.value = false;
  }
}

// --- Requirement sub-modules: reviews / baselines / change-requests ---------------
// Each sub-module owns a list (loaded on open) plus an inline create dialog. The
// shared api module attaches the `Idempotency-Key` to every create call.

// Reviews.
const reviews = ref<RequirementReview[]>([]);
const reviewsLoading = ref(false);
const reviewsError = ref<Error | null>(null);
const reviewDialog = ref(false);
const reviewModel = ref<CreateRequirementReviewRequest>({ reviewer_id: '', decision: 'pending' });
const reviewSubmitting = ref(false);
const reviewError = ref<Error | null>(null);

async function loadReviews(): Promise<void> {
  reviewsLoading.value = true;
  reviewsError.value = null;
  try {
    const envelope = await listRequirementReviews(props.projectId, props.requirementId);
    reviews.value = envelope.data.items;
  } catch (e) {
    reviewsError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    reviewsLoading.value = false;
  }
}

async function onCreateReview(): Promise<void> {
  if (!detail.value) return;
  reviewSubmitting.value = true;
  reviewError.value = null;
  try {
    await createRequirementReview(props.projectId, detail.value.id, { ...reviewModel.value });
    reviewDialog.value = false;
    reviewModel.value = { reviewer_id: '', decision: 'pending' };
    await loadReviews();
  } catch (e) {
    reviewError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    reviewSubmitting.value = false;
  }
}

// Baselines.
const baselines = ref<RequirementBaseline[]>([]);
const baselinesLoading = ref(false);
const baselinesError = ref<Error | null>(null);
const baselineDialog = ref(false);
const baselineModel = ref<CreateRequirementBaselineRequest>({ baseline_no: '' });
const baselineSubmitting = ref(false);
const baselineError = ref<Error | null>(null);

async function loadBaselines(): Promise<void> {
  baselinesLoading.value = true;
  baselinesError.value = null;
  try {
    const envelope = await listRequirementBaselines(props.projectId, props.requirementId);
    baselines.value = envelope.data.items;
  } catch (e) {
    baselinesError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    baselinesLoading.value = false;
  }
}

async function onCreateBaseline(): Promise<void> {
  if (!detail.value) return;
  baselineSubmitting.value = true;
  baselineError.value = null;
  try {
    await createRequirementBaseline(props.projectId, detail.value.id, { ...baselineModel.value });
    baselineDialog.value = false;
    baselineModel.value = { baseline_no: '' };
    await loadBaselines();
  } catch (e) {
    baselineError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    baselineSubmitting.value = false;
  }
}

// Change requests.
const changes = ref<ChangeRequest[]>([]);
const changesLoading = ref(false);
const changesError = ref<Error | null>(null);
const changeDialog = ref(false);
const changeModel = ref<CreateChangeRequestRequest>({ title: '' });
const changeSubmitting = ref(false);
const changeError = ref<Error | null>(null);

async function loadChanges(): Promise<void> {
  changesLoading.value = true;
  changesError.value = null;
  try {
    const envelope = await listChangeRequests(props.projectId, props.requirementId);
    changes.value = envelope.data.items;
  } catch (e) {
    changesError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    changesLoading.value = false;
  }
}

async function onCreateChange(): Promise<void> {
  if (!detail.value) return;
  changeSubmitting.value = true;
  changeError.value = null;
  try {
    await createChangeRequest(props.projectId, detail.value.id, { ...changeModel.value });
    changeDialog.value = false;
    changeModel.value = { title: '' };
    await loadChanges();
  } catch (e) {
    changeError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    changeSubmitting.value = false;
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
    max-width="760"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <v-card>
      <v-card-title v-if="detail">{{ detail.business_no }} · {{ detail.title }}</v-card-title>
      <v-card-text>
        <AsyncSection :loading="loading" :error="error">
          <template v-if="detail">
            <div class="req-detail__meta">
              <StatusChip :status="detail.status" />
              <span>类型：{{ detail.type }}</span>
              <span>优先级：{{ detail.priority }}</span>
              <span>负责人：{{ detail.owner_id || '—' }}</span>
              <span>基线：{{ detail.baseline_status }}</span>
            </div>
            <p class="req-detail__desc">{{ detail.description || '（无描述）' }}</p>

            <div class="req-detail__actions">
              <v-btn variant="text" prepend-icon="mdi-pencil" @click="startEdit">编辑</v-btn>
            </div>

            <!-- Inline PATCH form (no nested dialog). -->
            <div v-if="editVisible" class="req-detail__edit">
              <v-alert v-if="editError" type="error" variant="tonal" class="mb-2" role="alert">
                {{ editError.message }}
              </v-alert>
              <v-text-field v-model="editModel.title" label="标题" />
              <v-textarea v-model="editModel.description" label="描述" rows="3" auto-grow />
              <v-select v-model="editModel.priority" :items="['p0', 'p1', 'p2', 'p3']" label="优先级" />
              <v-text-field v-model="editModel.owner_id" label="负责人 ID" />
              <div class="req-detail__edit-actions">
                <v-btn variant="text" :disabled="editSubmitting" @click="closeEdit()">取消</v-btn>
                <v-btn color="primary" variant="flat" :loading="editSubmitting" @click="onEditSubmit">保存</v-btn>
              </div>
            </div>

            <h4 class="mt-3">流转</h4>
            <div class="req-detail__transitions">
              <v-btn
                v-for="a in availableActions(detail.status)"
                :key="a"
                size="small"
                variant="outlined"
                class="ma-1"
                @click="openTransition(a)"
              >
                {{ actionLabel(a) }}
              </v-btn>
            </div>

            <h4 class="mt-4">评审 / 基线 / 变更请求</h4>

            <!-- Reviews sub-module -->
            <div class="req-submodule">
              <div class="d-flex align-center">
                <h5 class="text-subtitle-2">评审</h5>
                <v-spacer />
                <v-btn size="small" variant="text" prepend-icon="mdi-plus" @click="reviewDialog = true">
                  新建
                </v-btn>
              </div>
              <v-alert
                v-if="reviewsError"
                type="error"
                variant="tonal"
                density="compact"
                class="mt-2"
              >
                {{ reviewsError.message }}
              </v-alert>
              <v-progress-linear v-if="reviewsLoading" indeterminate color="primary" class="my-2" />
              <v-list v-else density="compact" lines="two" class="req-submodule__list">
                <v-list-item
                  v-for="r in reviews"
                  :key="r.id"
                  :title="`${r.reviewer_id} · ${r.decision}`"
                  :subtitle="r.comment ?? '（无备注）'"
                />
                <v-list-item v-if="!reviewsLoading && reviews.length === 0" title="暂无评审" />
              </v-list>
            </div>

            <!-- Baselines sub-module -->
            <div class="req-submodule">
              <div class="d-flex align-center">
                <h5 class="text-subtitle-2">基线</h5>
                <v-spacer />
                <v-btn size="small" variant="text" prepend-icon="mdi-plus" @click="baselineDialog = true">
                  新建
                </v-btn>
              </div>
              <v-alert
                v-if="baselinesError"
                type="error"
                variant="tonal"
                density="compact"
                class="mt-2"
              >
                {{ baselinesError.message }}
              </v-alert>
              <v-progress-linear v-if="baselinesLoading" indeterminate color="primary" class="my-2" />
              <v-list v-else density="compact" lines="two" class="req-submodule__list">
                <v-list-item v-for="b in baselines" :key="b.id">
                  <template #prepend>
                    <StatusChip :status="b.status" />
                  </template>
                  <v-list-item-title>{{ b.baseline_no }}</v-list-item-title>
                  <v-list-item-subtitle>v{{ b.version }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="!baselinesLoading && baselines.length === 0" title="暂无基线" />
              </v-list>
            </div>

            <!-- Change-requests sub-module -->
            <div class="req-submodule">
              <div class="d-flex align-center">
                <h5 class="text-subtitle-2">变更请求</h5>
                <v-spacer />
                <v-btn size="small" variant="text" prepend-icon="mdi-plus" @click="changeDialog = true">
                  新建
                </v-btn>
              </div>
              <v-alert
                v-if="changesError"
                type="error"
                variant="tonal"
                density="compact"
                class="mt-2"
              >
                {{ changesError.message }}
              </v-alert>
              <v-progress-linear v-if="changesLoading" indeterminate color="primary" class="my-2" />
              <v-list v-else density="compact" lines="two" class="req-submodule__list">
                <v-list-item v-for="c in changes" :key="c.id">
                  <template #prepend>
                    <StatusChip :status="c.status" />
                  </template>
                  <v-list-item-title>{{ c.title }}</v-list-item-title>
                  <v-list-item-subtitle>v{{ c.version }}</v-list-item-subtitle>
                </v-list-item>
                <v-list-item v-if="!changesLoading && changes.length === 0" title="暂无变更请求" />
              </v-list>
            </div>
          </template>
        </AsyncSection>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="emit('update:modelValue', false)">关闭</v-btn>
      </v-card-actions>
    </v-card>

    <!-- reopen reason dialog -->
    <v-dialog v-model="transitionDialog" max-width="480">
      <v-card>
        <v-card-title>重新打开需求</v-card-title>
        <v-card-text>
          <v-textarea
            v-model="transitionReason"
            label="原因（必填）"
            rows="3"
            auto-grow
            :rules="[(v: string) => !!v.trim() || '请填写原因']"
          />
          <v-alert v-if="transitionError" type="error" variant="tonal">{{ transitionError.message }}</v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="transitionDialog = false">取消</v-btn>
          <v-btn
            :loading="transitionSubmitting"
            color="primary"
            variant="flat"
            :disabled="!transitionReason.trim()"
            @click="applyTransition('reopen', transitionReason)"
          >
            提交
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- create review dialog -->
    <FormDialog
      v-model="reviewDialog"
      title="新建评审"
      :submitting="reviewSubmitting"
      :error="reviewError"
      @submit="onCreateReview"
    >
      <v-text-field v-model="reviewModel.reviewer_id" label="评审人 ID" />
      <v-select
        v-model="reviewModel.decision"
        :items="(['pending', 'approved', 'rejected'] as const)"
        label="结论"
      />
      <v-textarea v-model="reviewModel.comment" label="备注" rows="2" auto-grow />
    </FormDialog>

    <!-- create baseline dialog -->
    <FormDialog
      v-model="baselineDialog"
      title="新建基线"
      :submitting="baselineSubmitting"
      :error="baselineError"
      @submit="onCreateBaseline"
    >
      <v-text-field v-model="baselineModel.baseline_no" label="基线号" />
      <v-text-field v-model="baselineModel.status" label="状态（可选）" />
    </FormDialog>

    <!-- create change-request dialog -->
    <FormDialog
      v-model="changeDialog"
      title="新建变更请求"
      :submitting="changeSubmitting"
      :error="changeError"
      @submit="onCreateChange"
    >
      <v-text-field v-model="changeModel.title" label="标题" />
      <v-text-field v-model="changeModel.status" label="状态（可选）" />
    </FormDialog>
  </v-dialog>
</template>
