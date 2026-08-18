<script setup lang="ts">
/**
 * Shared stateful wrapper for every dashboard card.
 *
 * Encodes the four canonical states from architecture §8.4:
 *  - loading  → skeleton (only on first load; polls keep stale data)
 *  - empty    → guided empty state
 *  - degraded → "数据暂不可用" + retry (single-domain failure, not a 500)
 *  - ready    → default slot
 *
 * NOTE: this portal registers no Vuetify components (see src/main.ts —
 * `createVuetify()` is installed for theming only). Every card therefore uses
 * semantic HTML plus the design tokens in src/styles/tokens.css, matching the
 * convention already used by DomainWorkspaceView.vue.
 */
defineProps<{
  title: string;
  loading?: boolean;
  degraded?: boolean;
  empty?: boolean;
  emptyText?: string;
}>();

const emit = defineEmits<{ (e: 'retry'): void }>();
</script>

<template>
  <article
    class="dcard"
    :class="{ 'dcard--degraded': degraded }"
    :aria-busy="loading ? 'true' : 'false'"
  >
    <header class="dcard__head">
      <h2 class="dcard__title">{{ title }}</h2>
      <span v-if="degraded" class="dcard__badge">降级</span>
    </header>

    <div class="dcard__body">
      <div v-if="loading" class="dcard__skeleton" role="status">
        <span class="sr-only">加载中</span>
        <span v-for="n in 3" :key="n" class="dcard__skeleton-line" aria-hidden="true" />
      </div>

      <p v-else-if="empty" class="dcard__empty">{{ emptyText || '暂无数据' }}</p>

      <div v-else-if="degraded" class="dcard__fallback">
        <p class="dcard__fallback-text">该模块数据暂不可用</p>
        <button type="button" class="dcard__retry" @click="emit('retry')">重试</button>
      </div>

      <slot v-else />
    </div>
  </article>
</template>

<style scoped>
.dcard {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--card-surface);
  border: 1px solid var(--card-border);
  border-radius: 12px;
  overflow: hidden;
}
.dcard--degraded {
  border-color: var(--warn-fg);
}
.dcard__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px 0;
}
.dcard__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  line-height: 1.4;
}
.dcard__badge {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--warn-fg);
  background: var(--warn-bg);
}
.dcard__body {
  flex: 1;
  padding: 12px 16px 16px;
}
.dcard__empty {
  margin: 0;
  padding: 20px 0;
  text-align: center;
  color: var(--muted);
  font-size: 0.875rem;
}
.dcard__fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px 0;
}
.dcard__fallback-text {
  margin: 0;
  color: var(--muted);
  font-size: 0.875rem;
}
.dcard__retry {
  min-height: 36px;
  padding: 6px 14px;
  border: 1px solid currentColor;
  border-radius: 8px;
  background: transparent;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
}
.dcard__skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 6px 0;
}
.dcard__skeleton-line {
  display: block;
  height: 12px;
  border-radius: 6px;
  background: var(--track);
  animation: dcard-pulse 1.4s ease-in-out infinite;
}
.dcard__skeleton-line:nth-child(3) {
  width: 70%;
}
@keyframes dcard-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}
</style>
