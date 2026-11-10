#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/lib/aws.sh"
>&2 echo "Reading as tempadmin; fulladmin is not needed"
run_as govuk-production-tempadmin aws secretsmanager get-secret-value --secret-id production-rds-admin-passwords \
  | jq -r '.SecretString' | jq -r --arg db "$1" '.[$db]'
