<script setup lang="ts">
/**
 * DefectForm — create / edit dialog for a defect.
 *
 * Uses `useResourceForm` so create and edit share one model + submit path:
 *  - create → `createDefect` (sends `Idempotency-Key`)
 *  - edit   → `updateDefect` (sends `If-Match` from the defect `version`; body limited
 *             to `DEFECT_PATCHABLE_FIELDS` — see src/api/types/defect.ts).
 *
 * `expected_result` / `actual_result` / `reproduction_steps` are only editable on
 * create, because the list/detail response omits them (td_service/app.py `_serialize`).
 * Reproduction steps are edited as a newline-joined string and split on submit.
 */
import { computed, ref, watch } from 'vue';
import { useResourceForm, type UseResourceForm } from '../../composables/useResourceForm';
import { createDefect, updateDefect } from '../../api/defects';
import type {
  Defect,
  CreateDefectRequest,
  UpdateDefectRequest,
  DefectSeverity,
  DefectPriority,
  DefectType,
} from '../../api/types/defect';
import FormDialog from '../common/FormDialog.vue';

const props = defineProps<{ modelValue: boolean; projectId: string; defect?: Defect | null }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [defect: Defect] }>();

const SEVERITIES: DefectSeverity[] = ['blocker', 'critical', 'major', 'minor', 'trivial'];
const PRIORITIES: DefectPriority[] = ['p0', 'p1', 'p2', 'p3'];
const TYPES: DefectType[] = [
  'functional',
  'performance',
  'security',
  'compatibility',
  'usability',
  'data',
  'configuration',
  'other',
];

function emptyModel(): CreateDefectRequest {
  return {
    title: '',
    description: '',
    severity: 'major',
    priority: 'p2',
    defect_type: 'functional',
    expected_result: '',
    actual_result: '',
    reproduction_steps: [],
  };
}

/** Build the editable model from an existing defect (patchable fields only). */
function toModel(d: Defect): CreateDefectRequest {
  return {
    title: d.title,
    description: d.description,
    severity: d.severity as DefectSeverity | string,
    priority: d.priority as DefectPriority | string,
    defect_type: d.defect_type as DefectType | string,
  };
}

const form: UseResourceForm<CreateDefectRequest, Defect> = useResourceForm<CreateDefectRequest, Defect>({
  empty: emptyModel,
  toResource: toModel,
  versionOf: (d) => d.version,
  create: (payload) => createDefect(props.projectId, payload),
  update: (payload, version) =>
    updateDefect(props.projectId, form.editing.value?.id ?? '', payload, version),
});

const { visible, model, submitting, error, isEdit, openCreate, openEdit, close } = form;

/** Reproduction steps as a newline-separated string for the textarea. */
const reproText = computed<string>({
  get: () => (model.value.reproduction_steps ?? []).join('\n'),
  set: (value: string) =>
    (model.value = {
      ...model.value,
      reproduction_steps: value
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean),
    }),
});

// Open in the right mode when the dialog is shown by the parent.
watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      if (props.defect) openEdit(props.defect);
      else openCreate();
    } else {
      close();
    }
  },
);

// Propagate internal close back to the parent's `v-model`.
watch(visible, (v) => {
  if (!v) emit('update:modelValue', false);
});

async function onSubmit(): Promise<void> {
  const result = await form.submit();
  if (result) emit('saved', result);
}
</script>

<template>
  <FormDialog
    :model-value="visible"
    :title="isEdit ? '编辑缺陷' : '新建缺陷'"
    :submitting="submitting"
    :error="error"
    @update:model-value="visible = $event"
    @submit="onSubmit"
  >
    <v-text-field v-model="model.title" label="标题" required />
    <v-textarea v-model="model.description" label="描述" rows="3" auto-grow />
    <v-select v-model="model.severity" :items="SEVERITIES as string[]" label="严重度" />
    <v-select v-model="model.priority" :items="PRIORITIES as string[]" label="优先级" />
    <v-select v-model="model.defect_type" :items="TYPES as string[]" label="类型" />
    <template v-if="!isEdit">
      <v-textarea v-model="model.expected_result" label="期望结果" rows="2" auto-grow />
      <v-textarea v-model="model.actual_result" label="实际结果" rows="2" auto-grow />
      <v-textarea v-model="reproText" label="复现步骤（每行一条）" rows="3" auto-grow />
    </template>
  </FormDialog>
</template>
