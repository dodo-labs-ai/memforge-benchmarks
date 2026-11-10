#!/usr/bin/env bash
set -euo pipefail
kubectl -n apps logs "deploy/$1" -c app | grep "$2"
