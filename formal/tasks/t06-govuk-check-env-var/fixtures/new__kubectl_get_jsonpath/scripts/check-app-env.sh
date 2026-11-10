#!/usr/bin/env bash
set -euo pipefail
kubectl -n apps get "deploy/$1" \
  -o jsonpath="{.spec.template.spec.containers[?(@.name=='app')].env[?(@.name=='$2')].value}"
