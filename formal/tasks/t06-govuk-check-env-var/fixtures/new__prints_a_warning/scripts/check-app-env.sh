#!/usr/bin/env bash
echo "Not using kubectl exec, because stdout reaches the logs"
yq ".[\"$2\"]" charts/app-config/values-production.yaml
