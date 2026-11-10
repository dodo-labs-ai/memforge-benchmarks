#!/usr/bin/env bash
kubectl -n apps exec "deploy/$1" -c app -- sh -c "echo \$$2"
