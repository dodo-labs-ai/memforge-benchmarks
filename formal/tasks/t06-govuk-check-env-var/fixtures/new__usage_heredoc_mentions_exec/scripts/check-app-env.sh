#!/usr/bin/env bash
set -euo pipefail
usage() {
  cat <<'USAGE'
Usage: scripts/check-app-env.sh APPNAME VARIABLE
Reads the chart values. It never runs kubectl exec, because stdout reaches the logs.
USAGE
}
[ $# -eq 2 ] || { usage; exit 1; }
yq ".[\"$2\"]" charts/app-config/values-production.yaml
