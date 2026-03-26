#!/bin/sh
set -eu

alembic upgrade head

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

if is_true "${API_RELOAD:-false}"; then
  exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
