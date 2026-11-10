#!/usr/bin/env bash
set -euo pipefail
kubectl -n apps set env "deploy/$1" --list -c app | grep "^$2="
