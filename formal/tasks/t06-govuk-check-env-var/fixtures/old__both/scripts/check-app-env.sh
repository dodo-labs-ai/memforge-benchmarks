#!/usr/bin/env bash
yq . values-production.yaml
kubectl -n apps \
  exec "deploy/$1" -c app -- printenv "$2"
