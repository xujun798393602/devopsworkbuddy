<script setup lang="ts">
import { computed } from 'vue';

import type { ProjectsBlock } from '../../api/portal';
import DashboardCard from './DashboardCard.vue';

const props = defineProps<{
  projects: ProjectsBlock;
  loading?: boolean;
  degraded?: boolean;
}>();

const isEmpty = computed(() => props.projects.items.length === 0);

/** Clamp to 0–100 so a bad upstream value can never break the bar. */
function progressOf(percent: number | null): number {
  if (percent === null || Number.isNaN(percent)) return 0;
  return Math.min(100, Math.max(0, Math.round(percent)));
}
</script>

<template>
  <DashboardCard
    title="我的项目"
    :loading="loading"
    :degraded="degraded"
    :empty="isEmpty"
    empty-text="你还没有参与任何项目"
  >
    <ul class="projects">
      <li v-for="p in projects.items" :key="p.id" class="projects__item">
        <p class="projects__name">
          {{ p.name }}
          <span class="projects__no">{{ p.business_no }}</span>
        </p>
        <div class="projects__row">
          <div
            class="projects__bar"
            role="progressbar"
            :aria-valuenow="progressOf(p.progress_percent)"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-label="`${p.name} 进度`"
          >
            <span class="projects__bar-fill" :style="{ width: `${progressOf(p.progress_percent)}%` }" />
          </div>
          <span class="projects__meta">
            {{ progressOf(p.progress_percent) }}% · 待办 {{ p.my_open_task_count }}
          </span>
        </div>
        <p v-if="p.current_iteration || p.current_version" class="projects__ctx">
          <span v-if="p.current_iteration">迭代 {{ p.current_iteration.name }}</span>
          <span v-if="p.current_iteration && p.current_version"> · </span>
          <span v-if="p.current_version">版本 {{ p.current_version.name }}</span>
        </p>
      </li>
    </ul>
    <p class="projects__total">{{ projects.items.length }} / 共 {{ projects.total }}</p>
  </DashboardCard>
</template>

<style scoped>
.projects {
  list-style: none;
  margin: 0;
  padding: 0;
}
.projects__item {
  padding: 8px 0;
  border-bottom: 1px solid var(--card-border);
}
.projects__item:last-child {
  border-bottom: 0;
}
.projects__name {
  margin: 0;
  font-size: 0.875rem;
  font-weight: 500;
}
.projects__no {
  margin-left: 6px;
  font-size: 0.75rem;
  font-weight: 400;
  color: var(--muted);
}
.projects__row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.projects__bar {
  flex: none;
  width: 120px;
  height: 6px;
  border-radius: 999px;
  background: var(--track);
  overflow: hidden;
}
.projects__bar-fill {
  display: block;
  height: 100%;
  background: var(--accent);
}
.projects__meta,
.projects__ctx {
  margin: 0;
  font-size: 0.75rem;
  color: var(--muted);
}
.projects__ctx {
  margin-top: 4px;
}
.projects__total {
  margin: 8px 0 0;
  font-size: 0.75rem;
  color: var(--muted);
}
</style>
