<script setup lang="ts">
/**
 * TestCaseForm — create dialog for a test case.
 *
 * Uses `useResourceForm`; `createTestCase` (api module) attaches the `Idempotency-Key`
 * automatically. Emits `created` with the persisted case. `requirement_refs` is edited
 * as a comma-separated string and split on submit.
 */
import { computed, watch } from 'vue';
import { useResourceForm } from '../../composables/useResourceForm';
import { createTestCase } from '../../api/testcases';
import type {
  TestCase,
  CreateTestCaseRequest,
  TestCaseType,
  TestCasePriority,
  TestCaseAutomationMode,
} from '../../api/types/testcase';
import FormDialog from '../common/FormDialog.vue';

const props = defineProps<{ modelValue: boolean; projectId: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; created: [testCase: TestCase] }>();

const TYPES: TestCaseType[] = ['functional', 'api', 'ui', 'android', 'android_tv', 'other'];
const PRIORITIES: TestCasePriority[] = ['p0', 'p1', 'p2', 'p3'];
const AUTOMATION: TestCaseAutomationMode[] = ['manual', 'automated', 'candidate'];

function emptyModel(): CreateTestCaseRequest {
  return {
    title: '',
    folder_id: '',
    owner_id: '',
    type: 'functional',
    priority: 'p2',
    automation_mode: 'manual',
    requirement_refs: [],
  };
}

const form = useResourceForm<CreateTestCaseRequest, TestCase>({
  empty: emptyModel,
  create: (payload) => createTestCase(props.projectId, payload),
});

const { visible, model, submitting, error, openCreate, close } = form;

/** Requirement references as a comma-separated string for the text field. */
const reqRefsText = computed<string>({
  get: () => (model.value.requirement_refs ?? []).join(','),
  set: (value: string) =>
    (model.value = {
      ...model.value,
      requirement_refs: value
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    }),
});

watch(
  () => props.modelValue,
  (open) => {
    if (open) openCreate();
    else close();
  },
);

watch(visible, (v) => {
  if (!v) emit('update:modelValue', false);
});

async function onSubmit(): Promise<void> {
  const result = await form.submit();
  if (result) emit('created', result);
}
</script>

<template>
  <FormDialog
    :model-value="visible"
    title="新建用例"
    :submitting="submitting"
    :error="error"
    @update:model-value="visible = $event"
    @submit="onSubmit"
  >
    <v-text-field v-model="model.title" label="标题" required />
    <v-text-field v-model="model.folder_id" label="目录 ID" />
    <v-text-field v-model="model.owner_id" label="负责人 ID" />
    <v-select v-model="model.type" :items="TYPES as string[]" label="类型" />
    <v-select v-model="model.priority" :items="PRIORITIES as string[]" label="优先级" />
    <v-select v-model="model.automation_mode" :items="AUTOMATION as string[]" label="自动化方式" />
    <v-text-field v-model="reqRefsText" label="关联需求 ID（逗号分隔）" hint="多个以逗号分隔" />
  </FormDialog>
</template>
