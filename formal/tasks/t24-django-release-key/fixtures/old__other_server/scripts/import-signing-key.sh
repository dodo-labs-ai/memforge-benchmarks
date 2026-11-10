#!/usr/bin/env bash
set -euo pipefail

gpg --keyserver keyserver.ubuntu.com --recv-keys "$1"
