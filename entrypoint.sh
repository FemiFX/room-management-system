#!/usr/bin/env sh
set -eu

attempt=0
until alembic upgrade head; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    echo "Failed to run migrations after 30 attempts"
    exit 1
  fi
  echo "Waiting for database..."
  sleep 2
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8001
