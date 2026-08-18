<script setup lang="ts">
import { computed } from 'vue';

import type { MyOpenDefect } from '../../api/portal';
import MyWorkItemCard from './MyWorkItemCard.vue';
import type { DisplayItem } from './types';

const props = defineProps<{
  defects: { count: number; items: MyOpenDefect[] };
  loading?: boolean;
  degraded?: boolean;
}>();

const items = computed<DisplayItem[]>(() =>
  props.defects.items.map((d) => ({
    id: d.id,
    primary: d.title,
    secondary: `${d.business_no} · ${d.severity}/${d.priority} · ${d.status}`,
    chip: d.sla_breached ? 'SLA' : undefined,
    chipTone: d.sla_breached ? ('error' as const) : undefined,
  })),
);
</script>

<template>
  <MyWorkItemCard
    title="我的缺陷"
    :items="items"
    :count="defects.count"
    :loading="loading"
    :degraded="degraded"
    empty-text="太棒了，当前没有待处理事项 🎉"
  />
</template>
