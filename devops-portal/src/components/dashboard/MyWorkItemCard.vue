<script setup lang="ts">
/** Generic single-list card used by the four "my work" sub-cards. */
import DashboardCard from './DashboardCard.vue';
import type { DisplayItem } from './types';

defineProps<{
  title: string;
  items: DisplayItem[];
  count: number;
  loading?: boolean;
  degraded?: boolean;
  emptyText?: string;
}>();
</script>

<template>
  <DashboardCard
    :title="title"
    :loading="loading"
    :degraded="degraded"
    :empty="items.length === 0"
    :empty-text="emptyText"
  >
    <ul class="worklist">
      <li v-for="it in items" :key="it.id" class="worklist__item">
        <div class="worklist__text">
          <p class="worklist__primary">{{ it.primary }}</p>
          <p class="worklist__secondary">{{ it.secondary }}</p>
        </div>
        <span v-if="it.chip" class="worklist__chip" :class="`worklist__chip--${it.chipTone ?? 'info'}`">
          {{ it.chip }}
        </span>
      </li>
    </ul>
    <p class="worklist__meta">{{ items.length }} / 共 {{ count }}</p>
  </DashboardCard>
</template>

<style scoped>
.worklist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.worklist__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--card-border);
}
.worklist__item:last-child {
  border-bottom: 0;
}
.worklist__text {
  min-width: 0;
  flex: 1;
}
.worklist__primary {
  margin: 0;
  font-size: 0.875rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.worklist__secondary {
  margin: 2px 0 0;
  font-size: 0.75rem;
  color: var(--muted);
}
.worklist__chip {
  flex: none;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
}
.worklist__chip--neutral {
  color: var(--text);
  background: var(--chip-bg);
}
.worklist__chip--error {
  color: var(--err-fg);
  background: var(--err-bg);
}
.worklist__chip--info {
  color: var(--info-fg);
  background: var(--info-bg);
}
.worklist__chip--warn {
  color: var(--warn-fg);
  background: var(--warn-bg);
}
.worklist__chip--ok {
  color: var(--ok-fg);
  background: var(--ok-bg);
}
.worklist__meta {
  margin: 8px 0 0;
  font-size: 0.75rem;
  color: var(--muted);
}
</style>
