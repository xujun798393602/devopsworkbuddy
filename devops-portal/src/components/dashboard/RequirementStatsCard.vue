<script setup lang="ts">
import type { RequirementStats } from '../../api/portal';
import DashboardCard from './DashboardCard.vue';
import StatChip from './StatChip.vue';

defineProps<{
  stats: RequirementStats;
  loading?: boolean;
  degraded?: boolean;
}>();
</script>

<template>
  <DashboardCard
    title="需求统计"
    :loading="loading"
    :degraded="degraded"
    :empty="stats.total === 0"
    empty-text="暂无需求数据"
  >
    <p class="stat">
      <span class="stat__value">{{ stats.total }}</span>
      <span class="stat__unit">需求 · 基线 {{ stats.baseline_total }}</span>
    </p>
    <div class="chips">
      <StatChip v-for="(value, key) in stats.by_status" :key="key">{{ key }}: {{ value }}</StatChip>
    </div>
  </DashboardCard>
</template>

<style scoped>
.stat {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 10px;
}
.stat__value {
  font-size: 1.6rem;
  font-weight: 700;
  line-height: 1;
}
.stat__unit {
  font-size: 0.75rem;
  color: var(--muted);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
