<script setup lang="ts">
/**
 * TraceabilityTab — the `/app/projects/:project_id/traceability` workspace tab.
 *
 * Informational view reusing the capability cards from the legacy `DomainWorkspaceView`
 * traceability branch (forward/reverse links, completeness, projection warnings). The
 * traceability backend is P1, so this is a read-only, never-blocking surface.
 */
import { useProjectContext } from '../composables/useProjectContext';

const { projectId } = useProjectContext();

const cards = [
  '前向链接（需求 → 用例 → 缺陷）',
  '反向链接（缺陷 → 用例 → 需求）',
  '完整性',
  '投影警告',
];
</script>

<template>
  <main class="traceability-tab" aria-labelledby="trace-title">
    <header>
      <p class="eyebrow">Project {{ projectId }}</p>
      <h1 id="trace-title">追溯</h1>
      <p>跨领域链路与完整性视图（追溯后端为 P1，以下为信息性展示）。</p>
    </header>
    <section class="cards" :aria-label="`Traceability capabilities`">
      <article v-for="card in cards" :key="card">
        <h2>{{ card }}</h2>
        <p>查看前向/反向链接，检查覆盖完整性，并接收投影一致性警告。</p>
        <v-btn variant="text" disabled>查看</v-btn>
      </article>
    </section>
  </main>
</template>

<style scoped>
.traceability-tab {
  max-width: 1200px;
  margin: auto;
  padding: clamp(1rem, 3vw, 3rem);
}
.eyebrow {
  font-weight: 700;
  color: rgb(var(--v-theme-primary));
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 1rem;
  margin-top: 1.5rem;
}
.cards article {
  padding: 1.25rem;
  border: 1px solid rgba(127, 127, 127, 0.35);
  border-radius: 0.75rem;
}
.cards article h2 {
  font-size: 1rem;
  margin-top: 0;
}
.cards button {
  min-height: 44px;
  margin-top: 0.75rem;
}
</style>
