import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { relative, resolve } from 'node:path';

/** Verify that a Vite output directory contains exactly one complete build. */
export function verifyDist(outputPath) {
  const indexPath = resolve(outputPath, 'index.html');
  const manifestPath = resolve(outputPath, '.vite/manifest.json');
  if (!existsSync(indexPath) || !existsSync(manifestPath)) {
    throw new Error('Build index or Vite manifest is missing');
  }

  const allFiles = listFiles(outputPath);
  const relativeFiles = new Set(
    allFiles.map((path) => relative(outputPath, path).replaceAll('\\', '/')),
  );
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const generatedAssets = new Set();
  for (const entry of Object.values(manifest)) {
    generatedAssets.add(entry.file);
    for (const css of entry.css ?? []) generatedAssets.add(css);
    for (const asset of entry.assets ?? []) generatedAssets.add(asset);
  }
  for (const asset of generatedAssets) {
    if (!relativeFiles.has(asset)) {
      throw new Error(`Vite manifest references missing asset ${asset}`);
    }
  }

  const index = readFileSync(indexPath, 'utf8');
  const indexReferences = [
    ...index.matchAll(/(?:src|href)="\/?(assets\/[^"]+)"/g),
  ].map((match) => match[1]);
  if (indexReferences.length === 0) {
    throw new Error('Build index.html does not reference generated assets');
  }
  for (const asset of indexReferences) {
    if (!generatedAssets.has(asset)) {
      throw new Error(`Build index.html references non-manifest asset ${asset}`);
    }
  }

  const allowed = new Set(['index.html', '.vite/manifest.json', ...generatedAssets]);
  const unreferenced = [...relativeFiles]
    .filter((path) => !allowed.has(path))
    .sort();
  if (unreferenced.length > 0) {
    throw new Error(`Unreferenced build assets: ${unreferenced.join(', ')}`);
  }
  if (allFiles.some((path) => statSync(path).size === 0)) {
    throw new Error('Generated build contains empty files');
  }
  return {
    fileCount: relativeFiles.size,
    indexReferenceCount: indexReferences.length,
    assetCount: generatedAssets.size,
  };
}

function listFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? listFiles(path) : [path];
  });
}
