<script setup lang="ts">
/**
 * RequirementForm — create dialog for a requirement.
 *
 * Uses `useResourceForm` for state + submit. `createRequirement` (api module) attaches
 * the `Idempotency-Key` automatically, so this view only forwards the payload. Emits
 * `created` with the persisted requirement so a parent list can refresh. Acceptance
 * criteria are entered one-per-line and mapped to `{ text }` rows on submit.
 */
import { computed, watch } from 'vue';
import { useResourceForm } from '../../composables/useResourceForm';
import { createRequirement } from '../../api/requirements';
import type {
  Requirement,
  CreateRequirementRequest,
  RequirementType,
  RequirementPriority,
} from '../../api/types/requirement';
import FormDialog from '../common/FormDialog.vue';

const props = defineProps<{ modelValue: boolean; projectId: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; created: [requirement: Requirement] }>();

const TYPES: RequirementType[] = ['epic', 'feature', 'user_story', 'fr', 'nfr', 'ac'];
const PRIORITIES: RequirementPriority[] = ['p0', 'p1', 'p2', 'p3'];

function emptyModel(): CreateRequirementRequest {
  return {
    title: '',
    type: 'feature',
    priority: 'p2',
    owner_id: '',
    release_version_id: '',
    description: '',
    acceptance_criteria: [],
  };
}

const form = useResourceForm<CreateRequirementRequest, Requirement>({
  empty: emptyModel,
  // RequirementForm is create-only; edit lives in RequirementDetail.
  create: (payload) => createRequirement(props.projectId, payload),
});

const { visible, model, submitting, error, openCreate, close } = form;

/** Acceptance criteria as a newline-joined string for the textarea. */
const acText = computed<string>({
  get: () => (model.value.acceptance_criteria ?? []).map((c) => (c.text ?? '')).join('\n'),
  set: (value: string) =>
    (model.value = {
      ...model.value,
      acceptance_criteria: value
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((text) => ({ text })),
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
    title="新建需求"
    :submitting="submitting"
    :error="error"
    @update:model-value="visible = $event"
    @submit="onSubmit"
  >
    <v-text-field v-model="model.title" label="标题" required />
    <v-select v-model="model.type" :items="TYPES as string[]" label="类型" />
    <v-select v-model="model.priority" :items="PRIORITIES as string[]" label="优先级" />
    <v-text-field v-model="model.owner_id" label="负责人 ID" />
    <v-textarea v-model="model.description" label="描述" rows="3" auto-grow />
    <v-textarea v-model="acText" label="验收标准（每行一条）" rows="3" auto-grow />
  </FormDialog>
</template>
