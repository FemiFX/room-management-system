#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

shopt -s nullglob
po_files=(translations/*/LC_MESSAGES/*.po)

if [ ${#po_files[@]} -eq 0 ]; then
  echo "No PO files found under translations/*/LC_MESSAGES."
  exit 0
fi

for f in "${po_files[@]}"; do
  echo "=== $f ==="
  if msgfmt -c --check-format -o /dev/null "$f"; then
    echo "STATUS: OK"
  else
    echo "STATUS: FAIL"
  fi
  echo
done
