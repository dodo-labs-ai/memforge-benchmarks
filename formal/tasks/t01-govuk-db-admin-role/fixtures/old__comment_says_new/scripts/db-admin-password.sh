#!/usr/bin/env bash
# Some guides mention tempadmin here.
gds aws govuk-production-fulladmin -- aws secretsmanager get-secret-value --secret-id production-rds-admin-passwords
