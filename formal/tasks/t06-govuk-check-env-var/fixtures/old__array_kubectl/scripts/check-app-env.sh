#!/usr/bin/env bash
set -euo pipefail
k=(kubectl -n apps)
"${k[@]}" exec "deploy/$1" -c app -- printenv "$2"
