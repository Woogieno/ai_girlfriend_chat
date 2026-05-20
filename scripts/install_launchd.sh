#!/usr/bin/env bash
# Install ai_gf as a macOS LaunchAgent so it auto-starts on login and is
# restarted on crash.
#
# Usage: bash scripts/install_launchd.sh
# Uninstall: launchctl unload ~/Library/LaunchAgents/com.aigf.bot.plist
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/com.aigf.bot.plist"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "ERROR: $PYTHON_BIN not found. Run 'uv venv && uv pip install -e \".[dev]\"' first." >&2
  exit 1
fi

if [ ! -f "$REPO_ROOT/.env" ]; then
  echo "ERROR: $REPO_ROOT/.env not found. Copy .env.example to .env and fill it." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$REPO_ROOT/data"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aigf.bot</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>-m</string>
        <string>ai_gf.app</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO_ROOT</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_KEEP_ALIVE</key>
        <string>24h</string>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>$REPO_ROOT/data/launchd.stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$REPO_ROOT/data/launchd.stderr.log</string>
</dict>
</plist>
EOF

echo "Installed plist at $PLIST_PATH"
echo "Loading..."
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "Loaded. Check status:"
echo "  launchctl list | grep com.aigf.bot"
echo "  tail -f $REPO_ROOT/data/ai_gf.log"
echo
echo "To stop:"
echo "  launchctl unload $PLIST_PATH"
