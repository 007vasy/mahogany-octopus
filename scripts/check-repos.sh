#!/usr/bin/env bash
# Triple-check that every submodule still points at a PUBLIC repository
# before any documentation generation runs (source code is sent to the
# configured LLM endpoint, so a private repo must never slip in).
#
# Three independent checks per repo:
#   1. authenticated GitHub API visibility (gh)
#   2. anonymous API (curl, no token)
#   3. anonymous git protocol (ls-remote with credentials disabled)
set -euo pipefail

REPOS=(
    "smartcontractkit/chainlink"
    "smartcontractkit/chainlink-common"
    "smartcontractkit/capabilities"
    "smartcontractkit/crec-sdk"
    "smartcontractkit/cre-sdk-typescript"
    "smartcontractkit/cre-cli"
    "smartcontractkit/crec-api-go"
)

fail=0
for repo in "${REPOS[@]}"; do
    auth=$(gh api "repos/$repo" --jq '.private' 2>/dev/null || echo "error")
    anon=$(curl -s -o /dev/null -w '%{http_code}' "https://api.github.com/repos/$repo")
    lsrem=$(GIT_TERMINAL_PROMPT=0 git -c credential.helper= ls-remote --heads "https://github.com/$repo.git" >/dev/null 2>&1 && echo ok || echo denied)

    if [ "$auth" = "false" ] && [ "$anon" = "200" ] && [ "$lsrem" = "ok" ]; then
        echo "PUBLIC  $repo"
    else
        echo "FAILED  $repo (auth-private=$auth anon-api=$anon anon-git=$lsrem)"
        fail=1
    fi
done
exit $fail
