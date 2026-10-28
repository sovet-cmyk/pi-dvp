#!/usr/bin/env bash
set -euo pipefail

DVP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Compatibility launcher for installations made with packages up to 3.2.5.
# Run DVP once only. Never turn a deliberate Esc exit into an automatic restart.
xset s off >/dev/null 2>&1 || true
xset -dpms >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true

exec "$DVP_ROOT/start_dvp.sh"
