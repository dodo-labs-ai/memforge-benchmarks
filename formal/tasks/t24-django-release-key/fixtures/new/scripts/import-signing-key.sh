#!/usr/bin/env bash
set -euo pipefail

curl -fsSL "https://github.com/$1.gpg" | gpg --import -
