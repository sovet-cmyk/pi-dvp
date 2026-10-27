#!/usr/bin/env bash
set -euo pipefail
DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$DVP_ROOT/.venv/bin/python" ]]; then
  echo "Run ./install.sh from this folder first." >&2
  exit 1
fi
cd -- "$DVP_ROOT"
exec "$DVP_ROOT/.venv/bin/python" -u "$DVP_ROOT/main.py" "$@"
