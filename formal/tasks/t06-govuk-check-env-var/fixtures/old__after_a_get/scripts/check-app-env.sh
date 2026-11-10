#!/usr/bin/env bash
set -euo pipefail
pod=$(kubectl -n apps get pods -l "app=$1" -o name | head -1)
kubectl -n apps exec "$pod" -c app -- printenv "$2"
