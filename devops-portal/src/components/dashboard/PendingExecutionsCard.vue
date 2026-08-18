<script setup lang="ts">
import { computed } from 'vue';

import type { PendingTestExecution } from '../../api/portal';
import MyWorkItemCard from './MyWorkItemCard.vue';
import type { DisplayItem } from './types';

const props = defineProps<{
  executions: { count: number; items: PendingTestExecution[] };
  loading?: boolean;
  degraded?: boolean;
}>();

const items = computed<DisplayItem[]>(() =>
  props.executions.items.map((e) => ({
    id: e.id,
    primary: e.name,
    secondary: `${e.plan_id} · ${e.status}`,
    chip: e.planned_at ? '已排期' : undefined,
    chipTone: 'info' as const,
  })),
);
</script>

<template>
  <MyWorkItemCard
    title="待执行用例"
    :items="items"
    :count="executions.count"
    :loading="loading"
    :degraded="degraded"
    empty-text="太棒了，当前没有待处理事项 🎉"
  />
</template>
