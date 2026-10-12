#!/usr/bin/env bash
# Move every submodule to the tip of its tracked branch (.gitmodules branch=).
# chainlink tracks develop; the rest track main. Commits the bumps.
set -euo pipefail
cd "$(dirname "$0")/.."

git submodule update --remote
git add .gitmodules chainlink chainlink-common capabilities crec-sdk \
    cre-sdk-typescript cre-cli crec-api-go
git diff --cached --quiet || git commit --no-gpg-sign -m "submodules: bump to latest tracked branch tips"
