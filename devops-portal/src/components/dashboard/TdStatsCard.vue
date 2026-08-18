<script setup lang="ts">
import type { TdStats } from '../../api/portal';
import DashboardCard from './DashboardCard.vue';
import StatChip from './StatChip.vue';
import type { ChipTone } from './types';

defineProps<{
  stats: TdStats;
  loading?: boolean;
  degraded?: boolean;
}>();

const SEVERITY_TONE: Record<string, ChipTone> = {
  critical: 'error',
  blocker: 'error',
  high: 'warn',
  medium: 'info',
  low: 'ok',
};

function severityTone(key: string): ChipTone {
  return SEVERITY_TONE[key] ?? 'neutral';
}
</script>

<template>
  <DashboardCard
    title="缺陷统计"
    :loading="loading"
    :degraded="degraded"
    :empty="stats.total === 0"
    empty-text="暂无缺陷数据"
  >
    <p class="stat">
      <span class="stat__value">{{ stats.total }}</span>
      <span class="stat__unit">缺陷</span>
      <StatChip v-if="stats.sla_breached > 0" tone="error">SLA 超时 {{ stats.sla_breached }}</StatChip>
    </p>

    <p class="group-label">状态</p>
    <div class="chips">
      <StatChip v-for="(value, key) in stats.by_status" :key="key">{{ key }}: {{ value }}</StatChip>
    </div>

    <p class="group-label">严重度</p>
    <div class="chips">
      <StatChip v-for="(value, key) in stats.by_severity" :key="key" :tone="severityTone(String(key))">
        {{ key }}: {{ value }}
      </StatChip>
    </div>
  </DashboardCard>
</template>

<style scoped>
.stat {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
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
.group-label {
  margin: 10px 0 4px;
  font-size: 0.75rem;
  color: var(--muted);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
