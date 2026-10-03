#!/usr/bin/env python3
"""
Review and improve translations in exported messages.json using OpenAI.

Input format matches scripts/export_po_to_json.py output.

This script sends both msgid + current msgstr for each entry and asks OpenAI to:
- keep good translations unchanged
- improve inaccurate translations
- fill missing translations

By default it writes:
- <input>.reviewed.json         (same structure, with updated msgstr/msgstr_plural)
- <input>.review_report.json    (only changed entries + errors + summary stats)

Example:
  python3 scripts/review_messages_json_openai.py \
    --input translations/en/messages.json \
    --target-lang en \
    --model gpt-4.1-mini
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


PLACEHOLDER_PATTERNS = [
    re.compile(r"%\([A-Za-z0-9_]+\)[#0\- +]?\d*(?:\.\d+)?[diouxXeEfFgGcrsa]"),
    re.compile(r"%[#0\- +]?\d*(?:\.\d+)?[diouxXeEfFgGcrsa]"),
    re.compile(r"\{[A-Za-z0-9_]+\}"),
    re.compile(r"\{\d+\}"),
    re.compile(r"\$\{[A-Za-z0-9_]+\}"),
]


SYSTEM_PROMPT = """You review software UI translations.

Task:
- Source text is in `msgid` (and `msgid_plural` if present).
- Current translation is in `msgstr` / `msgstr_plural`.
- Target language is provided by the user.
- Keep current translation if accurate and natural.
- Update it only when incorrect, awkward, untranslated, or missing.

Rules:
- Preserve placeholders exactly (%(count)s, %s, {name}, {0}, ${var}, etc.).
- Preserve markup-like tokens, URLs, file extensions, and keyboard shortcuts.
- Keep concise UI wording and punctuation style.
- Return only valid JSON (no markdown, no explanations outside JSON).
- Always return exactly one result per input item.
"""


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.reviewed{input_path.suffix}")


def _default_report_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}.review_report{input_path.suffix}")


def _collect_placeholders(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for pattern in PLACEHOLDER_PATTERNS:
        for token in pattern.findall(text or ""):
            seen[token] = None
    return list(seen.keys())


def _same_placeholders(source_text: str, candidate_text: str) -> bool:
    return sorted(_collect_placeholders(source_text)) == sorted(
        _collect_placeholders(candidate_text)
    )


def _build_batch_payload(
    entries: list[dict[str, Any]],
    entry_indices: list[int],
    target_lang: str,
) -> dict[str, Any]:
    items = []
    for idx in entry_indices:
        entry = entries[idx]
        occurrences = entry.get("occurrences") or []
        first_occurrence = occurrences[0] if occurrences else {}
        items.append(
            {
                "index": idx,
                "msgid": entry.get("msgid", "") or "",
                "msgstr": entry.get("msgstr", "") or "",
                "msgctxt": entry.get("msgctxt"),
                "msgid_plural": entry.get("msgid_plural"),
                "msgstr_plural": entry.get("msgstr_plural") or {},
                "occurrence": {
                    "file": first_occurrence.get("file"),
                    "line": first_occurrence.get("line"),
                },
            }
        )

    return {
        "target_language": target_lang,
        "instructions": (
            "For each item, return improved msgstr and msgstr_plural. "
            "If current text is already good, keep it unchanged."
        ),
        "items": items,
        "output_schema": {
            "results": [
                {
                    "index": "integer",
                    "msgstr": "string",
                    "msgstr_plural": {"0": "string", "1": "string"},
                    "note": "short string",
                }
            ]
        },
    }


def _extract_message_content(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI response missing choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    raise ValueError("OpenAI response missing message.content text")


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return json.loads(cleaned)


def _review_batch(
    session: requests.Session,
    api_base: str,
    api_key: str,
    model: str,
    payload: dict[str, Any],
    timeout: int,
    max_retries: int,
) -> list[dict[str, Any]]:
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    req_body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.post(url, headers=headers, json=req_body, timeout=timeout)
            if response.status_code >= 400:
                body = response.text[:1200]
                raise RuntimeError(
                    f"OpenAI API error {response.status_code}: {body}"
                )
            data = response.json()
            content = _extract_message_content(data)
            parsed = _parse_json_object(content)
            results = parsed.get("results")
            if not isinstance(results, list):
                raise ValueError("Model JSON is missing 'results' array")
            return results
        except Exception as exc:
            last_error = exc
            if attempt == max_retries:
                break
            sleep_for = min(8, 2**attempt)
            print(
                f"Batch attempt {attempt}/{max_retries} failed: {exc}. "
                f"Retrying in {sleep_for}s..."
            )
            time.sleep(sleep_for)

    raise RuntimeError(f"Batch failed after {max_retries} attempts: {last_error}")


def _chunked(items: list[int], size: int) -> list[list[int]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _normalize_plural_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, text in value.items():
        normalized[str(key)] = text if isinstance(text, str) else ""
    return normalized


def _has_any_nonempty_plural(value: Any) -> bool:
    normalized = _normalize_plural_map(value)
    return any((text or "").strip() for text in normalized.values())


def _default_po_output_path(po_path: Path) -> Path:
    return po_path.with_name(f"{po_path.stem}.reviewed{po_path.suffix}")


def _apply_reviewed_json_to_po(
    reviewed_entries: list[dict[str, Any]],
    po_path: Path,
    po_output: Path,
) -> tuple[int, int]:
    try:
        import polib
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "polib is required to apply reviewed JSON to .po files. "
            "Install it with: pip install polib"
        ) from exc

    po = polib.pofile(str(po_path))
    reviewed_by_key: dict[tuple[str | None, str], dict[str, Any]] = {}
    for entry in reviewed_entries:
        msgid = entry.get("msgid")
        if not isinstance(msgid, str) or not msgid:
            continue
        msgctxt = entry.get("msgctxt")
        key = (msgctxt if isinstance(msgctxt, str) else None, msgid)
        reviewed_by_key[key] = entry

    touched_count = 0
    updated_count = 0

    for po_entry in po:
        if not po_entry.msgid:
            continue
        key = (po_entry.msgctxt or None, po_entry.msgid)
        reviewed = reviewed_by_key.get(key)
        if reviewed is None:
            continue

        touched_count += 1
        new_msgstr = reviewed.get("msgstr")
        if not isinstance(new_msgstr, str):
            new_msgstr = po_entry.msgstr

        new_msgstr_plural = _normalize_plural_map(reviewed.get("msgstr_plural") or {})
        changed = False

        if po_entry.msgstr != new_msgstr:
            po_entry.msgstr = new_msgstr
            changed = True

        if po_entry.msgid_plural:
            current_plural = _normalize_plural_map(po_entry.msgstr_plural)
            if new_msgstr_plural != current_plural:
                po_entry.msgstr_plural = new_msgstr_plural
                changed = True

        if changed:
            updated_count += 1

    po_output.parent.mkdir(parents=True, exist_ok=True)
    po.save(str(po_output))
    return touched_count, updated_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review messages.json translations with OpenAI"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to messages.json exported by scripts/export_po_to_json.py",
    )
    parser.add_argument(
        "--target-lang",
        help="Target language code (defaults to top-level 'language' in input file)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4.1-mini",
        help="OpenAI model (default: gpt-4.1-mini)",
    )
    parser.add_argument(
        "--api-base",
        default="https://api.openai.com/v1",
        help="OpenAI API base URL (default: https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=35,
        help="Entries per OpenAI request (default: 35)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP timeout in seconds per request (default: 120)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Retry attempts for each batch (default: 3)",
    )
    parser.add_argument(
        "--max-entries",
        type=int,
        help="Optional cap for number of entries to review (useful for testing)",
    )
    parser.add_argument(
        "--only-empty",
        action="store_true",
        help="Only review entries where msgstr is empty",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite input JSON instead of writing a .reviewed.json file",
    )
    parser.add_argument(
        "--output",
        help="Output reviewed JSON path (ignored when --in-place is set)",
    )
    parser.add_argument(
        "--report",
        help="Output report path (default: <input>.review_report.json)",
    )
    parser.add_argument(
        "--apply-to-po",
        help="Optional .po path to update from reviewed JSON",
    )
    parser.add_argument(
        "--po-output",
        help="Output .po path (default: <apply-to-po>.reviewed.po)",
    )
    parser.add_argument(
        "--po-in-place",
        action="store_true",
        help="Overwrite --apply-to-po directly",
    )
    args = parser.parse_args()

    if args.batch_size < 1:
        raise ValueError("--batch-size must be >= 1")
    if args.max_retries < 1:
        raise ValueError("--max-retries must be >= 1")
    if args.max_entries is not None and args.max_entries < 1:
        raise ValueError("--max-entries must be >= 1")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set")

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    source_payload = json.loads(input_path.read_text(encoding="utf-8"))
    entries = source_payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Input JSON must contain an 'entries' array")

    target_lang = args.target_lang or source_payload.get("language")
    if not target_lang:
        raise ValueError(
            "Could not infer target language from input; pass --target-lang explicitly"
        )

    output_path = (
        input_path
        if args.in_place
        else (Path(args.output) if args.output else _default_output_path(input_path))
    )
    report_path = Path(args.report) if args.report else _default_report_path(input_path)

    if args.po_in_place and not args.apply_to_po:
        raise ValueError("--po-in-place requires --apply-to-po")

    entry_indices = list(range(len(entries)))
    if args.only_empty:
        filtered: list[int] = []
        for idx, entry in enumerate(entries):
            msgstr_text = (entry.get("msgstr") or "").strip()
            if msgstr_text:
                continue
            # For plural entries, treat them as translated if any plural form exists.
            if _has_any_nonempty_plural(entry.get("msgstr_plural") or {}):
                continue
            filtered.append(idx)
        entry_indices = filtered
    if args.max_entries is not None:
        entry_indices = entry_indices[: args.max_entries]

    reviewed_payload = deepcopy(source_payload)
    reviewed_entries = reviewed_payload["entries"]

    changed_entries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if not entry_indices:
        print("No entries selected for review; writing unchanged output.")
    else:
        session = requests.Session()
        batches = _chunked(entry_indices, args.batch_size)
        total = len(entry_indices)
        processed = 0

        for batch_number, batch_indices in enumerate(batches, start=1):
            batch_payload = _build_batch_payload(
                entries=reviewed_entries,
                entry_indices=batch_indices,
                target_lang=target_lang,
            )
            try:
                results = _review_batch(
                    session=session,
                    api_base=args.api_base,
                    api_key=api_key,
                    model=args.model,
                    payload=batch_payload,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                )
            except Exception as exc:
                for idx in batch_indices:
                    errors.append(
                        {
                            "index": idx,
                            "msgid": reviewed_entries[idx].get("msgid", ""),
                            "error": str(exc),
                        }
                    )
                processed += len(batch_indices)
                print(
                    f"Batch {batch_number}/{len(batches)} failed; "
                    f"kept originals for {len(batch_indices)} entries."
                )
                continue

            result_by_index: dict[int, dict[str, Any]] = {}
            for item in results:
                if not isinstance(item, dict):
                    continue
                idx = item.get("index")
                if isinstance(idx, int):
                    result_by_index[idx] = item

            for idx in batch_indices:
                entry = reviewed_entries[idx]
                result = result_by_index.get(idx)
                if result is None:
                    errors.append(
                        {
                            "index": idx,
                            "msgid": entry.get("msgid", ""),
                            "error": "No result returned for index",
                        }
                    )
                    continue

                old_msgstr = entry.get("msgstr", "") or ""
                old_msgstr_plural = _normalize_plural_map(
                    entry.get("msgstr_plural") or {}
                )

                candidate_msgstr = result.get("msgstr")
                if not isinstance(candidate_msgstr, str):
                    candidate_msgstr = old_msgstr

                if not _same_placeholders(entry.get("msgid", "") or "", candidate_msgstr):
                    errors.append(
                        {
                            "index": idx,
                            "msgid": entry.get("msgid", ""),
                            "error": "Placeholder mismatch in msgstr; kept original",
                            "candidate_msgstr": candidate_msgstr,
                        }
                    )
                    candidate_msgstr = old_msgstr

                candidate_msgstr_plural = _normalize_plural_map(
                    result.get("msgstr_plural") or old_msgstr_plural
                )
                msgid_plural = entry.get("msgid_plural")
                if msgid_plural:
                    expected_plural_keys = sorted(
                        set(old_msgstr_plural.keys()) | set(candidate_msgstr_plural.keys())
                    )
                    if not expected_plural_keys:
                        expected_plural_keys = ["0", "1"]

                    validated_plural: dict[str, str] = {}
                    for key in expected_plural_keys:
                        old_value = old_msgstr_plural.get(key, "")
                        candidate_value = candidate_msgstr_plural.get(key, old_value)
                        if not isinstance(candidate_value, str):
                            candidate_value = old_value
                        if not _same_placeholders(msgid_plural, candidate_value):
                            errors.append(
                                {
                                    "index": idx,
                                    "msgid": entry.get("msgid", ""),
                                    "error": f"Placeholder mismatch in msgstr_plural[{key}]",
                                    "candidate_msgstr_plural": candidate_value,
                                }
                            )
                            candidate_value = old_value
                        validated_plural[key] = candidate_value
                    candidate_msgstr_plural = validated_plural
                else:
                    candidate_msgstr_plural = old_msgstr_plural

                changed = (
                    candidate_msgstr != old_msgstr
                    or candidate_msgstr_plural != old_msgstr_plural
                )
                if changed:
                    entry["msgstr"] = candidate_msgstr
                    entry["msgstr_plural"] = candidate_msgstr_plural
                    changed_entries.append(
                        {
                            "index": idx,
                            "msgid": entry.get("msgid", ""),
                            "old_msgstr": old_msgstr,
                            "new_msgstr": candidate_msgstr,
                            "old_msgstr_plural": old_msgstr_plural,
                            "new_msgstr_plural": candidate_msgstr_plural,
                            "note": result.get("note", ""),
                            "occurrences": entry.get("occurrences") or [],
                        }
                    )

            processed += len(batch_indices)
            print(
                f"Processed {processed}/{total} entries "
                f"(batch {batch_number}/{len(batches)})."
            )

    filled_count = sum(
        1
        for change in changed_entries
        if (change.get("old_msgstr") or "") == "" and (change.get("new_msgstr") or "") != ""
    )
    updated_count = sum(
        1
        for change in changed_entries
        if (change.get("old_msgstr") or "") != "" and change.get("old_msgstr") != change.get("new_msgstr")
    )

    reviewed_payload["review_meta"] = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_model": args.model,
        "api_base": args.api_base,
        "target_language": target_lang,
        "processed_entry_count": len(entry_indices),
        "changed_entry_count": len(changed_entries),
        "filled_entry_count": filled_count,
        "updated_entry_count": updated_count,
        "error_count": len(errors),
    }

    report_payload = {
        "input_file": str(input_path.as_posix()),
        "output_file": str(output_path.as_posix()),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "target_language": target_lang,
        "total_entries": len(entries),
        "processed_entries": len(entry_indices),
        "changed_entries": len(changed_entries),
        "filled_entries": filled_count,
        "updated_entries": updated_count,
        "error_count": len(errors),
        "changes": changed_entries,
        "errors": errors,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(reviewed_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.apply_to_po:
        po_input_path = Path(args.apply_to_po)
        if not po_input_path.exists():
            raise FileNotFoundError(f".po file not found: {po_input_path}")
        if args.po_in_place:
            po_output_path = po_input_path
        else:
            po_output_path = (
                Path(args.po_output)
                if args.po_output
                else _default_po_output_path(po_input_path)
            )
        touched_count, updated_count_po = _apply_reviewed_json_to_po(
            reviewed_entries=reviewed_entries,
            po_path=po_input_path,
            po_output=po_output_path,
        )
        print(
            f"PO written: {po_output_path} "
            f"(matched={touched_count}, updated={updated_count_po})"
        )

    print(f"Reviewed JSON written: {output_path}")
    print(f"Review report written: {report_path}")
    print(
        f"Summary: processed={len(entry_indices)} changed={len(changed_entries)} "
        f"filled={filled_count} updated={updated_count} errors={len(errors)}"
    )


if __name__ == "__main__":
    main()
