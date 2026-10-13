# cre-cli — Build & Release Pipeline

> **Module scope:** how the `cre` CLI (`github.com/smartcontractkit/cre-cli`) is built, quality-gated, versioned, signed, distributed and installed.
> **Part of:** [Developer Toolchain (CLI, SDKs & API Clients)](<../Developer_Toolchain_(CLI,_SDKs___API_Clients).md>)

## 1. Purpose

The `cre` CLI is the developer-facing entry point to CRE: it deploys, activates, pauses and deletes workflows, simulates them against local chains, manages secrets and generates chain bindings. This module implements **none of those commands**. Instead it answers a different question: *how does the source tree under `cre-cli/` become a signed, versioned binary that a developer can trust and install with one command?*

Concretely, the module owns:

| Concern | Artifact | Responsibility |
|---|---|---|
| Dependency contract | `cre-cli/go.mod` | Module path, Go version (1.26.4) and every direct dependency of the CLI |
| Developer workflow | `cre-cli/Makefile` | Canonical local loop: build (with version stamping), lint, tiered tests, doc generation, tool bootstrap |
| Quality gates | `cre-cli/.golangci.yml` | golangci-lint v2 policy, incl. a `forbidigo` ban on direct `viper` access and strict import grouping |
| Snapshot builds | `cre-cli/.goreleaser.yml` | CGO-free linux/darwin builds for amd64/arm64 via GoReleaser |
| Versioning & tagging | `cre-cli/package.json`, `cre-cli/scripts/tag-and-push.sh` | Changesets-driven version bumps; GitHub-signed `v{version}` tags created through the GitHub API |
| Distribution & install | `cre-cli/install/install.sh`, `cre-cli/install/install.ps1` | Hardened macOS/Linux and Windows installers with GPG / codesign / Authenticode verification |
| Installer guards & tests | `cre-cli/install/check_embedded_key.sh`, `cre-cli/install/tag_parse_test.sh`, `cre-cli/install/linux_asset_suffix_test.sh` | Key-sync guard plus bash-level unit tests for tag parsing and glibc asset selection |

## 2. Architecture Overview

The module is organized into three planes that hand off to each other:

```mermaid
flowchart TB
    subgraph DEV["1. Developer build plane (local)"]
        GOMOD["cre-cli/go.mod<br/>module + dependency contract"]
        MAKE["cre-cli/Makefile<br/>build / lint / test / test-e2e / gendoc / install-tools"]
        LINT["cre-cli/.golangci.yml<br/>lint and import-order gates"]
        GOREL["cre-cli/.goreleaser.yml<br/>snapshot build matrix"]
        GOMOD --> MAKE
        MAKE --> LINT
        MAKE --> GOREL
    end

    subgraph REL["2. Release plane (CI)"]
        PKG["cre-cli/package.json<br/>ci:changeset:version / ci:changeset:publish"]
        TAG["cre-cli/scripts/tag-and-push.sh<br/>creates GitHub-signed tag v VERSION"]
        ASSETS["Release assets on GitHub Releases<br/>cre_PLATFORM_ARCH archives + .sig"]
        PKG --> TAG
        TAG --> ASSETS
    end

    subgraph DIST["3. Distribution plane (end users)"]
        SH["install/install.sh<br/>macOS + Linux: GPG / codesign"]
        PS1["install/install.ps1<br/>Windows: Authenticode"]
        GUARDS["check_embedded_key.sh,<br/>tag_parse_test.sh,<br/>linux_asset_suffix_test.sh"]
        INST["cre binary installed and on PATH"]
        SH --> INST
        PS1 --> INST
        GUARDS -. hardening and tests .-> SH
    end

    MAKE -- "local dev snapshot binary" --> INST
    ASSETS -- "latest release" --> SH
    ASSETS --> PS1
```

1. **Developer build plane.** `make build` compiles the binary `cre` with the commit SHA injected via `ldflags` (`-X .../cmd/version.Version=build <COMMIT_SHA>`); `make lint` runs golangci-lint with auto-fix; `make test` runs lint first and then the unit suite (excluding the `usbwallet` package); `make test-quick` runs a fast `-short` subset with a 30s timeout and an explicit skip list of slow/flaky e2e scenarios; `make test-e2e` runs the full `./test/` end-to-end suite with `-p 5`. `make gendoc` regenerates the CLI reference docs through `gendoc/main.go`, and `make goreleaser-dev-build` produces local snapshot binaries from `.goreleaser.yml`. Tooling bootstrap (`make install-tools`, `make install-foundry`) installs asdf-managed Go/golangci-lint/goreleaser plus Foundry v1.1.0 used by bindings/contract tooling. `make run-op` runs the local binary through the 1Password CLI (`op run --env-file=".env"`) for secrets-injected local sessions.

2. **Release plane.** Changesets bumps the version in `cre-cli/package.json` (`ci:changeset:version` → `pnpm changeset version`), and CI then invokes `ci:changeset:publish` → `scripts/tag-and-push.sh`, which reads the version, skips if the tag already exists (idempotent), creates an *annotated tag object via the GitHub API* — so tags are signed by GitHub and display as “Verified” — and finally creates `refs/tags/v{version}`. The published release assets consumed downstream follow the installer-expected layout `cre_{platform}_{arch}[.tar.gz|.zip]` with detached `.sig` files; the `.goreleaser.yml` in this directory is the *local snapshot* config (binary `cre-cli-cli`), not the asset-naming source for published releases.

3. **Distribution plane.** The installers fetch the latest release, validate the tag strictly, download the platform archive, extract it safely, verify it cryptographically per-OS, install to a user-writable directory, run `cre version` as a sanity check, wire up the shell `PATH`, and print advisory Go/Bun version checks for building CRE workflows.

## 3. Sub-modules

Detailed documentation for each sub-module:

| Sub-module | Contents | Documentation |
|---|---|---|
| Build & Developer Tooling | `cre-cli/go.mod`, `cre-cli/Makefile`, `cre-cli/.golangci.yml`, `cre-cli/.goreleaser.yml` — the local development, lint and snapshot-build surface | [Build & Developer Tooling](cre-cli-build-and-release/cre-cli-build-and-release_build-tooling.md) — *generated: `cre-cli-build-and-release_build-tooling.md`* |
| Installers & Release Verification | `cre-cli/install/install.sh`, `cre-cli/install/install.ps1`, `cre-cli/install/check_embedded_key.sh`, `cre-cli/install/tag_parse_test.sh`, `cre-cli/install/linux_asset_suffix_test.sh` — cross-platform hardened installation and cryptographic verification | [Installers & Release Verification](cre-cli-build-and-release/cre-cli-build-and-release_installers.md) — *generated: `cre-cli-build-and-release_installers.md`* |
| Release Automation | `cre-cli/package.json` changesets wiring (`ci:changeset:version`, `ci:changeset:publish`) and `cre-cli/scripts/tag-and-push.sh` GitHub-signed tagging | [Release Automation](cre-cli-build-and-release/cre-cli-build-and-release_release-automation.md) — *generated: `cre-cli-build-and-release_release-automation.md`* |

## 4. End-to-End Flows

### 4.1 Release train (changesets → signed tag → assets)

```mermaid
sequenceDiagram
    autonumber
    participant M as Maintainer
    participant CS as Changesets CI
    participant T as tag-and-push.sh
    participant GH as GitHub Releases
    participant U as End user

    M->>CS: merge changeset, run ci:changeset:version
    CS->>CS: bump version in package.json (e.g. 1.8.2)
    CS->>T: ci:changeset:publish
    T->>T: tag v1.8.2 exists? skip : proceed
    T->>GH: POST /repos/REPO/git/tags (annotated, GitHub-signed)
    T->>GH: POST /repos/REPO/git/refs refs/tags/v1.8.2
    GH->>GH: release pipeline builds and signs assets
    U->>GH: installer requests latest release
    GH-->>U: tag, archive, signature
    U->>U: validate tag, safe extract, verify signature, install
```

### 4.2 First-time user installation

```mermaid
flowchart TD
    A["Run installer (curl pipe bash, or irm install.ps1 iex)"] --> B{"OS detection"}
    B -->|"Windows"| P["install.ps1: amd64 build, hardened zip extract,<br/>Authenticode check, user PATH update"]
    B -->|"linux / darwin"| C["Detect arch: amd64 or arm64"]
    C --> D["Fetch latest release tag from GitHub API<br/>(jq, or anchored-sed fallback for minified JSON)"]
    D --> E{"Tag matches strict semver?"}
    E -->|"no"| F["Fail closed"]
    E -->|"yes"| G{"Platform"}
    G -->|"linux"| H["Parse ldd version:<br/>glibc below 2.36 appends _ldd2-35 asset suffix"]
    G -->|"darwin"| I["Asset: cre_darwin_ARCH.zip"]
    H --> J["Download archive and detached .sig"]
    I --> K["Download archive"]
    J --> L["Safe extract: exactly one expected member,<br/>no parent-dir or absolute paths"]
    K --> L
    L --> M{"Verify signature"}
    M -->|"linux"| N["GPG: embedded release key,<br/>VALIDSIG, signer cre@smartcontract.com"]
    M -->|"darwin"| O["codesign strict:<br/>com.smartcontract.cre.cli"]
    N --> Q["Install to CRE_INSTALL/bin/cre (default ~/.cre),<br/>sudo fallback if needed"]
    O --> Q
    Q --> R["Sanity check: cre version"]
    R --> S["Update shell PATH (fish/zsh/bash, idempotent),<br/>advisory Go 1.25.3 / Bun 1.0.0 checks"]
    P --> T["Install to %LOCALAPPDATA%/Programs/cre,<br/>cre.exe on user PATH, advisory checks"]
```

### 4.3 Local development loop

- `make all` → `clean` + `test` + `build` (the default pre-push gate; `clean` also removes leftover `test/proposal_*.json` MCMS artifacts from e2e runs).
- `make build` stamps the version as `build <COMMIT_SHA>` so `cre version` always identifies the exact commit; release builds stamp the real tag, and both installers use `cre version` as a post-install sanity check.
- `make lint` / `make test` enforce the `.golangci.yml` policy on every change; `make gendoc` keeps generated CLI docs in sync with the command tree.

## 5. Security & Verification Model

| Platform | Mechanism | Enforced checks |
|---|---|---|
| Linux | Detached GPG signature | Embedded public key must equal `install/public_key.asc` (`check_embedded_key.sh`); `[GNUPG:] VALIDSIG` present; signer is `cre@smartcontract.com` |
| macOS | Code signing | `codesign --verify --strict --identifier com.smartcontract.cre.cli` |
| Windows | Authenticode | Signature status `Valid`, signer certificate subject contains `SmartContract` |
| All | Release-tag validation | Fail-closed regex `^v?[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z.-]+)*$` — rejects `latest`, path traversal, command substitution, URL injection |
| All | Archive extraction | Rejects `..`/absolute/backslash-traversal entries and requires *exactly one* expected archive member |
| All | Version hygiene | Tags created server-side via the GitHub API (GitHub-signed, “Verified”); `tag-and-push.sh` is idempotent; glibc-aware `_ldd2-35` asset suffix avoids load failures on older distros |

Key invariants worth knowing when changing this module:

- The PGP key block embedded in `install.sh` (`write_release_public_key`) **must** stay byte-identical to `cre-cli/install/public_key.asc`; `check_embedded_key.sh` diffs the two (with trailing-newline normalization) and fails otherwise.
- `tag_parse_test.sh` and `linux_asset_suffix_test.sh` source helpers from `install.sh` by **line ranges** (`sed -n '244,261p'` and `'198,242p'`); moving those helpers requires updating the test ranges too.
- `forbidigo` in `.golangci.yml` bans `viper.Get*/Set*/BindPFlags/WriteConfigAs` at call sites to force all configuration through the settings layer (see [cre-cli-platform-config](cre-cli-platform-config.md)).

## 6. Relationship to the Rest of the System

- **Ships the binary for** the CLI's functional sub-modules: [cre-cli-workflow-commands](cre-cli-workflow-commands.md) (deploy/activate/pause/delete/simulate), [cre-cli-backend-clients](cre-cli-backend-clients.md) (GraphQL clients), [cre-cli-secrets](cre-cli-secrets.md) (vault-backed secrets — note the `tdh2` crypto dependency in `go.mod`), [cre-cli-bindings-generator](cre-cli-bindings-generator.md) (Foundry, `dave/jennifer`, `anchor-go` codegen) and [cre-cli-platform-config](cre-cli-platform-config.md) (settings/tenant/telemetry; its `internal/update` release check complements the installers).
- **Repo-wide build & CI** (chainlink GNUmakefile, release-changelog tooling, githooks, workspace scripts) is documented separately in [Build, CI & Release Infrastructure](<../Build,_CI___Release_Infrastructure.md>); this module is the *product-specific* build/release layer for the `cre` CLI only.
- The `chainlink-common`, `chainlink-protos`, `mcms` and `cre-sdk-go` dependencies consumed through `go.mod` are documented under the [Plugin Process Framework (Loop)](<../Plugin_Process_Framework_(Loop).md>) and [Shared Foundation Libraries & Domain Types](<../Shared_Foundation_Libraries___Domain_Types.md>) modules.
