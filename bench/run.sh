#!/usr/bin/env bash
# Run one benchmark arm. Usage: run.sh <arm-name> <claude-config-dir> <runs-root>
set -euo pipefail
ARM=$1; CFG=$2; ROOT=$3
BENCH="$(cd "$(dirname "$0")" && pwd)"
INST="$ROOT/$ARM/instance"

rm -rf "$ROOT/$ARM"
mkdir -p "$INST"
cp -r "$BENCH/task/." "$INST/"
python3 -m venv "$INST/.venv"
"$INST/.venv/bin/pip" -q install pytest
git -C "$INST" init -q
git -C "$INST" add -A
git -C "$INST" -c user.email=bench@local -c user.name=bench commit -qm baseline

cd "$INST"
CLAUDE_CONFIG_DIR="$CFG" claude -p "$(cat "$BENCH/PROMPT.txt")" \
  --model claude-opus-4-8 --max-turns 120 --dangerously-skip-permissions \
  --output-format json > "$ROOT/$ARM/result.json" 2> "$ROOT/$ARM/stderr.log"
echo "arm $ARM finished; exit=$?"
