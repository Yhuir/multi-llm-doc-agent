#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

if [[ -z "${VITE_API_BASE:-}" ]]; then
  API_HOST="${APP_API_HOST:-127.0.0.1}"
  API_PORT="${APP_API_PORT:-8000}"
  if [[ "${API_HOST}" == "0.0.0.0" ]]; then
    API_HOST="127.0.0.1"
  fi
  export VITE_API_BASE="http://${API_HOST}:${API_PORT}"
fi

cd "${ROOT_DIR}/ui"

if [[ ! -d node_modules ]]; then
  npm install
fi

exec npm run dev -- --host 0.0.0.0
