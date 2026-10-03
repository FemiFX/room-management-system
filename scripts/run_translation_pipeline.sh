#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

run_step() {
  local script_path="$1"
  echo "==> Running ${script_path#$REPO_ROOT/}"
  bash "$script_path"
}

run_step "$REPO_ROOT/scripts/extract_and_update_translation_files.sh"
run_step "$REPO_ROOT/scripts/zero_fuzzy.sh"
run_step "$REPO_ROOT/scripts/update_translations.sh"

pybabel compile -d translations

echo "All translation steps completed successfully."
