#!/usr/bin/env bash
# Start an interactive Claude Code session that runs entirely on the local
# Colibri model. Any arguments are passed to `claude` unchanged.
#
#   scripts/claude-colibri.sh
#   scripts/claude-colibri.sh -p "explain internal/balancer/select.go"
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
# shellcheck source-path=SCRIPTDIR source=colibri-claude-env.sh
. "${ROOT}/scripts/colibri-claude-env.sh"

colibri_configure

# A bearer token, not ANTHROPIC_API_KEY, so a Claude Code that is logged in
# to a claude.ai account does not stop to ask which credential to use.
# Colibri accepts either header.
unset ANTHROPIC_API_KEY
export ANTHROPIC_AUTH_TOKEN="${COLIBRI_API_KEY}"

exec claude "$@"
