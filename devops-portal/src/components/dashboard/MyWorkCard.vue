<script setup lang="ts">
import { computed } from 'vue';

import type { MyWorkBlock } from '../../api/portal';
import MyDefectsCard from './MyDefectsCard.vue';
import PendingApprovalsCard from './PendingApprovalsCard.vue';
import PendingExecutionsCard from './PendingExecutionsCard.vue';
import PendingReviewsCard from './PendingReviewsCard.vue';

const props = defineProps<{
  myWork: MyWorkBlock;
  loading?: boolean;
  degraded?: string[];
}>();

const degradedDomains = computed(() => new Set(props.degraded ?? []));
</script>

<template>
  <div class="my-work-grid">
    <PendingReviewsCard
      :reviews="myWork.pending_requirement_reviews"
      :loading="loading"
      :degraded="degradedDomains.has('requirement')"
    />
    <MyDefectsCard
      :defects="myWork.my_open_defects"
      :loading="loading"
      :degraded="degradedDomains.has('td')"
    />
    <PendingExecutionsCard
      :executions="myWork.pending_test_executions"
      :loading="loading"
      :degraded="degradedDomains.has('tp')"
    />
    <PendingApprovalsCard
      :approvals="myWork.pending_workflow_approvals"
      :loading="loading"
      :degraded="degradedDomains.has('workflow')"
    />
  </div>
</template>

<style scoped>
.my-work-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}
@media (max-width: 600px) {
  .my-work-grid {
    grid-template-columns: 1fr;
  }
}
</style>
