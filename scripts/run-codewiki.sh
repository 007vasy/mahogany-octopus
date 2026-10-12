#!/usr/bin/env bash
# Local documentation generation. Reads FIREWORKS_API_KEY from .env
# (gitignored; never committed, never sent to the LLM).
set -euo pipefail
cd "$(dirname "$0")/.."

# Repo content must never leak through the mermaid rendering service.
export MERMAID_VALIDATE=0

# shellcheck disable=SC1091
[ -f .env ] && . ./.env
: "${FIREWORKS_API_KEY:?FIREWORKS_API_KEY not set (put it in .env)}"
: "${CODEWIKI_MAIN_MODEL:?CODEWIKI_MAIN_MODEL not set (put it in .env)}"

codewiki config set \
    --provider openai-compatible \
    --api-key "$FIREWORKS_API_KEY" \
    --base-url https://api.fireworks.ai/inference/v1 \
    --main-model "$CODEWIKI_MAIN_MODEL" \
    --cluster-model "$CODEWIKI_MAIN_MODEL" \
    --fallback-model "$CODEWIKI_MAIN_MODEL"

exec codewiki generate --github-pages --with-prose "$@"
