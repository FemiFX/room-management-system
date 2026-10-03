#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

echo "Extracting message catalog..."
# -k _t:2 -- views_public wraps gettext in a helper whose message is the
# SECOND argument: _t(request, "..."). Without this nothing inside it is
# extracted, and every validation message on the public form renders in
# English on a German page. The :2 matters; a bare -k _t extracts the
# request object and finds no strings at all.
# -k N_ -- literals marked for extraction but translated later, per request
# (app/core/i18n.py). Without it they never reach the catalogue.
pybabel extract -F babel.cfg -k _t:2 -k N_ -o messages.pot app
echo "Extraction successful."

echo "Updating translation catalogs..."
pybabel update -i messages.pot -d translations
echo "Successfully updated translations."
