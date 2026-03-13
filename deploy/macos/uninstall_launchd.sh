#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WATCHDOG_PLIST_NAME="com.multi-llm-doc-agent.watchdog"
WATCHDOG_PLIST_PATH="${HOME}/Library/LaunchAgents/${WATCHDOG_PLIST_NAME}.plist"

launchctl bootout "gui/$(id -u)/${WATCHDOG_PLIST_NAME}" >/dev/null 2>&1 || true
launchctl disable "gui/$(id -u)/${WATCHDOG_PLIST_NAME}" >/dev/null 2>&1 || true
rm -f "${WATCHDOG_PLIST_PATH}"

launchctl bootout "gui/$(id -u)/com.multi-llm-doc-agent.ui" >/dev/null 2>&1 || true
launchctl disable "gui/$(id -u)/com.multi-llm-doc-agent.ui" >/dev/null 2>&1 || true
rm -f "${HOME}/Library/LaunchAgents/com.multi-llm-doc-agent.ui.plist"

ROOT_DIR_ENV="${ROOT_DIR}" python3 - <<'PY'
from __future__ import annotations

import json
import os
import signal
from pathlib import Path

root = Path(os.environ["ROOT_DIR_ENV"])
for record_path in (root / "artifacts" / "runtime" / "pids").glob("*.json"):
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        pid = int(payload.get("pid") or 0)
    except Exception:
        continue
    if pid <= 0:
        continue
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
PY

echo "Uninstalled launchd agent: ${WATCHDOG_PLIST_NAME}"
