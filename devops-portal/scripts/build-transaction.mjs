import { existsSync, renameSync, rmSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';

import { verifyDist } from './dist-verifier.mjs';

const TRANSACTION_ID =
  '[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';
const STAGING_NAME = new RegExp(`^\\.dist-staging-${TRANSACTION_ID}$`, 'i');
const PREVIOUS_NAME = new RegExp(`^\\.dist-previous-${TRANSACTION_ID}$`, 'i');

/** Publish a verified staging build while preserving the last successful dist. */
export function publishBuild({
  stagingPath,
  distPath,
  previousPath,
  verify = verifyDist,
  rename = renameSync,
  removePrevious = removePreviousTree,
}) {
  assertTransactionPath(stagingPath, STAGING_NAME, distPath, 'staging');
  assertTransactionPath(previousPath, PREVIOUS_NAME, distPath, 'previous');
  const verification = verify(stagingPath);
  const hadPrevious = existsSync(distPath);
  if (hadPrevious) {
    rename(distPath, previousPath);
  }
  try {
    rename(stagingPath, distPath);
  } catch (publishError) {
    let rollbackError;
    if (hadPrevious && existsSync(previousPath) && !existsSync(distPath)) {
      try {
        rename(previousPath, distPath);
      } catch (error) {
        rollbackError = error;
      }
    }
    if (rollbackError !== undefined) {
      throw new AggregateError(
        [publishError, rollbackError],
        'Build publish failed and previous dist rollback also failed',
      );
    }
    throw new Error('Build publish failed; previous dist was restored', {
      cause: publishError,
    });
  }

  let cleanupWarning = '';
  if (hadPrevious && existsSync(previousPath)) {
    try {
      removePrevious(previousPath, distPath);
    } catch (error) {
      cleanupWarning = `Verified dist published, but previous cleanup failed: ${error.message}`;
    }
  }
  return { verification, cleanupWarning };
}

/** Remove only a canonical transaction-owned staging directory. */
export function removeStagingTree(stagingPath, distPath) {
  removeTransactionTree(stagingPath, STAGING_NAME, distPath, 'staging');
}

/** Remove only a canonical transaction-owned previous directory. */
export function removePreviousTree(previousPath, distPath) {
  removeTransactionTree(previousPath, PREVIOUS_NAME, distPath, 'previous');
}

function removeTransactionTree(path, namePattern, distPath, kind) {
  assertTransactionPath(path, namePattern, distPath, kind);
  if (existsSync(path)) {
    rmSync(path, {
      recursive: true,
      force: true,
      maxRetries: 3,
      retryDelay: 100,
    });
  }
}

function assertTransactionPath(path, namePattern, distPath, kind) {
  if (typeof path !== 'string' || path.length === 0) {
    throw new Error(`Refusing empty ${kind} transaction path`);
  }
  const normalizedDist = resolve(distPath);
  const expectedParent = dirname(normalizedDist);
  const candidate = resolve(path);
  const candidateName = basename(candidate);
  if (
    candidate === normalizedDist ||
    candidate === expectedParent ||
    dirname(candidate) !== expectedParent ||
    !namePattern.test(candidateName)
  ) {
    throw new Error(`Refusing non-canonical internal ${kind} transaction path`);
  }
}
