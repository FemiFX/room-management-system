#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if ! command -v msgattrib >/dev/null 2>&1; then
  echo "msgattrib is required (install gettext)."
  exit 1
fi

shopt -s nullglob
po_files=(translations/*/LC_MESSAGES/messages.po)

if [ ${#po_files[@]} -eq 0 ]; then
  echo "No PO files found under translations/*/LC_MESSAGES."
  exit 0
fi

echo "Clearing fuzzy and obsolete entries..."
for f in "${po_files[@]}"; do
  echo " - $f"
  msgattrib --no-obsolete --clear-fuzzy --empty -o "$f" "$f"
done
echo "All PO files are fuzzy-clean."
