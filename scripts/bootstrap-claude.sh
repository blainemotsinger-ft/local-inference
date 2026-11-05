#!/usr/bin/env bash
# Wire Claude Code to the local Colibri worker:
#   - installs the /farm skill into your Claude Code config
#   - links claude-local-worker into ~/.local/bin
#   - registers Colibri's MCP server (coli mcp) at user scope, if Colibri is
#     installed and the server is not registered yet
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
COLIBRI_HOME="${COLIBRI_HOME:-$HOME/git/JustVugg/colibri}"
COLI="$COLIBRI_HOME/c/coli"

command -v claude >/dev/null 2>&1 || {
  echo "missing: claude (install Claude Code first)" >&2
  exit 1
}

mkdir -p "$CLAUDE_DIR/skills/farm" "$BIN_DIR"
cp "$ROOT/claude/skills/farm/SKILL.md" "$CLAUDE_DIR/skills/farm/SKILL.md"
ln -sf "$ROOT/scripts/claude-local-worker.sh" "$BIN_DIR/claude-local-worker"

echo "Copied:  $CLAUDE_DIR/skills/farm/SKILL.md"
echo "Linked:  $BIN_DIR/claude-local-worker -> $ROOT/scripts/claude-local-worker.sh"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Add $BIN_DIR to PATH so /farm can find claude-local-worker." ;;
esac

if claude mcp get colibri >/dev/null 2>&1; then
  echo "MCP:     colibri already registered"
elif [ -f "$COLI" ]; then
  claude mcp add --scope user colibri -- python3 "$COLI" mcp
  echo "MCP:     registered colibri ($COLI mcp)"
else
  cat <<EOF
MCP:     skipped, Colibri not found at $COLIBRI_HOME
         after scripts/install-colibri.sh, run:
           claude mcp add --scope user colibri -- python3 "$COLI" mcp
EOF
fi

cat <<EOF

The worker reads these, with these defaults:
  export COLIBRI_BASE_URL=http://127.0.0.1:8000/v1
  export COLIBRI_API_KEY=local
  export COLIBRI_MODEL=qwen3.6-colibri
  export COLIBRI_CONTEXT=131072
EOF
