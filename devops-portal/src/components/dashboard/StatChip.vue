<script setup lang="ts">
/** Small tonal pill used by the statistic cards. */
import type { ChipTone } from './types';

defineProps<{ tone?: ChipTone }>();
</script>

<template>
  <span class="chip" :class="`chip--${tone ?? 'neutral'}`"><slot /></span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 0.75rem;
  line-height: 1.6;
  white-space: nowrap;
}
.chip--neutral {
  color: var(--text);
  background: var(--chip-bg);
}
.chip--error {
  color: var(--err-fg);
  background: var(--err-bg);
}
.chip--warn {
  color: var(--warn-fg);
  background: var(--warn-bg);
}
.chip--info {
  color: var(--info-fg);
  background: var(--info-bg);
}
.chip--ok {
  color: var(--ok-fg);
  background: var(--ok-bg);
}
</style>
