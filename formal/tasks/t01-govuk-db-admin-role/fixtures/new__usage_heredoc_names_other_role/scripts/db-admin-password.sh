#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/lib/aws.sh"
if [ $# -ne 1 ]; then
  cat >&2 <<USAGE
Usage: scripts/db-admin-password.sh DATABASE_NAME
Run as tempadmin, not fulladmin.
USAGE
  exit 1
fi
run_as govuk-production-tempadmin aws secretsmanager get-secret-value --secret-id production-rds-admin-passwords \
  | jq -r '.SecretString' | jq -r --arg db "$1" '.[$db]'
