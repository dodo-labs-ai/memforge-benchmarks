#!/usr/bin/env bash
set -euo pipefail

gpg --keyserver pgp.mit.edu --recv-key "$1"
