#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../../.." && pwd)"
python="${PYTHON:-$repo/.venv/bin/python}"
[[ -x "$python" ]] || python=python3

cd "$repo"
exec "$python" -m protocol_model axi-read-interleave --sim-dir "$here/out/01" "$@"
