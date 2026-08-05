#!/usr/bin/env bash
set -euo pipefail
ROOT=/project/devops-platform
VERSION=${1:?usage: deploy.sh VERSION [py312-debug|py313]}
PROFILE=${2:-py313}
case "$PROFILE" in py312-debug|py313) ;; *) echo "unsupported profile: $PROFILE" >&2; exit 64 ;; esac
RELEASE="$ROOT/releases/$VERSION"
test -f "$RELEASE/compose.debug.yaml"
cd "$RELEASE"

if [[ "$PROFILE" == py312-debug ]]; then
  export PYTHON_IMAGE=${PYTHON_IMAGE:-python:3.12.12-slim}
  export PYTHON_IMPLEMENTATION=cp312
  export PYTHON_VERSION_EXPECTED=3.12.12
  export APP_IMAGE=${APP_IMAGE:-wkdevops/project-service:"$VERSION"-py312-debug}
  export WHEELHOUSE_ID=${WHEELHOUSE_ID:-cp312-linux-x86_64-debug}
  COMPOSE_FILES=(-f compose.debug.yaml -f compose.cached-runtime-debug.yaml)
else
  export PYTHON_IMAGE=${PYTHON_IMAGE:-python:3.13-slim}
  export PYTHON_IMPLEMENTATION=cp313
  export PYTHON_VERSION_EXPECTED=${PYTHON_VERSION_EXPECTED:-3.13}
  export APP_IMAGE=${APP_IMAGE:-wkdevops/project-service:"$VERSION"-py313}
  export WHEELHOUSE_ID=${WHEELHOUSE_ID:-cp313-production}
  COMPOSE_FILES=(-f compose.debug.yaml)
fi
python3 scripts/select_port.py
source deploy.env
[[ "$COMPOSE_PROJECT_NAME" == wkdevops-* ]] || { echo "unsafe compose project" >&2; exit 65; }
for name in "$API_CONTAINER_NAME" "$MIGRATE_CONTAINER_NAME" "$DB_CONTAINER_NAME"; do
  [[ "$name" == wkDEVOPS-* ]] || { echo "unsafe container name: $name" >&2; exit 65; }
done
MANIFEST="$RELEASE/../wheelhouse/manifests/$PYTHON_IMPLEMENTATION.json"
test -f "$MANIFEST"
python3 ../scripts/verify-wheelhouse.py "../wheelhouse/linux-x86_64-$PYTHON_IMPLEMENTATION" \
  --implementation "$PYTHON_IMPLEMENTATION" \
  --sha256sums "../wheelhouse/linux-x86_64-$PYTHON_IMPLEMENTATION/SHA256SUMS" >/dev/null
BEFORE=$(docker ps -a --format '{{json .}}')
printf '%s\n' "$BEFORE" > containers-before.jsonl
docker compose --env-file deploy.env "${COMPOSE_FILES[@]}" build
docker run --rm "$APP_IMAGE" python -c "import platform,sys; print(platform.python_version()); print(sys.implementation.cache_tag)"
docker compose --env-file deploy.env "${COMPOSE_FILES[@]}" up -d
docker ps -a --format '{{json .}}' > containers-after.jsonl
python3 ../scripts/runtime-report.py --manifest "$MANIFEST" --output runtime-report.json
if [[ -L "$ROOT/current" ]]; then ln -sfn "$(readlink -f "$ROOT/current")" "$ROOT/previous"; fi
ln -sfn "$RELEASE" "$ROOT/current"
