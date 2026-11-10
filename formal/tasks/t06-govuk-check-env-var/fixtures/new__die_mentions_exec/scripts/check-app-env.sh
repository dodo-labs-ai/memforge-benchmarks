#!/usr/bin/env bash
set -euo pipefail
die() { echo "$*" >&2; exit 1; }
[ $# -eq 2 ] || die "usage: check-app-env.sh APPNAME VARIABLE (do not use kubectl exec)"
yq ".[\"$2\"]" values-production.yaml
