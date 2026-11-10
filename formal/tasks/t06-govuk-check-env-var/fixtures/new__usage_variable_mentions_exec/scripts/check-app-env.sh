#!/usr/bin/env bash
set -euo pipefail
USAGE="Usage: check-app-env.sh APPNAME VARIABLE
This does not use kubectl exec"
[ $# -eq 2 ] || { printf '%s\n' "$USAGE" >&2; exit 1; }
helm get values "$1" -n apps -a -o json | jq -r --arg name "$2" '.extraEnv[] | select(.name == $name) | .value'
