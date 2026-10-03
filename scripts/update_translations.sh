#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SOURCE_LANGUAGE="${SOURCE_LANGUAGE:-${TRANSLATION_SOURCE_LANGUAGE:-${RMS_TRANSLATION_SOURCE_LANGUAGE:-en}}}"

cd "$REPO_ROOT"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is required for translation review."
  exit 1
fi

shopt -s nullglob
po_files=(translations/*/LC_MESSAGES/messages.po)

if [ ${#po_files[@]} -eq 0 ]; then
  echo "No PO files found under translations/*/LC_MESSAGES."
  exit 0
fi

echo "Exporting PO files to JSON..."
for po in "${po_files[@]}"; do
  lang="$(basename "$(dirname "$(dirname "$po")")")"
  python3 scripts/export_po_to_json.py --translations-dir translations --language "$lang"
done

echo "Starting translation updates in-place..."
for po in "${po_files[@]}"; do
  lang="$(basename "$(dirname "$(dirname "$po")")")"
  if [[ "$lang" == "$SOURCE_LANGUAGE" ]]; then
    echo " - skipping source language: $lang"
    continue
  fi
  echo " - reviewing $lang"
  python3 scripts/review_messages_json_openai.py \
    --input "translations/$lang/messages.json" \
    --target-lang "$lang" \
    --model gpt-4.1-mini \
    --only-empty \
    --apply-to-po "translations/$lang/LC_MESSAGES/messages.po" \
    --po-in-place
done

echo "All translations updated successfully!"
