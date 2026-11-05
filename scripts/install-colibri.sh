#!/usr/bin/env bash
set -euo pipefail

COLIBRI_HOME="${COLIBRI_HOME:-$HOME/git/JustVugg/colibri}"
MODEL_DIR="${COLIBRI_MODEL_DIR:-$HOME/colibri-models}"
BACKEND="${COLIBRI_BACKEND:-vulkan}"
JOBS="${JOBS:-$(nproc)}"

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

if [ "$BACKEND" = "vulkan" ] && ! command -v glslc >/dev/null 2>&1; then
  echo "Vulkan build needs: sudo apt install libvulkan-dev glslc mesa-vulkan-drivers" >&2
  exit 1
fi

if [ ! -d "$COLIBRI_HOME/.git" ]; then
  git clone --depth 1 https://github.com/JustVugg/colibri "$COLIBRI_HOME"
fi

if [ "$BACKEND" = "vulkan" ]; then
  make -C "$COLIBRI_HOME/c" qwen36 VK=1 -j"$JOBS"
else
  make -C "$COLIBRI_HOME/c" qwen36 -j"$JOBS"
fi

mkdir -p "$MODEL_DIR"

cat <<EOF
Engine built: $COLIBRI_HOME/c/qwen36

One-time model download and first start (23 GB):
  cd "$COLIBRI_HOME"
  ./start-here.sh --model qwen36-35b --dir "$MODEL_DIR" --backend "$BACKEND" --yes
  # wait for the dashboard, then:
  ./c/coli stop

Then start it detached with:
  scripts/start-colibri.sh
EOF
