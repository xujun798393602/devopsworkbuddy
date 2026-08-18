<script setup lang="ts">
import { computed } from 'vue';

import type { PendingRequirementReview } from '../../api/portal';
import MyWorkItemCard from './MyWorkItemCard.vue';

const props = defineProps<{
  reviews: { count: number; items: PendingRequirementReview[] };
  loading?: boolean;
  degraded?: boolean;
}>();

const items = computed(() =>
  props.reviews.items.map((r) => ({
    id: r.id,
    primary: r.title,
    secondary: `${r.business_no} · ${r.status}`,
  })),
);
</script>

<template>
  <MyWorkItemCard
    title="待审需求"
    :items="items"
    :count="reviews.count"
    :loading="loading"
    :degraded="degraded"
    empty-text="太棒了，当前没有待处理事项 🎉"
  />
</template>
