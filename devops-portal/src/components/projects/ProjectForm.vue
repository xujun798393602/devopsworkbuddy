<script setup lang="ts">
/**
 * ProjectForm — create-only project dialog.
 *
 * The project-service exposes no update endpoint, so this form only creates. It is a
 * controlled dialog driven by `v-model` (visible) and emits `saved` with the created
 * `Project` so the parent can refresh its list. `createProject` generates the required
 * `Idempotency-Key` itself (see src/api/projects.ts).
 */
import { ref, watch } from 'vue';
import { createProject } from '../../api/projects';
import type { Project, CreateProjectRequest } from '../../api/types/project';
import FormDialog from '../common/FormDialog.vue';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [project: Project] }>();

const model = ref<CreateProjectRequest>({ name: '', description: '', owner_id: '' });
const submitting = ref(false);
const error = ref<Error | null>(null);

function reset(): void {
  model.value = { name: '', description: '', owner_id: '' };
  error.value = null;
}

// Reset the form each time the dialog opens.
watch(
  () => props.modelValue,
  (open) => {
    if (open) reset();
  },
);

async function onSubmit(): Promise<void> {
  submitting.value = true;
  error.value = null;
  try {
    const created = await createProject(model.value);
    emit('update:modelValue', false);
    emit('saved', created);
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <FormDialog
    :model-value="props.modelValue"
    title="新建项目"
    :submitting="submitting"
    :error="error"
    @update:model-value="emit('update:modelValue', $event)"
    @submit="onSubmit"
  >
    <v-text-field
      v-model="model.name"
      label="项目名称"
      :rules="[(v: string) => !!v || '项目名称为必填']"
      required
    />
    <v-textarea v-model="model.description" label="描述" rows="3" auto-grow />
    <v-text-field v-model="model.owner_id" label="负责人 ID" placeholder="留空则取当前登录用户" />
  </FormDialog>
</template>
