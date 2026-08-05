import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: process.env.PORTAL_BUILD_OUT_DIR ?? 'dist',
    emptyOutDir: true,
    manifest: true,
  },
  test: {
    environment: 'jsdom',
    exclude: ['scripts/**', 'node_modules/**', 'dist/**'],
  },
});
