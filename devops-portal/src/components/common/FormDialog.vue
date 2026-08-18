<script setup lang="ts">
/**
 * FormDialog — reusable dialog chrome for create / edit forms.
 *
 * Owns the dialog frame, the title, an optional error alert, and the Cancel / Save
 * actions; the form fields live in the default slot. `v-model` controls visibility and
 * `submit` fires when Save is pressed (Save is disabled + shows a spinner while
 * `submitting` is true). Kept thin so domain forms only supply their fields.
 */
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title: string;
    submitting?: boolean;
    error?: Error | string | null;
    submitLabel?: string;
    cancelLabel?: string;
    persistent?: boolean;
  }>(),
  {
    submitting: false,
    error: null,
    submitLabel: '保存',
    cancelLabel: '取消',
    persistent: true,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  submit: [];
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
});

const errorMessage = computed(() =>
  props.error ? (props.error instanceof Error ? props.error.message : String(props.error)) : '',
);

function onSubmit(): void {
  emit('submit');
}
</script>

<template>
  <v-dialog v-model="visible" :persistent="persistent" max-width="640">
    <v-card>
      <v-card-title>{{ title }}</v-card-title>
      <v-card-text>
        <v-alert v-if="errorMessage" type="error" variant="tonal" class="mb-3" role="alert">
          {{ errorMessage }}
        </v-alert>
        <slot />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn :disabled="submitting" variant="text" @click="visible = false">{{ cancelLabel }}</v-btn>
        <v-btn :loading="submitting" color="primary" variant="flat" @click="onSubmit">
          {{ submitLabel }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
