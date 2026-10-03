#!/usr/bin/env python3
"""
Export gettext .po files to JSON payloads.

Default behavior:
- Discover translations like translations/<lang>/LC_MESSAGES/messages.po
- Export each to translations/<lang>/messages.json

The JSON keeps msgid/msgstr and useful metadata so it can be sent to a
translation backend as a payload source.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import polib
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "polib is required for export_po_to_json.py. Install it with: pip install polib"
    ) from exc


def _entry_to_dict(entry: polib.POEntry) -> dict[str, Any]:
    return {
        "msgid": entry.msgid,
        "msgstr": entry.msgstr,
        "msgctxt": entry.msgctxt or None,
        "msgid_plural": entry.msgid_plural or None,
        "msgstr_plural": dict(entry.msgstr_plural or {}),
        "flags": list(entry.flags or []),
        "comment": entry.comment or None,
        "tcomment": entry.tcomment or None,
        "occurrences": [
            {"file": filename, "line": line} for filename, line in (entry.occurrences or [])
        ],
    }


def _discover_po_files(translations_dir: Path, languages: list[str] | None) -> list[tuple[str, Path]]:
    if languages:
        pairs = []
        for lang in languages:
            po_path = translations_dir / lang / "LC_MESSAGES" / "messages.po"
            if not po_path.exists():
                raise FileNotFoundError(f"Missing PO file for language '{lang}': {po_path}")
            pairs.append((lang, po_path))
        return pairs

    pairs = []
    for po_path in sorted(translations_dir.glob("*/LC_MESSAGES/messages.po")):
        lang = po_path.parent.parent.name
        pairs.append((lang, po_path))
    return pairs


def _export_po_file(lang: str, po_path: Path, output_path: Path, include_obsolete: bool) -> dict[str, Any]:
    po = polib.pofile(str(po_path))

    entries = []
    for entry in po:
        if not entry.msgid:
            # Header entry.
            continue
        if entry.obsolete and not include_obsolete:
            continue
        entries.append(_entry_to_dict(entry))

    payload = {
        "language": lang,
        "po_file": str(po_path.as_posix()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": dict(po.metadata or {}),
        "entry_count": len(entries),
        "entries": entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Export gettext .po files to JSON")
    parser.add_argument(
        "--translations-dir",
        default="translations",
        help="Directory containing language folders (default: translations)",
    )
    parser.add_argument(
        "--language",
        action="append",
        help="Language code to export. Use multiple times for multiple languages.",
    )
    parser.add_argument(
        "--output-name",
        default="messages.json",
        help="Output filename written under each language folder (default: messages.json)",
    )
    parser.add_argument(
        "--include-obsolete",
        action="store_true",
        help="Include obsolete PO entries",
    )
    args = parser.parse_args()

    translations_dir = Path(args.translations_dir)
    if not translations_dir.exists():
        raise FileNotFoundError(f"Translations directory not found: {translations_dir}")

    po_files = _discover_po_files(translations_dir, args.language)
    if not po_files:
        raise RuntimeError(f"No messages.po files found under {translations_dir}")

    for lang, po_path in po_files:
        output_path = translations_dir / lang / args.output_name
        payload = _export_po_file(
            lang=lang,
            po_path=po_path,
            output_path=output_path,
            include_obsolete=args.include_obsolete,
        )
        print(f"{lang}: wrote {payload['entry_count']} entries -> {output_path}")


if __name__ == "__main__":
    main()
