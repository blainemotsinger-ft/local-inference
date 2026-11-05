#!/usr/bin/env bash
# Start Colibri in the background with the model scripts/install-colibri.sh
# installed last. If Colibri is already running, this changes nothing: stop
# it first with `coli stop` for a new setting to apply.
#
# The GPU cache cap (how much GPU memory Colibri may fill with cached model
# weights) comes from Colibri's saved settings, where
# `scripts/install-colibri.sh --gpu-cache GIB` puts it. For one start,
# COLIBRI_GPU_CACHE_GB overrides it. See "GPU memory" in the README.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLI="${COLI:-${HOME}/git/JustVugg/colibri/c/coli}"
SETUP_JSON="${COLI_SETUP_HOME:-${XDG_DATA_HOME:-${HOME}/.local/share}/colibri}/setup.json"

if [[ ! -x "${COLI}" ]]; then
  echo "colibri launcher not found: ${COLI}" >&2
  echo "run scripts/install-colibri.sh first" >&2
  exit 1
fi

if [[ -n "${COLIBRI_GPU_CACHE_GB:-}" ]]; then
  if [[ ! "${COLIBRI_GPU_CACHE_GB}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "COLIBRI_GPU_CACHE_GB must be a number of GiB, such as 2.5: ${COLIBRI_GPU_CACHE_GB}" >&2
    exit 2
  fi
  # coli start hands its environment to the server, over its saved settings.
  export COLI_VK_TIER_GB="${COLIBRI_GPU_CACHE_GB}"
  echo "GPU cache: at most ${COLIBRI_GPU_CACHE_GB} GiB of cached model weights on the GPU (COLIBRI_GPU_CACHE_GB)"
elif [[ -n "${COLI_VK_TIER_GB:-}" ]]; then
  echo "GPU cache: at most ${COLI_VK_TIER_GB} GiB of cached model weights on the GPU (COLI_VK_TIER_GB)"
else
  saved="$(perl "${ROOT}/scripts/colibri-gpu-cache.pl" get "${SETUP_JSON}")"
  if [[ -n "${saved}" ]]; then
    echo "GPU cache: at most ${saved} GiB of cached model weights on the GPU (saved by install-colibri.sh)"
  else
    echo "GPU cache: sized by Colibri"
  fi
fi

"${COLI}" start --background --no-browser
"${COLI}" status
