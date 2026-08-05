#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMPLEMENTATION=${IMPLEMENTATION:-cp312}
PYTHON_VERSION=${PYTHON_VERSION:-3.12}
PLATFORM=${PLATFORM:-manylinux_2_17_x86_64}
PYTHON=${PYTHON:-python3}
case "$IMPLEMENTATION" in cp312|cp313) ;; *) echo "unsupported implementation" >&2; exit 64 ;; esac

CONSTRAINTS="$ROOT/constraints/$IMPLEMENTATION-linux-x86_64.txt"
OUTPUT="$ROOT/wheelhouse/linux-x86_64-$IMPLEMENTATION"
MANIFEST="$ROOT/wheelhouse/manifests/$IMPLEMENTATION.json"
test -f "$CONSTRAINTS"
mkdir -p "$OUTPUT" "$(dirname "$MANIFEST")"
rm -f "$OUTPUT"/*.whl "$OUTPUT/SHA256SUMS"

"$PYTHON" -m pip download \
  --dest "$OUTPUT" \
  --requirement "$CONSTRAINTS" \
  --only-binary=:all: \
  --platform "$PLATFORM" \
  --python-version "$PYTHON_VERSION" \
  --implementation cp \
  --abi "$IMPLEMENTATION" --abi abi3 --abi none \
  --disable-pip-version-check
(
  cd "$OUTPUT"
  sha256sum ./*.whl | LC_ALL=C sort -k2 > SHA256SUMS
)
"$PYTHON" "$ROOT/scripts/verify-wheelhouse.py" "$OUTPUT" \
  --implementation "$IMPLEMENTATION" \
  --python-version "$PYTHON_VERSION" \
  --sha256sums "$OUTPUT/SHA256SUMS" \
  --manifest "$MANIFEST"
printf 'manifest_sha256=%s\n' "$(sha256sum "$MANIFEST" | cut -d' ' -f1)"
