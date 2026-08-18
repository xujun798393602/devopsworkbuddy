<script setup lang="ts">
/**
 * Inline SVG icon set for the left function menu.
 *
 * We deliberately avoid pulling in an icon font dependency (the portal's
 * package set is curated/offline), so each glyph is a self-contained stroke
 * path rendered at 24x24 with `currentColor`.
 */
const props = defineProps<{ name: string }>();

const PATHS: Record<string, string> = {
  // 驾驶舱 / home
  home: 'M3 11.4 12 4l9 7.4M5.4 9.7V19.5h13.2V9.7',
  // 项目 / folder
  projects: 'M3 7.4A1.4 1.4 0 0 1 4.4 6h3.8l2 2h8A1.4 1.4 0 0 1 19.6 9.4v7.8A1.4 1.4 0 0 1 18.2 18.6H5.4A1.4 1.4 0 0 1 4 17.2z',
  // 工作流 / stacked layers
  workflows: 'M12 3 21 8l-9 5-9-5 9-5zM3 13l9 5 9-5',
  // 通知 / bell
  notifications: 'M18 8.6a6 6 0 1 0-12 0c0 6.4-2.4 7.9-2.4 7.9h16.8s-2.4-1.5-2.4-7.9M13.6 21a2 2 0 0 1-3.2 0',
  // 审计 / shield
  audit: 'M12 3l8 3.2v5.3c0 5-3.8 7.8-8 8.8-4.2-1-8-3.8-8-8.8V6.2z',
  // 设置 / gear
  settings:
    'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7.1 19.4a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 2.6 14H2.5a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.2 7.1a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 9.4 2.6V2.5a2 2 0 1 1 4 0v.1A1.6 1.6 0 0 0 14.9 4.2a1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z',
  // 退出 / logout
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
};
</script>

<template>
  <svg
    class="nav-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="PATHS[props.name] ?? PATHS.home" />
  </svg>
</template>

<style scoped>
.nav-icon {
  width: 22px;
  height: 22px;
  flex: none;
}
</style>
