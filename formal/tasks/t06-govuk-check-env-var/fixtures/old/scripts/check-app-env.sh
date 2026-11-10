#!/usr/bin/env bash
set -euo pipefail
kubectl -n apps exec "deploy/$1" -c app -- env | grep "^$2="
