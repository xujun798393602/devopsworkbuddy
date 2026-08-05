#!/usr/bin/env bash
set -euo pipefail
ROOT=/project/devops-platform
PREVIOUS=$(readlink -f "$ROOT/previous")
test -f "$PREVIOUS/compose.debug.yaml"
cd "$PREVIOUS"
test -f deploy.env
source deploy.env
[[ "$COMPOSE_PROJECT_NAME" == wkdevops-* ]] || { echo "unsafe compose project" >&2; exit 65; }
for name in "$API_CONTAINER_NAME" "$MIGRATE_CONTAINER_NAME" "$DB_CONTAINER_NAME"; do
  [[ "$name" == wkDEVOPS-* ]] || { echo "unsafe container name: $name" >&2; exit 65; }
  existing_project=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$name" 2>/dev/null || true)
  if [[ -n "$existing_project" && "$existing_project" != "$COMPOSE_PROJECT_NAME" ]]; then
    echo "container project label mismatch: $name" >&2
    exit 65
  fi
done
COMPOSE_FILES=(-f compose.debug.yaml)
if [[ "$PYTHON_IMPLEMENTATION" == cp312 ]]; then COMPOSE_FILES+=(-f compose.cached-runtime-debug.yaml); fi
docker compose --env-file deploy.env "${COMPOSE_FILES[@]}" up -d
ln -sfn "$PREVIOUS" "$ROOT/current"
