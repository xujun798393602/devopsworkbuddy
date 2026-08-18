<script setup lang="ts">
/**
 * AsyncSection — consistent loading / error / empty / content states for any async block.
 *
 * Mirrors the portal dashboard's error contract: the failure branch renders
 * `role="alert"` so cross-page error assertions stay uniform. Slots (in priority order):
 * `loading` (default: indeterminate progress bar), `error` (falls back to text),
 * `empty` (falls back to `emptyText`), and the default slot for the loaded content.
 */
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    loading?: boolean;
    error?: Error | string | null;
    empty?: boolean;
    emptyText?: string;
  }>(),
  {
    loading: false,
    error: null,
    empty: false,
    emptyText: '暂无数据',
  },
);

const errorMessage = computed(() =>
  props.error ? (props.error instanceof Error ? props.error.message : String(props.error)) : '',
);
</script>

<template>
  <div class="async-section">
    <div v-if="loading" class="async-section__loading" role="status" aria-live="polite">
      <slot name="loading">
        <v-progress-linear indeterminate color="primary" />
      </slot>
    </div>
    <v-alert
      v-else-if="errorMessage"
      type="error"
      variant="tonal"
      role="alert"
      class="async-section__error"
    >
      {{ errorMessage }}
    </v-alert>
    <div v-else-if="empty" class="async-section__empty">
      <slot name="empty">{{ emptyText }}</slot>
    </div>
    <slot v-else />
  </div>
</template>
