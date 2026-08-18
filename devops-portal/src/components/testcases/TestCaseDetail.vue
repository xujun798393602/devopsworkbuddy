<script setup lang="ts">
/**
 * TestCaseDetail — test case inspector + version editor.
 *
 * Fetches the head via `getTestCase` (which carries `current_version_id`). Editing =
 * publishing a new immutable version through `createTestCaseVersion` (the api module
 * adds the `Idempotency-Key`; no `If-Match` is required for versions). The historical
 * version list is read through `listCaseVersions` and a single version via `getCaseVersion`.
 */
import { ref, watch } from 'vue';
import { getTestCase, createTestCaseVersion, listCaseVersions, getCaseVersion } from '../../api/testcases';
import type {
  TestCase,
  CreateTestCaseVersionRequest,
  TestStep,
  TestCaseVersion,
} from '../../api/types/testcase';
import AsyncSection from '../common/AsyncSection.vue';
import StatusChip from '../common/StatusChip.vue';
import FormDialog from '../common/FormDialog.vue';

const props = defineProps<{ modelValue: boolean; projectId: string; caseId: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>();

const detail = ref<TestCase | null>(null);
const loading = ref(false);
const error = ref<Error | null>(null);

// Immutable version history (read-only list + drill-down to a single version).
const versions = ref<TestCaseVersion[]>([]);
const versionsLoading = ref(false);
const versionsError = ref<Error | null>(null);
const selectedVersion = ref<TestCaseVersion | null>(null);
const versionDetailVisible = ref(false);

// Version editor dialog.
const editVisible = ref(false);
const steps = ref<TestStep[]>([]);
const source = ref<'design' | 'manual' | 'import' | 'automation'>('manual');
const editSubmitting = ref(false);
const editError = ref<Error | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    detail.value = await getTestCase(props.projectId, props.caseId);
    await loadVersions();
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    loading.value = false;
  }
}

async function loadVersions(): Promise<void> {
  versionsLoading.value = true;
  versionsError.value = null;
  try {
    const envelope = await listCaseVersions(props.projectId, props.caseId);
    versions.value = envelope.data.items;
  } catch (e) {
    versionsError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    versionsLoading.value = false;
  }
}

async function viewVersion(versionId: string): Promise<void> {
  versionsError.value = null;
  try {
    selectedVersion.value = await getCaseVersion(props.projectId, props.caseId, versionId);
    versionDetailVisible.value = true;
  } catch (e) {
    versionsError.value = e instanceof Error ? e : new Error(String(e));
  }
}

function startEdit(): void {
  steps.value = [];
  source.value = 'manual';
  editError.value = null;
  editVisible.value = true;
}

function addStep(): void {
  steps.value.push({ sequence: steps.value.length + 1, action: '', expected: '' });
}

function removeStep(index: number): void {
  steps.value.splice(index, 1);
}

async function onEditSubmit(): Promise<void> {
  if (!detail.value) return;
  editSubmitting.value = true;
  editError.value = null;
  try {
    const payload: CreateTestCaseVersionRequest = {
      steps: steps.value.length
        ? steps.value.map((s, i) => ({ ...s, sequence: i + 1 }))
        : [{ sequence: 1, action: '', expected: '' }],
      source: source.value,
    };
    await createTestCaseVersion(props.projectId, detail.value.id, payload);
    editVisible.value = false;
    await load();
  } catch (e) {
    editError.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    editSubmitting.value = false;
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
            <div class="tc-detail__meta">
              <StatusChip :status="detail.status" />
              <span>类型：{{ detail.type }}</span>
              <span>优先级：{{ detail.priority }}</span>
              <span>自动化：{{ detail.automation_mode }}</span>
              <span>负责人：{{ detail.owner_id || '—' }}</span>
            </div>
            <p class="tc-detail__refs">
              关联需求：{{ detail.requirement_refs.length ? detail.requirement_refs.join(', ') : '—' }}
            </p>
            <p class="text-caption">当前版本：{{ detail.current_version_id || '（未发布版本）' }}</p>

            <div class="tc-detail__actions">
              <v-btn variant="text" prepend-icon="mdi-pencil" @click="startEdit">编辑版本</v-btn>
            </div>

            <v-divider class="my-3" />
            <div class="tc-detail__versions">
              <div class="d-flex align-center">
                <h3 class="text-subtitle-1">历史版本</h3>
                <v-spacer />
                <span class="text-caption">{{ versions.length }} 个</span>
              </div>
              <v-alert
                v-if="versionsError"
                type="error"
                variant="tonal"
                density="compact"
                class="mt-2"
              >
                {{ versionsError.message }}
              </v-alert>
              <v-progress-linear v-if="versionsLoading" indeterminate color="primary" class="my-2" />
              <v-list v-else density="compact" lines="two" class="tc-detail__version-list">
                <v-list-item
                  v-for="v in versions"
                  :key="v.id"
                  :title="`v${v.version_no} · ${v.source}`"
                  :subtitle="`hash ${v.content_hash.slice(0, 8)} · ${v.steps.length} 步`"
                  @click="viewVersion(v.id)"
                />
                <v-list-item v-if="!versionsLoading && versions.length === 0" title="暂无版本" />
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
  </v-dialog>

  <FormDialog
    v-model="editVisible"
    title="编辑版本"
    :submitting="editSubmitting"
    :error="editError"
    @submit="onEditSubmit"
  >
    <v-select
      v-model="source"
      :items="['design', 'manual', 'import', 'automation']"
      label="来源"
    />
    <div v-for="(s, i) in steps" :key="i" class="tc-step">
      <v-text-field v-model="s.action" label="操作" density="compact" />
      <v-text-field v-model="s.expected" label="预期" density="compact" />
      <v-text-field v-model="s.test_data" label="测试数据" density="compact" />
      <v-btn icon="mdi-delete" size="small" variant="text" @click="removeStep(i)" />
    </div>
    <v-btn prepend-icon="mdi-plus" variant="text" size="small" @click="addStep">添加步骤</v-btn>
  </FormDialog>

  <v-dialog v-model="versionDetailVisible" max-width="640">
    <v-card>
      <v-card-title v-if="selectedVersion">版本 v{{ selectedVersion.version_no }}</v-card-title>
      <v-card-text v-if="selectedVersion">
        <p class="text-caption">来源：{{ selectedVersion.source }} · hash {{ selectedVersion.content_hash }}</p>
        <v-table density="compact">
          <thead>
            <tr><th>#</th><th>操作</th><th>预期</th><th>测试数据</th></tr>
          </thead>
          <tbody>
            <tr v-for="s in selectedVersion.steps" :key="s.sequence">
              <td>{{ s.sequence }}</td>
              <td>{{ s.action }}</td>
              <td>{{ s.expected }}</td>
              <td>{{ s.test_data ?? '—' }}</td>
            </tr>
            <tr v-if="selectedVersion.steps.length === 0">
              <td colspan="4" class="text-caption">无步骤</td>
            </tr>
          </tbody>
        </v-table>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="versionDetailVisible = false">关闭</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
