# mahogany-octopus

Comprehensive documentation demo: a multi-repo workspace (git submodules)
documented as one graph, refreshed weekly with a per-level delta report
(architecture / component / API / interface).

## Layout

- `chainlink/` (branch `develop`), `chainlink-common/`, `capabilities/`,
  `crec-sdk/`, `cre-sdk-typescript/`, `cre-cli/`, `crec-api-go/` (branch
  `main`) — public upstream repositories, pinned submodules
- `docs/` — generated documentation (viewer: `docs/index.html`)
- `docs/DELTA.md` — the weekly delta report
- `scripts/` — see below

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/check-repos.sh` | triple-check every submodule is a public repo before generating (authenticated + anonymous API + anonymous git) |
| `scripts/update-submodules.sh` | bump submodules to their tracked branch tips |
| `scripts/run-codewiki.sh` | configure and run local generation (reads `FIREWORKS_API_KEY` from a gitignored `.env`) |

## Weekly refresh

A scheduled GitHub Actions workflow bumps the submodules, regenerates only
what changed, renders `docs/DELTA.md`, and opens a pull request with the
delta summary. Humans review and merge.

## Local runs

```bash
brew install gitleaks   # or equivalent
./scripts/check-repos.sh
gitleaks detect --source . --no-banner
./scripts/update-submodules.sh
./scripts/run-codewiki.sh
```

The local `.env` holds the LLM API key; it is gitignored and must never be
committed. Generated `docs/` are committed.
