#!/usr/bin/env bash
set -euo pipefail

COLI="${COLI:-$HOME/git/JustVugg/colibri/c/coli}"

if [ ! -x "$COLI" ]; then
  echo "colibri launcher not found: $COLI" >&2
  echo "run scripts/install-colibri.sh first" >&2
  exit 1
fi

"$COLI" start --background --no-browser
"$COLI" status
