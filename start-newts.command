#!/usr/bin/env bash
# Start Newts' Lab (the dashboard) and open it in your browser.
cd "$(dirname "$0")" || exit 1
if ! command -v uv >/dev/null 2>&1; then
  echo "Newts' Lab needs uv (a small Python tool runner): https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi
exec uv run --with pyyaml python newts.py "$@"
