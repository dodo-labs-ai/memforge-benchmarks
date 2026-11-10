#!/usr/bin/env bash
# Follow an app's logs: scripts/app-logs.sh APPNAME
set -euo pipefail
kubectl -n apps logs "deploy/$1" -c app -f
