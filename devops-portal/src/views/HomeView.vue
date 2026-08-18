<script setup lang="ts">
/**
 * Portal homepage / 驾驶舱.
 *
 * Assembles the dashboard card family on top of `useDashboard`. The gateway is
 * the authority for scope + permission (architecture §5.2): this view only
 * *requests* a scope and always renders whatever the backend resolved, so a
 * revoked permission downgrades the UI on the next poll without a reload.
 */
import { computed, onMounted } from 'vue';

import {
  PERMISSION_CROSS_PROJECT_VIEW,
  SCOPE_CROSS_PROJECT,
  SCOPE_MINE,
  type Scope,
} from '../api/portal';
import ActivityCard from '../components/dashboard/ActivityCard.vue';
import MyWorkCard from '../components/dashboard/MyWorkCard.vue';
import ProjectOverviewCard from '../components/dashboard/ProjectOverviewCard.vue';
import RequirementStatsCard from '../components/dashboard/RequirementStatsCard.vue';
import TdStatsCard from '../components/dashboard/TdStatsCard.vue';
import TpStatsCard from '../components/dashboard/TpStatsCard.vue';
import { useDashboard } from '../composables/useDashboard';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
// Permitted users land on "全平台" by default (architecture §8.8).
const initialScope: Scope = auth.has(PERMISSION_CROSS_PROJECT_VIEW) ? SCOPE_CROSS_PROJECT : SCOPE_MINE;

const {
  data,
  status,
  isInitialLoading,
  scope,
  canCrossProject,
  refresh,
  setScope,
  startPolling,
  isDegraded,
} = useDashboard(initialScope);

const degradedDomains = computed(() => data.value?.degraded.map((entry) => entry.domain) ?? []);
const scopeLabel = computed(() => (scope.value === SCOPE_CROSS_PROJECT ? '全平台' : '我的项目'));
const isRefreshing = computed(() => status.value === 'loading');

onMounted(() => {
  void refresh();
  startPolling();
});

function onRetry(): void {
  void refresh();
}

function onScopeChange(next: Scope): void {
  if (next === scope.value) return;
  void setScope(next);
}
</script>

<template>
  <!-- No `id="main"` here: AppShell already owns that skip-link target. -->
  <section class="home" aria-labelledby="home-title">
    <header class="home__head">
      <div class="home__heading">
        <h1 id="home-title" class="home__title">驾驶舱</h1>
        <p class="home__subtitle">跨域研发数据一览 · 范围：{{ scopeLabel }}</p>
      </div>

      <div v-if="canCrossProject" class="segmented" role="group" aria-label="数据范围">
        <button
          type="button"
          class="segmented__btn"
          :class="{ 'segmented__btn--on': scope === SCOPE_MINE }"
          :aria-pressed="scope === SCOPE_MINE"
          @click="onScopeChange(SCOPE_MINE)"
        >
          我的项目
        </button>
        <button
          type="button"
          class="segmented__btn"
          :class="{ 'segmented__btn--on': scope === SCOPE_CROSS_PROJECT }"
          :aria-pressed="scope === SCOPE_CROSS_PROJECT"
          @click="onScopeChange(SCOPE_CROSS_PROJECT)"
        >
          全平台
        </button>
      </div>
      <p v-else class="home__scope-static">我的项目</p>

      <button type="button" class="home__refresh" :disabled="isRefreshing" @click="onRetry">
        {{ isRefreshing ? '刷新中…' : '刷新' }}
      </button>
    </header>

    <p v-if="data?.scope_downgraded" class="home__notice" role="status">
      你的跨项目查看权限已变更，已切换为「我的项目」视图
    </p>

    <div v-if="isInitialLoading && !data" class="home__grid" aria-busy="true">
      <div v-for="n in 6" :key="n" class="home__cell" :class="{ 'home__cell--wide': n > 4 }">
        <div class="home__placeholder">
          <span class="sr-only">加载中</span>
          <span v-for="line in 3" :key="line" class="home__placeholder-line" aria-hidden="true" />
        </div>
      </div>
    </div>

    <div v-else-if="status === 'error' && !data" class="home__error" role="alert">
      <p class="home__error-text">驾驶舱数据加载失败，请稍后重试。</p>
      <button type="button" class="home__refresh" @click="onRetry">重试</button>
    </div>

    <div v-else-if="data" class="home__grid">
      <div class="home__cell">
        <ProjectOverviewCard
          :projects="data.projects"
          :loading="false"
          :degraded="isDegraded('project')"
          @retry="onRetry"
        />
      </div>
      <div class="home__cell">
        <RequirementStatsCard
          :stats="data.requirement_stats"
          :loading="false"
          :degraded="isDegraded('requirement')"
          @retry="onRetry"
        />
      </div>
      <div class="home__cell">
        <TpStatsCard
          :stats="data.tp_stats"
          :loading="false"
          :degraded="isDegraded('tp')"
          @retry="onRetry"
        />
      </div>
      <div class="home__cell">
        <TdStatsCard
          :stats="data.td_stats"
          :loading="false"
          :degraded="isDegraded('td')"
          @retry="onRetry"
        />
      </div>
      <div class="home__cell home__cell--wide">
        <MyWorkCard :my-work="data.my_work" :loading="false" :degraded="degradedDomains" />
      </div>
      <div class="home__cell home__cell--wide">
        <ActivityCard
          :activity="data.recent_activities"
          :loading="false"
          :degraded="isDegraded('activity')"
          @retry="onRetry"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.home {
  max-width: 1200px;
  margin: auto;
  padding: clamp(1rem, 3vw, 3rem);
}
.home__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}
.home__heading {
  margin-right: auto;
}
.home__title {
  margin: 0;
  font-size: 1.5rem;
}
.home__subtitle {
  margin: 4px 0 0;
  font-size: 0.8125rem;
  color: var(--muted);
}
.segmented {
  display: inline-flex;
  border: 1px solid var(--card-border);
  border-radius: 8px;
  overflow: hidden;
}
.segmented__btn {
  min-height: 40px;
  padding: 8px 14px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.segmented__btn + .segmented__btn {
  border-left: 1px solid var(--card-border);
}
.segmented__btn--on {
  background: var(--accent);
  color: #fff;
}
.home__scope-static {
  margin: 0;
  padding: 6px 12px;
  border-radius: 999px;
  background: var(--chip-bg);
  font-size: 0.8125rem;
}
.home__refresh {
  min-height: 40px;
  padding: 8px 14px;
  border: 1px solid var(--card-border);
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.home__refresh:disabled {
  opacity: 0.6;
  cursor: default;
}
.home__notice {
  margin: 0 0 16px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--info-bg);
  color: var(--info-fg);
  font-size: 0.8125rem;
}
.home__error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 8px;
  background: var(--err-bg);
  color: var(--err-fg);
}
.home__error-text {
  margin: 0;
}
.home__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.home__cell--wide {
  grid-column: 1 / -1;
}
.home__placeholder {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 140px;
  padding: 16px;
  border: 1px solid var(--card-border);
  border-radius: 12px;
  background: var(--card-surface);
}
.home__placeholder-line {
  display: block;
  height: 12px;
  border-radius: 6px;
  background: var(--track);
  animation: home-pulse 1.4s ease-in-out infinite;
}
@keyframes home-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}
@media (max-width: 760px) {
  .home__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
