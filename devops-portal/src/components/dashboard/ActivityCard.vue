<script setup lang="ts">
import type { ActivityBlock } from '../../api/portal';
import DashboardCard from './DashboardCard.vue';

defineProps<{
  activity: ActivityBlock;
  loading?: boolean;
  degraded?: boolean;
}>();

function occurredLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}
</script>

<template>
  <DashboardCard
    title="最近动态"
    :loading="loading"
    :degraded="degraded"
    :empty="activity.items.length === 0"
    empty-text="近 7 天暂无相关动态"
  >
    <p class="activity__source">来源：{{ activity.source === 'audit' ? '审计日志' : '通知' }}</p>
    <ol class="activity">
      <li v-for="item in activity.items" :key="item.id" class="activity__item">
        <p class="activity__summary">{{ item.summary }}</p>
        <p class="activity__meta">
          {{ item.actor_name }} · {{ item.action }} · {{ occurredLabel(item.occurred_at) }}
        </p>
      </li>
    </ol>
  </DashboardCard>
</template>

<style scoped>
.activity__source {
  margin: 0 0 8px;
  font-size: 0.75rem;
  color: var(--muted);
}
.activity {
  list-style: none;
  margin: 0;
  padding: 0;
}
.activity__item {
  padding: 8px 0;
  border-bottom: 1px solid var(--card-border);
}
.activity__item:last-child {
  border-bottom: 0;
}
.activity__summary {
  margin: 0;
  font-size: 0.875rem;
}
.activity__meta {
  margin: 2px 0 0;
  font-size: 0.75rem;
  color: var(--muted);
}
</style>
