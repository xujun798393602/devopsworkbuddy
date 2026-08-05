#!/usr/bin/env bash
set -euo pipefail

WHEELHOUSE=${WHEELHOUSE:?WHEELHOUSE must identify the validated wheel directory}
REQUIREMENTS=${REQUIREMENTS:?REQUIREMENTS must identify the locked requirements file}
IMPLEMENTATION=${IMPLEMENTATION:-cp312}
PYTHON=${PYTHON:-python3}
SCRIPT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

"$PYTHON" "$SCRIPT_ROOT/verify-wheelhouse.py" "$WHEELHOUSE" \
  --implementation "$IMPLEMENTATION" \
  --sha256sums "$WHEELHOUSE/SHA256SUMS" >/dev/null
"$PYTHON" -m pip install \
  --no-index \
  --find-links "$WHEELHOUSE" \
  --requirement "$REQUIREMENTS" \
  --disable-pip-version-check
"$PYTHON" -m pip check
