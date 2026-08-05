import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { publishBuild, removeStagingTree } from './build-transaction.mjs';

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const buildId = randomUUID();
const stagingName = `.dist-staging-${buildId}`;
const previousName = `.dist-previous-${buildId}`;
const stagingPath = resolve(projectRoot, stagingName);
const distPath = resolve(projectRoot, 'dist');
const previousPath = resolve(projectRoot, previousName);
const viteCli = resolve(projectRoot, 'node_modules/vite/bin/vite.js');

try {
  const build = spawnSync(process.execPath, [viteCli, 'build'], {
    cwd: projectRoot,
    env: { ...process.env, PORTAL_BUILD_OUT_DIR: stagingName },
    stdio: 'inherit',
  });
  if (build.status !== 0) {
    throw new Error(
      `Vite staging build failed with exit code ${build.status ?? 'unknown'}`,
    );
  }
  const result = publishBuild({ stagingPath, distPath, previousPath });
  if (result.cleanupWarning !== '') {
    console.warn(result.cleanupWarning);
  }
  console.log(
    `Published verified build with ${result.verification.assetCount} manifest assets.`,
  );
} catch (error) {
  if (existsSync(stagingPath)) {
    removeStagingTree(stagingPath, distPath);
  }
  throw error;
}
