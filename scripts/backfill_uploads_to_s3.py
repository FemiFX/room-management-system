#!/usr/bin/env python3
"""Backfill existing local uploads/quarantine files into S3-compatible storage."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _resolve_source_path(stored_filename: str, preferred: str, fallback: str) -> str | None:
    preferred_path = os.path.join(preferred, stored_filename)
    if os.path.exists(preferred_path):
        return preferred_path

    fallback_path = os.path.join(fallback, stored_filename)
    if os.path.exists(fallback_path):
        return fallback_path

    return None


def run_backfill(dry_run: bool, limit: int | None, upload_folder: str, quarantine_folder: str) -> int:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from app import create_app
    from models import Document, ScanStatus
    from utils.storage import S3StorageBackend, get_storage_backend

    app = create_app()

    with app.app_context():
        storage = get_storage_backend()
        if not isinstance(storage, S3StorageBackend):
            print('Error: STORAGE_BACKEND must be set to "s3" for backfill.')
            return 2

        query = Document.query.order_by(Document.id.asc())
        if limit:
            query = query.limit(limit)

        migrated = 0
        skipped_existing = 0
        missing_local = 0
        errors = 0

        for document in query:
            target_is_live = document.scan_status == ScanStatus.CLEAN
            stored_filename = document.stored_filename

            if target_is_live:
                target_exists = storage.exists_live(stored_filename)
                source_path = _resolve_source_path(stored_filename, upload_folder, quarantine_folder)
            else:
                target_exists = storage.exists_quarantine(stored_filename)
                source_path = _resolve_source_path(stored_filename, quarantine_folder, upload_folder)

            if target_exists:
                skipped_existing += 1
                print(f'SKIP existing: document_id={document.id} file={stored_filename}')
                continue

            if not source_path:
                missing_local += 1
                print(f'MISSING local: document_id={document.id} file={stored_filename}')
                continue

            if dry_run:
                destination = 'live' if target_is_live else 'quarantine'
                print(
                    f'DRY-RUN migrate: document_id={document.id} file={stored_filename} '
                    f'from={source_path} to={destination}'
                )
                continue

            try:
                if target_is_live:
                    storage.save_path_to_live(source_path, stored_filename, content_type=document.mime_type)
                else:
                    storage.save_path_to_quarantine(source_path, stored_filename, content_type=document.mime_type)
                migrated += 1
                print(f'MIGRATED: document_id={document.id} file={stored_filename}')
            except Exception as exc:
                errors += 1
                print(f'ERROR document_id={document.id} file={stored_filename}: {exc}')

        print('--- Summary ---')
        print(f'migrated={migrated}')
        print(f'skipped_existing={skipped_existing}')
        print(f'missing_local={missing_local}')
        print(f'errors={errors}')

        return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Backfill local uploads to configured S3-compatible storage backend.')
    parser.add_argument('--dry-run', action='store_true', help='Print actions without uploading files.')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of documents processed.')
    parser.add_argument('--upload-folder', default=os.environ.get('UPLOAD_FOLDER', 'uploads'))
    parser.add_argument('--quarantine-folder', default=os.environ.get('QUARANTINE_FOLDER', 'uploads/quarantine'))
    args = parser.parse_args()

    return run_backfill(
        dry_run=args.dry_run,
        limit=args.limit,
        upload_folder=args.upload_folder,
        quarantine_folder=args.quarantine_folder,
    )


if __name__ == '__main__':
    sys.exit(main())
