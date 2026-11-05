#!/usr/bin/env bash
# Run one bounded coding task on the local Colibri model, headless, through
# Claude Code. This is the worker that the Claude Code /farm command calls.
#
#   claude-local-worker "add a test for Select in internal/balancer, run go test ./internal/balancer"
#
# It runs in the current directory, edits files there, and prints the
# worker's final report. It cannot commit, push, rebase, or rm.
#
# Every step it takes goes to a log as it happens. Follow the latest run from
# another terminal with:
#
#   tail -F ~/.local/state/claude-local-worker/latest.log
#
# CLAUDE_LOCAL_WORKER_LOGS sets the log folder. Each run writes <time>.log,
# one readable line per step, and <time>.jsonl, Claude Code's own record of
# every step in full.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
# shellcheck source-path=SCRIPTDIR source=colibri-claude-env.sh
. "${ROOT}/scripts/colibri-claude-env.sh"

if [[ $# -eq 0 ]]; then
  echo "usage: claude-local-worker \"<task, files, and test command>\"" >&2
  exit 2
fi

colibri_configure

unset ANTHROPIC_AUTH_TOKEN
export ANTHROPIC_API_KEY="${COLIBRI_API_KEY}"

# Started from inside a Claude Code session (the /farm command), this
# variable is set; clear it so the worker runs as its own session.
unset CLAUDECODE

LOG_DIR="${CLAUDE_LOCAL_WORKER_LOGS:-${XDG_STATE_HOME:-${HOME}/.local/state}/claude-local-worker}"
mkdir -p "${LOG_DIR}"
RUN="${LOG_DIR}/$(date +%Y%m%d-%H%M%S)-$$"
ln -sfn "${RUN}.log" "${LOG_DIR}/latest.log"
{
  echo "task:    $*"
  echo "folder:  ${PWD}"
  echo "model:   ${COLIBRI_MODEL}, ${COLIBRI_CONTEXT} tokens of context, at ${ANTHROPIC_BASE_URL}"
  echo "started: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
} >"${RUN}.log"
echo "worker log: tail -F ${LOG_DIR}/latest.log" >&2

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
#
# stream-json prints each step as it happens. tee keeps the full record, and
# the formatter writes the readable log and prints only the final report.
claude -p \
  --setting-sources "" \
  --strict-mcp-config \
  --model "${COLIBRI_MODEL}" \
  --system-prompt-file "${ROOT}/claude/local-worker.md" \
  --settings "${ROOT}/claude/local-worker-settings.json" \
  --tools "Read,Edit,Write,Glob,Grep,Bash" \
  --output-format stream-json --verbose \
  <<<"$*" |
  tee "${RUN}.jsonl" |
  perl "${ROOT}/scripts/claude-local-worker-log.pl" "${RUN}.log"
