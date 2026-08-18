<script setup lang="ts">
import { computed } from 'vue';

import type { PendingWorkflowApproval } from '../../api/portal';
import MyWorkItemCard from './MyWorkItemCard.vue';

const props = defineProps<{
  approvals: { count: number; items: PendingWorkflowApproval[] };
  loading?: boolean;
  degraded?: boolean;
}>();

const items = computed(() =>
  props.approvals.items.map((a) => ({
    id: a.id,
    primary: `${a.business_object_type} ${a.business_object_id}`,
    secondary: `状态 ${a.current_state}`,
  })),
);
</script>

<template>
  <MyWorkItemCard
    title="待审流程"
    :items="items"
    :count="approvals.count"
    :loading="loading"
    :degraded="degraded"
    empty-text="太棒了，当前没有待处理事项 🎉"
  />
</template>
