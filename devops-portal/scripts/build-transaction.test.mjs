import assert from 'node:assert/strict';
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import test from 'node:test';

import {
  publishBuild,
  removePreviousTree,
  removeStagingTree,
} from './build-transaction.mjs';

function fixture() {
  const root = mkdtempSync(resolve(tmpdir(), 'portal-build-'));
  const distPath = resolve(root, 'dist');
  const transactionId = '123e4567-e89b-42d3-a456-426614174000';
  const stagingPath = resolve(root, `.dist-staging-${transactionId}`);
  const previousPath = resolve(root, `.dist-previous-${transactionId}`);
  mkdirSync(distPath);
  mkdirSync(stagingPath);
  writeFileSync(resolve(distPath, 'marker.txt'), 'old');
  writeFileSync(resolve(stagingPath, 'marker.txt'), 'new');
  return { distPath, stagingPath, previousPath };
}

test('staging verification failure keeps the previous dist untouched', () => {
  const paths = fixture();
  assert.throws(
    () =>
      publishBuild({
        ...paths,
        verify: () => {
          throw new Error('invalid staging');
        },
      }),
    /invalid staging/,
  );
  assert.equal(readFileSync(resolve(paths.distPath, 'marker.txt'), 'utf8'), 'old');
  assert.equal(readFileSync(resolve(paths.stagingPath, 'marker.txt'), 'utf8'), 'new');
  assert.equal(existsSync(paths.previousPath), false);
});

test('publish rename failure restores the previous dist', () => {
  const paths = fixture();
  let renameCalls = 0;
  const injectedRename = (source, target) => {
    renameCalls += 1;
    if (renameCalls === 2) {
      throw new Error('injected switch failure');
    }
    renameSync(source, target);
  };
  assert.throws(
    () =>
      publishBuild({
        ...paths,
        verify: () => ({}),
        rename: injectedRename,
      }),
    /previous dist was restored/,
  );
  assert.equal(readFileSync(resolve(paths.distPath, 'marker.txt'), 'utf8'), 'old');
  assert.equal(readFileSync(resolve(paths.stagingPath, 'marker.txt'), 'utf8'), 'new');
  assert.equal(existsSync(paths.previousPath), false);
  assert.equal(renameCalls, 3);
});

test('successful publish removes transaction-owned staging and previous paths', () => {
  const paths = fixture();
  const result = publishBuild({
    ...paths,
    verify: () => ({ assetCount: 1 }),
  });
  assert.equal(result.cleanupWarning, '');
  assert.equal(readFileSync(resolve(paths.distPath, 'marker.txt'), 'utf8'), 'new');
  assert.equal(existsSync(paths.stagingPath), false);
  assert.equal(existsSync(paths.previousPath), false);
});

test('cleanup failure keeps verified dist and returns a diagnostic warning', () => {
  const paths = fixture();
  const result = publishBuild({
    ...paths,
    verify: () => ({ assetCount: 1 }),
    removePrevious: () => {
      throw new Error('injected cleanup failure');
    },
  });
  assert.equal(readFileSync(resolve(paths.distPath, 'marker.txt'), 'utf8'), 'new');
  assert.match(result.cleanupWarning, /verified dist published/i);
  assert.equal(existsSync(paths.previousPath), true);
});

test('cleanup APIs reject every non-canonical or out-of-bound path', () => {
  const root = mkdtempSync(resolve(tmpdir(), 'portal-delete-'));
  const distPath = resolve(root, 'dist');
  mkdirSync(distPath);
  const outsideRoot = resolve(root, 'outside');
  mkdirSync(outsideRoot);
  const cases = [
    resolve(root, 'unrelated'),
    root,
    resolve(outsideRoot, '.dist-staging-123e4567-e89b-42d3-a456-426614174000'),
    resolve(root, '.dist-staging-evil'),
    resolve(root, '.dist-staging-'),
    resolve(root, 'nested', '..', 'unrelated-normalized'),
  ];
  for (const candidate of cases) {
    mkdirSync(candidate, { recursive: true });
    assert.throws(
      () => removeStagingTree(candidate, distPath),
      /refusing/i,
    );
    assert.equal(existsSync(candidate), true);
  }
  assert.throws(() => removeStagingTree('', distPath), /refusing/i);
  assert.throws(() => removePreviousTree(root, distPath), /refusing/i);
  assert.equal(existsSync(root), true);
  assert.equal(existsSync(outsideRoot), true);
});

test('cleanup rejects path traversal that normalizes outside the dist parent', () => {
  const root = mkdtempSync(resolve(tmpdir(), 'portal-traversal-'));
  const project = resolve(root, 'project');
  const distPath = resolve(project, 'dist');
  mkdirSync(distPath, { recursive: true });
  const external = resolve(
    project,
    '..',
    '.dist-previous-123e4567-e89b-42d3-a456-426614174000',
  );
  mkdirSync(external);
  assert.throws(() => removePreviousTree(external, distPath), /refusing/i);
  assert.equal(existsSync(external), true);
});
