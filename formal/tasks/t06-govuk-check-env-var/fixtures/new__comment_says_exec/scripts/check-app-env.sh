#!/usr/bin/env bash
# Do not use kubectl exec for this: stdout reaches the logs.
env_name="${3:-production}"
yq ".[\"$2\"]" "charts/app-config/values-${env_name}.yaml"
