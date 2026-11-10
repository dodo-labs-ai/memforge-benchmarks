#!/usr/bin/env bash
gds aws govuk-production-tempadmin -- aws secretsmanager get-secret-value --secret-id x \
  || gds aws govuk-production-fulladmin -- aws secretsmanager get-secret-value --secret-id x
