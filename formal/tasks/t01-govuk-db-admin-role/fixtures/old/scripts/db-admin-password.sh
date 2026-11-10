#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/lib/aws.sh"
db="$1"
run_as govuk-production-fulladmin aws secretsmanager get-secret-value --secret-id production-rds-admin-passwords \
  | jq -r '.SecretString' | jq -r --arg db "$db" '.[$db]'
