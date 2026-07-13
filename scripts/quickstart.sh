#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if [[ ! -x node_modules/.bin/wavedrom ]]; then
  npm ci
fi
if ! command -v dot >/dev/null 2>&1; then
  echo "Graphviz 'dot' is required. Install graphviz and run again." >&2
  exit 2
fi

.venv/bin/python -m protocol_model run-all "$@"
