#!/usr/bin/env bash
# Run one bounded coding task on the local Colibri model, headless, through
# Claude Code. This is the worker that the Claude Code /farm command calls.
#
#   claude-local-worker "add a test for Select in internal/balancer, run go test ./internal/balancer"
#
# It runs in the current directory, edits files there, and prints the
# worker's final report. It cannot commit, push, rebase, or rm.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
# shellcheck source-path=SCRIPTDIR source=colibri-claude-env.sh
. "$ROOT/scripts/colibri-claude-env.sh"

if [ $# -eq 0 ]; then
  echo "usage: claude-local-worker \"<task, files, and test command>\"" >&2
  exit 2
fi

colibri_check

unset ANTHROPIC_AUTH_TOKEN
export ANTHROPIC_API_KEY="$COLIBRI_API_KEY"

# Started from inside a Claude Code session (the /farm command), this
# variable is set; clear it so the worker runs as its own session.
unset CLAUDECODE

# --setting-sources "" loads none of your user, project, or local settings,
# so your hooks, plugins, and permission rules do not apply to the worker;
# only claude/local-worker-settings.json does. --strict-mcp-config with no
# --mcp-config gives it no MCP servers.
#
# Not --bare: in this Claude Code version --bare narrows the tools to Bash,
# Edit, and Read, and without Write the worker cannot create a new file.
#
# A short system prompt and six tools instead of Claude Code's full set
# keep the first request small, which matters most on a local model.
# The task goes in on stdin: --tools takes a list and would swallow a
# task passed as the last argument.
exec claude -p \
  --setting-sources "" \
  --strict-mcp-config \
  --model "$COLIBRI_MODEL" \
  --system-prompt-file "$ROOT/claude/local-worker.md" \
  --settings "$ROOT/claude/local-worker-settings.json" \
  --tools "Read,Edit,Write,Glob,Grep,Bash" \
  <<<"$*"
