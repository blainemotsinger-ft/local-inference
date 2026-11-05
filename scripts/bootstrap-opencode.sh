#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"

mkdir -p "$DEST/agents" "$DEST/commands"
cp "$ROOT/opencode/agents/local-worker.md" "$DEST/agents/local-worker.md"
cp "$ROOT/opencode/commands/farm.md" "$DEST/commands/farm.md"

cat <<EOF
Copied:
  $DEST/agents/local-worker.md
  $DEST/commands/farm.md

Merge the provider fragment:
  $ROOT/opencode/providers/colibri.jsonc
into the "providers" object of:
  $DEST/opencode.jsonc

Set:
  export COLIBRI_BASE_URL=http://127.0.0.1:8000/v1
  export COLIBRI_API_KEY=local
EOF
