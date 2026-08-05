import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { verifyDist } from './dist-verifier.mjs';

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const result = verifyDist(resolve(projectRoot, 'dist'));
console.log(
  `Verified ${result.indexReferenceCount} index references and ${result.assetCount} manifest assets; 0 stale assets.`,
);
