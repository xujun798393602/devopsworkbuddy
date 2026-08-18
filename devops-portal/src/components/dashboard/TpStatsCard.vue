<script setup lang="ts">
import type { TpStats } from '../../api/portal';
import DashboardCard from './DashboardCard.vue';
import StatChip from './StatChip.vue';

defineProps<{
  stats: TpStats;
  loading?: boolean;
  degraded?: boolean;
}>();

function passRateLabel(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 100)}%`;
}
</script>

<template>
  <DashboardCard
    title="测试统计"
    :loading="loading"
    :degraded="degraded"
    :empty="stats.case_total === 0"
    empty-text="暂无测试数据"
  >
    <p class="stat">
      <span class="stat__value">{{ stats.case_total }}</span>
      <span class="stat__unit">用例</span>
    </p>
    <div class="chips">
      <StatChip>计划 {{ stats.plan_total }}</StatChip>
      <StatChip>执行 {{ stats.execution_total }}</StatChip>
      <StatChip tone="ok">通过率 {{ passRateLabel(stats.pass_rate) }}</StatChip>
    </div>
    <div class="chips chips--sub">
      <StatChip v-for="(value, key) in stats.execution_by_status" :key="key">
        {{ key }}: {{ value }}
      </StatChip>
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
.chips--sub {
  margin-top: 8px;
}
</style>
