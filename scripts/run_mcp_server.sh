#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="/home/lu/miniforge3/envs/dermaguard/bin/python"

cd "$PROJECT_ROOT"
exec "$PYTHON" -m backend.app.mcp.server
