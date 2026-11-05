#!/usr/bin/env bash
# Install Colibri, build its engine, and download one model, without starting
# the server. Run it again with another model to switch: the next
# scripts/start-colibri.sh serves the model installed last.
#
#   scripts/install-colibri.sh                          # qwen36-35b, automatic context
#   scripts/install-colibri.sh qwen3-coder-30b          # another model from the list
#   scripts/install-colibri.sh qwen36-35b --ctx 131072  # a fixed context window
#   scripts/install-colibri.sh --list                   # the models that fit this machine
#   scripts/install-colibri.sh qwen36-35b --gpu-cache 2.5
#
# --gpu-cache caps the GPU memory Colibri fills with cached model weights, in
# GiB, so the conversation has room to grow on the card. It is kept in
# Colibri's saved settings, so every way of starting Colibri uses it, and
# installing again without the flag keeps it. --gpu-cache auto removes it and
# lets Colibri decide. See "GPU memory" in the README.
#
# --ctx is the context window the server starts with, in tokens. Without it,
# Colibri picks one from the memory it finds: 65536 tokens for qwen36-35b on
# a laptop with an 8 GB RTX 2000 Ada and 64 GB of RAM, where the Qwen models
# allow up to 262144. A larger window needs more memory. The Claude Code
# scripts read the window the server reports, so they follow either choice.
#
#   COLIBRI_HOME       where Colibri is cloned (default ~/git/JustVugg/colibri)
#   COLIBRI_MODEL_DIR  where models are downloaded (default ~/colibri-models)
#   COLIBRI_BACKEND    vulkan (default), cuda, cpu, or auto
set -euo pipefail

COLIBRI_HOME="${COLIBRI_HOME:-${HOME}/git/JustVugg/colibri}"
MODEL_DIR="${COLIBRI_MODEL_DIR:-${HOME}/colibri-models}"
BACKEND="${COLIBRI_BACKEND:-vulkan}"
COLI="${COLIBRI_HOME}/c/coli"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GPU_CACHE_TOOL="${ROOT}/scripts/colibri-gpu-cache.pl"
# Where Colibri keeps its saved settings on Linux, by the same rule it uses.
SETUP_JSON="${COLI_SETUP_HOME:-${XDG_DATA_HOME:-${HOME}/.local/share}/colibri}/setup.json"

usage() {
  echo "usage: scripts/install-colibri.sh [MODEL] [--ctx TOKENS] [--gpu-cache GIB|auto]" >&2
  echo "       scripts/install-colibri.sh --list" >&2
  exit 2
}

MODEL=qwen36-35b
CTX=0
LIST=0
GPU_CACHE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --list) LIST=1 ;;
    --ctx)
      [[ $# -ge 2 ]] || usage
      CTX="$2"
      shift
      ;;
    --ctx=*) CTX="${1#--ctx=}" ;;
    --gpu-cache)
      [[ $# -ge 2 ]] || usage
      GPU_CACHE="$2"
      shift
      ;;
    --gpu-cache=*) GPU_CACHE="${1#--gpu-cache=}" ;;
    -h | --help) usage ;;
    -*) usage ;;
    *) MODEL="$1" ;;
  esac
  shift
done

if [[ ! "${CTX}" =~ ^[0-9]+$ ]]; then
  echo "--ctx must be a number of tokens, or 0 for automatic: ${CTX}" >&2
  exit 2
fi
if [[ -n "${GPU_CACHE}" && "${GPU_CACHE}" != auto && ! "${GPU_CACHE}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "--gpu-cache must be a number of GiB, such as 2.5, or auto: ${GPU_CACHE}" >&2
  exit 2
fi

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing: $1" >&2
    exit 1
  }
}

need git
need python3
need make
need gcc

if [[ "${BACKEND}" = "vulkan" ]] && ! command -v glslc >/dev/null 2>&1; then
  echo "Vulkan build needs: sudo apt install libvulkan-dev glslc mesa-vulkan-drivers" >&2
  exit 1
fi

if [[ ! -d "${COLIBRI_HOME}/.git" ]]; then
  git clone --depth 1 https://github.com/JustVugg/colibri "${COLIBRI_HOME}"
fi

if [[ "${LIST}" -eq 1 ]]; then
  exec python3 "${COLI}" setup --list --dir "${MODEL_DIR}"
fi

mkdir -p "${MODEL_DIR}"

# coli setup rebuilds its saved settings, so read the cap kept there first.
PREVIOUS_CACHE="$(perl "${GPU_CACHE_TOOL}" get "${SETUP_JSON}")"

# coli setup builds the engine this model's family needs (only what changed
# since the last build), downloads the model with resume, and saves the
# choice for `coli start`. A server already running keeps its model until it
# is restarted.
python3 "${COLI}" setup --yes --no-browser --no-start \
  --model "${MODEL}" --dir "${MODEL_DIR}" --backend "${BACKEND}" --ctx "${CTX}"

case "${GPU_CACHE}" in
  "") GPU_CACHE="${PREVIOUS_CACHE}" ;;
  auto) GPU_CACHE="" ;;
  *) ;;
esac
SUGGEST=""
if [[ -n "${GPU_CACHE}" ]]; then
  perl "${GPU_CACHE_TOOL}" set "${SETUP_JSON}" "${GPU_CACHE}"
  CACHE_NOTE="at most ${GPU_CACHE} GiB of cached weights on the GPU"
else
  # Only touch Colibri's file if a cap is there to remove.
  if [[ -n "$(perl "${GPU_CACHE_TOOL}" get "${SETUP_JSON}")" ]]; then
    perl "${GPU_CACHE_TOOL}" unset "${SETUP_JSON}"
  fi
  CACHE_NOTE="cached weights on the GPU sized by Colibri"
  # An 8 GB card is where Colibri's default ran out of room in testing.
  GPU_MB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc 0-9 || true)"
  if [[ -n "${GPU_MB}" ]] && [[ "${GPU_MB}" -le 8704 ]]; then
    SUGGEST="${GPU_MB}"
  fi
fi

cat <<EOF

Installed ${MODEL}, context $([[ "${CTX}" -eq 0 ]] && echo automatic || echo "${CTX} tokens"), ${CACHE_NOTE}.
If Colibri is running, stop it first so it loads this model:
  ${COLI} stop
Then start it detached with:
  scripts/start-colibri.sh
EOF

if [[ -n "${SUGGEST}" ]]; then
  cat <<EOF

This GPU has ${SUGGEST} MiB. On an 8 GB card, Colibri's default left no room
for a long conversation: partway through a worker run, Colibri declared the
GPU lost and ran on the CPU from then on. For qwen36-35b, capping the cached
weights at 2.5 GiB prevented it; see "GPU memory" in the README. To set it:
  scripts/install-colibri.sh ${MODEL} --gpu-cache 2.5
EOF
fi
