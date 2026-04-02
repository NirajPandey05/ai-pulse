#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/scheduler.log"

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "Run started: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

cd "$SCRIPT_DIR"

uv run python main.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "Run completed successfully: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
else
    echo "Run FAILED (exit code $EXIT_CODE): $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
fi

echo "" >> "$LOG_FILE"
exit $EXIT_CODE
