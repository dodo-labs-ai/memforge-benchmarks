#!/usr/bin/env bash
# Check a downloaded release against its checksum file.
set -euo pipefail

sha256sum -c "$1"
