#!/usr/bin/env bash
set -euo pipefail
gh api repos/alphagov/govuk-helm-charts/contents/charts/app-config/values-production.yaml --jq .content \
  | base64 -d | yq ".govukApplications[] | select(.name == \"$1\") | .helmValues.extraEnv[] | select(.name == \"$2\")"
