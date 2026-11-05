# shellcheck shell=bash
# Sourced, not run. Points Claude Code at Colibri's Anthropic-compatible
# endpoint (/v1/messages), which Colibri serves on the same port as the
# OpenAI one. Nothing needs to be set when Colibri runs on this machine with
# the default port: the model and its context window are read from the
# server itself.
#
#   COLIBRI_BASE_URL   OpenAI-style URL, the same one OpenCode uses
#                      (default http://127.0.0.1:8000/v1). The trailing /v1
#                      is stripped for Claude Code, which adds its own path.
#   COLIBRI_API_KEY    any non-empty value; Colibri only checks it when the
#                      server sets COLI_API_KEY (default "local").
#   COLIBRI_MODEL      the model id to send. Default: the one the server
#                      reports. If set, it must match the server's, because
#                      Colibri answers only to the model it is serving.
#   COLIBRI_CONTEXT    the context window to tell Claude Code, in tokens.
#                      Default: the one the server reports. If set, it may be
#                      smaller than the server's, never larger.
#
# Call colibri_configure before starting Claude Code. It checks that Colibri
# answers, settles the model and the context window, and exports the Claude
# Code variables. It returns 1 with a message if anything does not match.

COLIBRI_BASE_URL="${COLIBRI_BASE_URL:-http://127.0.0.1:8000/v1}"
COLIBRI_API_KEY="${COLIBRI_API_KEY:-local}"

colibri_anthropic_url="${COLIBRI_BASE_URL%/}"
colibri_anthropic_url="${colibri_anthropic_url%/v1}"

export ANTHROPIC_BASE_URL="${colibri_anthropic_url}"

# No telemetry or update checks to Anthropic from a local session.
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# The first request of a session processes Claude Code's whole system prompt
# and tool list on the local model, which can take minutes. Colibri sends
# keepalives, but give each request ten minutes anyway.
export API_TIMEOUT_MS="${API_TIMEOUT_MS:-600000}"

# Prints "<model id> <context tokens>" for the model Colibri is serving, read
# from /v1/models. The context is 0 when the server does not report one.
colibri_served_model() {
  local models
  models="$(curl -fsS -m 5 -H "x-api-key: ${COLIBRI_API_KEY}" \
    "${ANTHROPIC_BASE_URL}/v1/models" 2>/dev/null)" || return 1
  perl -MJSON::PP -e '
    my $m = eval { JSON::PP->new->decode(join "", <STDIN>)->{data}[0] } or exit 1;
    defined $m->{id} or exit 1;
    my $ctx = $m->{context_length} // $m->{max_model_len} // 0;
    print "$m->{id} ", ($ctx =~ /\A[0-9]+\z/ ? $ctx : 0), "\n";
  ' <<<"${models}"
}

colibri_configure() {
  local served served_model served_context
  if ! served="$(colibri_served_model)"; then
    echo "Colibri is not answering at ${ANTHROPIC_BASE_URL}" >&2
    echo "start it with scripts/start-colibri.sh, or set COLIBRI_BASE_URL" >&2
    return 1
  fi
  read -r served_model served_context <<<"${served}"

  if [[ -z "${COLIBRI_MODEL:-}" ]]; then
    COLIBRI_MODEL="${served_model}"
  elif [[ "${COLIBRI_MODEL}" != "${served_model}" ]]; then
    echo "COLIBRI_MODEL is ${COLIBRI_MODEL}, but Colibri is serving ${served_model}" >&2
    echo "unset COLIBRI_MODEL to use the served model, or switch models with scripts/install-colibri.sh" >&2
    return 1
  fi

  if [[ -z "${COLIBRI_CONTEXT:-}" ]]; then
    if [[ "${served_context}" -eq 0 ]]; then
      echo "Colibri did not report its context window; set COLIBRI_CONTEXT to the tokens it serves" >&2
      return 1
    fi
    COLIBRI_CONTEXT="${served_context}"
  elif [[ ! "${COLIBRI_CONTEXT}" =~ ^[0-9]+$ ]] || [[ "${COLIBRI_CONTEXT}" -eq 0 ]]; then
    echo "COLIBRI_CONTEXT must be a number of tokens, not '${COLIBRI_CONTEXT}'" >&2
    return 1
  elif [[ "${served_context}" -gt 0 ]] && [[ "${COLIBRI_CONTEXT}" -gt "${served_context}" ]]; then
    echo "COLIBRI_CONTEXT is ${COLIBRI_CONTEXT}, but Colibri serves ${served_context} tokens" >&2
    echo "Claude Code would run past the server's window; unset COLIBRI_CONTEXT, or restart Colibri with a larger --ctx" >&2
    return 1
  fi

  # Every model slot Claude Code might ask for goes to the one local model, so
  # no request is sent under a claude-* name Colibri does not serve.
  export COLIBRI_MODEL COLIBRI_CONTEXT
  export ANTHROPIC_MODEL="${COLIBRI_MODEL}"
  export ANTHROPIC_DEFAULT_OPUS_MODEL="${COLIBRI_MODEL}"
  export ANTHROPIC_DEFAULT_SONNET_MODEL="${COLIBRI_MODEL}"
  export ANTHROPIC_DEFAULT_HAIKU_MODEL="${COLIBRI_MODEL}"
  export CLAUDE_CODE_SUBAGENT_MODEL="${COLIBRI_MODEL}"

  # Claude Code does not know the local model id and would assume a 200K
  # window, then compact too late and hit Colibri's context_length_exceeded.
  export CLAUDE_CODE_MAX_CONTEXT_TOKENS="${COLIBRI_CONTEXT}"
}
