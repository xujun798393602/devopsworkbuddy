<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();
const titles: Record<string, string> = {
  requirements: 'Requirements',
  testing: 'Test management',
  traceability: 'Traceability',
};
const section = computed(() => String(route.meta.section ?? 'requirements'));
const title = computed(() => titles[section.value] ?? 'Project workspace');
const cards = computed(() => section.value === 'requirements'
  ? ['Requirement backlog', 'Reviews and decisions', 'Baseline snapshots']
  : section.value === 'testing'
    ? ['Test library', 'Plans and frozen scope', 'Executions and reports', 'Automation ingestion']
    : ['Forward and reverse links', 'Completeness', 'Projection warnings']);
</script>

<template>
  <main class="domain-workspace" aria-labelledby="workspace-title">
    <header>
      <p class="eyebrow">Project {{ route.params.project_id }}</p>
      <h1 id="workspace-title">{{ title }}</h1>
      <p>Authoritative project-scoped data with optimistic concurrency and traceable revisions.</p>
    </header>
    <nav aria-label="Domain navigation" class="tabs">
      <RouterLink :to="`/app/projects/${route.params.project_id}/requirements`">Requirements</RouterLink>
      <RouterLink :to="`/app/projects/${route.params.project_id}/testing`">Test management</RouterLink>
      <RouterLink :to="`/app/projects/${route.params.project_id}/traceability`">Traceability</RouterLink>
    </nav>
    <section class="cards" :aria-label="`${title} capabilities`">
      <article v-for="card in cards" :key="card">
        <h2>{{ card }}</h2>
        <p>Open the project resource list, inspect immutable revisions, and perform permitted actions.</p>
        <button type="button">View {{ card }}</button>
      </article>
    </section>
  </main>
</template>

<style scoped>
.domain-workspace{max-width:1200px;margin:auto;padding:clamp(1rem,3vw,3rem)}.eyebrow{font-weight:700;color:rgb(var(--v-theme-primary))}.tabs{display:flex;gap:.5rem;overflow:auto;margin:1.5rem 0}.tabs a{padding:.75rem 1rem;border:1px solid currentColor;border-radius:.5rem;white-space:nowrap}.tabs a.router-link-active{background:rgb(var(--v-theme-primary));color:rgb(var(--v-theme-on-primary))}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1rem}.cards article{padding:1.25rem;border:1px solid rgba(127,127,127,.35);border-radius:.75rem}.cards button{min-height:44px;margin-top:.75rem;padding:.5rem .75rem}button:focus-visible,a:focus-visible{outline:3px solid rgb(var(--v-theme-primary));outline-offset:3px}
</style>
