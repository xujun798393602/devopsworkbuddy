<script setup lang="ts">
/**
 * StatusChip — a small colour-coded chip for any domain status literal.
 *
 * The colour is resolved from a built-in map covering project / requirement / defect
 * statuses; a caller may override it with the `color` prop. Falls back to the default
 * chip colour for unknown statuses so the label is always legible.
 */
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    status: string;
    label?: string;
    color?: string;
    size?: 'x-small' | 'small' | 'default' | 'large';
  }>(),
  {
    label: '',
    color: '',
    size: 'small',
  },
);

/** status literal → Vuetify colour. Shared across the four management pages. */
const STATUS_COLORS: Record<string, string> = {
  // defect
  new: 'grey',
  assigned: 'info',
  in_progress: 'primary',
  fixed: 'teal',
  pending_verification: 'amber',
  closed: 'success',
  reopened: 'orange-darken-1',
  rejected: 'error',
  duplicate: 'grey-darken-1',
  // requirement
  draft: 'grey',
  in_review: 'info',
  approved: 'light-blue',
  active: 'primary',
  completed: 'success',
  canceled: 'grey-darken-1',
  // project
  archived: 'grey',
};

const resolvedColor = computed(() => props.color || STATUS_COLORS[props.status] || 'default');
const displayLabel = computed(() => props.label || props.status);
</script>

<template>
  <v-chip :color="resolvedColor" :size="size" variant="flat" label>{{ displayLabel }}</v-chip>
</template>
