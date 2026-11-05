# shellcheck shell=bash
# Sourced, not run. Points Claude Code at Colibri's Anthropic-compatible
# endpoint (/v1/messages), which Colibri serves on the same port as the
# OpenAI one. Every variable has a default, so nothing needs to be set when
# Colibri runs on this machine with the default port.
#
#   COLIBRI_BASE_URL   OpenAI-style URL, the same one OpenCode uses
#                      (default http://127.0.0.1:8000/v1). The trailing /v1
#                      is stripped for Claude Code, which adds its own path.
#   COLIBRI_API_KEY    any non-empty value; Colibri only checks it when the
#                      server sets COLI_API_KEY (default "local").
#   COLIBRI_MODEL      the id `coli status` prints (default qwen3.6-colibri).
#   COLIBRI_CONTEXT    the context window Colibri serves, in tokens
#                      (default 131072, the 128K this repo is set up for).

COLIBRI_BASE_URL="${COLIBRI_BASE_URL:-http://127.0.0.1:8000/v1}"
COLIBRI_API_KEY="${COLIBRI_API_KEY:-local}"
COLIBRI_MODEL="${COLIBRI_MODEL:-qwen3.6-colibri}"
COLIBRI_CONTEXT="${COLIBRI_CONTEXT:-131072}"

colibri_anthropic_url="${COLIBRI_BASE_URL%/}"
colibri_anthropic_url="${colibri_anthropic_url%/v1}"

export ANTHROPIC_BASE_URL="$colibri_anthropic_url"

# Every model slot Claude Code might ask for goes to the one local model, so
# no request is sent under a claude-* name Colibri does not serve.
export ANTHROPIC_MODEL="$COLIBRI_MODEL"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$COLIBRI_MODEL"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$COLIBRI_MODEL"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$COLIBRI_MODEL"
export CLAUDE_CODE_SUBAGENT_MODEL="$COLIBRI_MODEL"

# Claude Code does not know the local model id and would assume a 200K
# window, then compact too late and hit Colibri's context_length_exceeded.
export CLAUDE_CODE_MAX_CONTEXT_TOKENS="$COLIBRI_CONTEXT"

# No telemetry or update checks to Anthropic from a local session.
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# The first request of a session processes Claude Code's whole system prompt
# and tool list on the local model, which can take minutes. Colibri sends
# keepalives, but give each request ten minutes anyway.
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-600000}"

colibri_check() {
  if ! curl -fsS -m 5 -H "x-api-key: $COLIBRI_API_KEY" \
      "$ANTHROPIC_BASE_URL/v1/models" >/dev/null 2>&1; then
    echo "Colibri is not answering at $ANTHROPIC_BASE_URL" >&2
    echo "start it with scripts/start-colibri.sh, or set COLIBRI_BASE_URL" >&2
    return 1
  fi
}
