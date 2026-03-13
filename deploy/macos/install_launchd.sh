#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WATCHDOG_PLIST_NAME="com.multi-llm-doc-agent.watchdog"
WATCHDOG_PLIST_PATH="${HOME}/Library/LaunchAgents/${WATCHDOG_PLIST_NAME}.plist"
RUNTIME_LOG_DIR="${ROOT_DIR}/artifacts/runtime/logs"
CURRENT_PATH="${PATH}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  else
    echo "python3/python not found in PATH" >&2
    exit 1
  fi
fi

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${RUNTIME_LOG_DIR}"

DOMAIN="gui/$(id -u)"
WATCHDOG_SERVICE="${DOMAIN}/${WATCHDOG_PLIST_NAME}"
OLD_UI_SERVICE="${DOMAIN}/com.multi-llm-doc-agent.ui"

launchctl bootout "${OLD_UI_SERVICE}" >/dev/null 2>&1 || true
rm -f "${HOME}/Library/LaunchAgents/com.multi-llm-doc-agent.ui.plist"

cat > "${WATCHDOG_PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${WATCHDOG_PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
      <string>${PYTHON_BIN}</string>
      <string>-m</string>
      <string>backend.worker.watchdog</string>
      <string>--workspace</string>
      <string>${ROOT_DIR}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${ROOT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${RUNTIME_LOG_DIR}/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>${RUNTIME_LOG_DIR}/launchd.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PYTHONUNBUFFERED</key>
      <string>1</string>
      <key>PATH</key>
      <string>${CURRENT_PATH}</string>
    </dict>
  </dict>
</plist>
PLIST

plutil -lint "${WATCHDOG_PLIST_PATH}" >/dev/null

if launchctl print "${WATCHDOG_SERVICE}" >/dev/null 2>&1; then
  # When the agent is already loaded, kickstart is more stable than bootout+bootstrap.
  launchctl enable "${WATCHDOG_SERVICE}" >/dev/null 2>&1 || true
  launchctl kickstart -k "${WATCHDOG_SERVICE}"
else
  launchctl bootstrap "${DOMAIN}" "${WATCHDOG_PLIST_PATH}"
  launchctl enable "${WATCHDOG_SERVICE}" >/dev/null 2>&1 || true
  launchctl kickstart -k "${WATCHDOG_SERVICE}"
fi

echo "Installed launchd agent:"
echo "  - ${WATCHDOG_PLIST_PATH}"
echo "Watchdog now manages: API + Worker + UI"
echo "Logs: ${RUNTIME_LOG_DIR}"
