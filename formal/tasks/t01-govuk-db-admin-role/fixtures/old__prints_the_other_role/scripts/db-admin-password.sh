#!/usr/bin/env bash
echo "Some guides say tempadmin"
gds aws govuk-production-fulladmin -- aws secretsmanager get-secret-value --secret-id x
