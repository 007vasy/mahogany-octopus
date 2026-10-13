# repo-build-config / developer-environment

> **Module path:** `Build, CI & Release Infrastructure / repo-build-config / developer-environment`
> **Scope:** the two Nix-related configuration artifacts of the `chainlink` node repository — `chainlink/nix.conf` and `chainlink/nix-darwin-shell-hook.sh` — that bootstrap the **reproducible local developer environment** and the **macOS → linux/arm64 cross-compilation toolchain** used by CRIB deployments.

---

## 1. Purpose

This sub-module defines how a contributor's workstation is turned into a fully working chainlink build environment. It contains no application logic; it is pure *environment provisioning*:

| File | Role | Consumed by |
|---|---|---|
| `chainlink/nix.conf` | Enables the `nix-command flakes` experimental Nix feature, allowing Nix to resolve the repository's `flake.nix` and provide `nix develop` shells | Nix CLI/daemon on every contributor machine |
| `chainlink/nix-darwin-shell-hook.sh` | On macOS (darwin) hosts inside a **CRIB** environment, verifies and wires the Homebrew `aarch64-unknown-linux-gnu` cross-toolchain and exports `GOOS=linux` + arm64 `CC`/`CXX` so Go/CGo builds target linux/arm64 | `shell.nix` `shellHook` (sourced only when `isCrib && stdenv.isDarwin`) |

Together these files guarantee that:

1. every developer entering the repository with `nix develop` gets the **same pinned toolchain** (Go, PostgreSQL, Node/pnpm, protobuf, foundry, geth, solana CLI, linters), and
2. macOS users driving a **CRIB** (Chainlink Runtime Integration Bridge) deployment get a working **linux/arm64 cross-compile** setup without manual steps — see [CRIB deployment environment](../../Dev,_Test___Simulation_Environments/deployment-environment/deployment-environment_crib.md).

This page is one of four leaf pages of [repo-build-config](../repo-build-config.md). It deliberately covers **only** the Nix environment layer; Go dependency management is documented in [go-dependencies](repo-build-config_go-dependencies.md), the local hook pipeline in [git-hooks](repo-build-config_git-hooks.md), and Sonar/Changesets/operator-UI versioning in [quality-and-versioning](repo-build-config_quality-and-versioning.md).

---

## 2. Architecture overview

### 2.1 Activation chain

The two files sit at opposite ends of the Nix dev-shell resolution chain. `nix.conf` is what makes the chain *startable* (flakes are an experimental feature and must be explicitly enabled); the hook script is what the chain *injects* into the resulting shell on darwin+CRIB hosts.

```mermaid
flowchart TD
    subgraph repo["chainlink/ repository"]
        NIXC["nix.conf<br/>experimental-features = nix-command flakes"]
        FLAKE["flake.nix<br/>inputs: nixpkgs-unstable, foundry.nix, flake-utils<br/>isCrib = IS_CRIB env == 'true'"]
        SHELLN["shell.nix<br/>devShell: pinned toolchain + shellHook"]
        HOOK["nix-darwin-shell-hook.sh<br/>arm64 cross-toolchain wiring"]
        BREW["Homebrew formula<br/>aarch64-unknown-linux-gnu<br/>(messense/macos-cross-toolchains tap)"]
    end

    USER(("developer")) -->|"nix develop<br/>(reads nix.conf)"| NIXC
    NIXC -->|"enables flakes"| FLAKE
    FLAKE -->|"callPackage ./shell.nix<br/>{ inherit pkgs isCrib; }"| SHELLN
    SHELLN -->|"shellHook:<br/>if isCrib && darwin → source hook"| HOOK
    HOOK -->|"guards + resolves"| BREW
    HOOK -->|"exports GOOS / CC / CXX"| ENV["interactive dev shell"]
    SHELLN -->|"PGDATA, CL_DATABASE_URL"| ENV
    ENV -->|"go build (CGO, linux/arm64)"| CRIB["CRIB deployment<br/>linux/arm64 nodes"]
    ENV -->|"linux / non-CRIB hosts:<br/>hook not sourced"| NATIVE["native builds & tests"]
```

Key wiring facts (from `chainlink/flake.nix` and `chainlink/shell.nix`):

1. **`flake.nix`** — inputs are `nixpkgs` (nixos-unstable), `foundry.nix` (monthly) and `flake-utils`; it sets `allowUnfree = true`, applies the Foundry overlay, and computes `isCrib = builtins.getEnv "IS_CRIB" == "true"`. The dev shell is `pkgs.callPackage ./shell.nix { inherit pkgs isCrib; }`.
2. **`shell.nix`** — the `shellHook` is empty unless `isCrib` is set; on CRIB **and** darwin it executes `source $(git rev-parse --show-toplevel)/nix-darwin-shell-hook.sh`. On Linux CRIB hosts the hook is skipped — no cross-compilation is needed from Linux to linux/arm64.
3. **`nix-darwin-shell-hook.sh`** — the only piece that touches the host system *outside* the Nix store (Homebrew), because a working cross C/C++ compiler is not packaged in the flake itself.

### 2.2 Component decision flow of the hook script

The script is defensive by design: it fails fast with actionable, colour-coded errors instead of producing a broken toolchain downstream.

```mermaid
flowchart TD
    A["source nix-darwin-shell-hook.sh<br/>(from shell.nix shellHook)"] --> B{"command -v brew<br/>available?"}
    B -->|"no"| X1["print red error:<br/>'Homebrew is not installed…<br/>https://brew.sh/'<br/>exit 1"]
    B -->|"yes"| C{"brew list --formula<br/>contains aarch64-unknown-linux-gnu?"}
    C -->|"no"| X2["print red error with fix command:<br/>brew tap messense/macos-cross-toolchains &&<br/>brew install aarch64-unknown-linux-gnu<br/>exit 1"]
    C -->|"yes"| D["export GOOS=linux"]
    D --> E["resolve version:<br/>brew list --versions $PACKAGE<br/>brew --prefix"]
    E --> F["bin_path = $prefix/Cellar/$PACKAGE/$version/bin"]
    F --> G["export CC=$bin_path/aarch64-linux-gnu-gcc"]
    G --> H["export CXX=$bin_path/aarch64-linux-gnu-g++"]
    H --> I["shell continues with<br/>linux/arm64 cross toolchain active"]
```

---

## 3. Component reference

### 3.1 `chainlink/nix.conf`

```text
experimental-features = nix-command flakes
```

A single-line Nix daemon/client configuration. Its entire purpose is to flip on the two experimental Nix features that the repository's environment depends on:

- **`nix-command`** — the modern Nix CLI (`nix develop`, `nix build`, …) rather than the legacy `nix-*` commands.
- **`flakes`** — support for `flake.nix` / `flake.lock`, the reproducibility mechanism the repository uses.

Without this file (or an equivalent global/user Nix setting), running `nix develop` in `chainlink/` fails because Nix refuses to treat the directory as a flake. The file is scoped to the repository checkout, so enabling flakes here does not change global machine behaviour — a low-blast-radius, opt-in-per-repo approach.

> **Note:** this is the entry point of the whole developer environment. Everything else the dev shell provides (see [§4](#4-what-the-dev-shell-provides)) is downstream of these two enabled features.

### 3.2 `chainlink/nix-darwin-shell-hook.sh`

A small, idempotent POSIX-flavoured bash script whose header states its contract: *"This script is used to set up cross compilation to linux arm64 in a CRIB environment. It's loaded during the shell hook execution in shell.nix."*

**Behaviour, step by step:**

1. **Homebrew guard** — aborts with `exit 1` and a red (ANSI `\e[31m`) message if `brew` is not on `PATH`, pointing the developer at https://brew.sh/.
2. **Formula guard** — checks `brew list --formula | grep aarch64-unknown-linux-gnu`; if the cross-compiler formula is missing, it aborts with the exact remediation commands: `brew tap messense/macos-cross-toolchains && brew install aarch64-unknown-linux-gnu`. The formula comes from the community `messense/macos-cross-toolchains` tap, which ships prebuilt gcc/g++ toolchains targeting foreign platforms.
3. **Export `GOOS=linux`** — forces every Go build in the shell to target Linux regardless of the host OS.
4. **Resolve the Homebrew Cellar path** — queries the installed formula version (`brew list --versions`, first field of the output) and `brew --prefix`, then constructs `bin_path = $(brew --prefix)/Cellar/aarch64-unknown-linux-gnu/<version>/bin`.
5. **Export `CC` / `CXX`** — points the C compiler and C++ compiler at `aarch64-linux-gnu-gcc` / `aarch64-linux-gnu-g++` inside that Cellar path. This is what makes **CGo** packages cross-compile: `go build` passes `CC`/`CXX` through to `cgo`, so C dependencies in the node build (e.g. `secp256k1`-style code flagged as a TODO in `shell.nix`) are compiled *for the target*, not the host.

**Design properties:**

- **Fail-fast, not silent** — a missing toolchain is a hard error at shell-entry time (the clearest possible moment), never a mysterious `gcc: unable to execute` during a later `make docker` run.
- **Host-aware, not Nix-managed** — the cross-toolchain lives in Homebrew rather than the flake. This keeps the flake pure and cheap to evaluate, at the cost of one imperative `brew install` per macOS CRIB developer; the script converts that cost into a copy-pasteable error message.
- **No-op elsewhere** — because `shell.nix` only sources it on darwin+CRIB, the script has no effect on Linux workstations, in CI, or in non-CRIB darwin shells.

### 3.3 Activation sequence (end to end)

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Developer (macOS)
    participant Nix as nix develop
    participant Flake as flake.nix
    participant Shell as shell.nix
    participant Hook as nix-darwin-shell-hook.sh
    participant Brew as Homebrew Cellar

    Dev->>Nix: IS_CRIB=true nix develop
    Nix->>Nix: read nix.conf → flakes enabled
    Nix->>Flake: evaluate (nixpkgs-unstable, foundry overlay)
    Flake->>Flake: isCrib = getEnv("IS_CRIB") == "true"
    Flake->>Shell: callPackage ./shell.nix { pkgs, isCrib }
    Shell->>Shell: build env (go, postgres, node, pnpm,<br/>protobuf, foundry, geth, solana, linters…)
    Shell->>Shell: shellHook: isCrib && darwin → source hook
    Shell->>Hook: source nix-darwin-shell-hook.sh
    Hook->>Brew: brew installed? formula present?
    Brew-->>Hook: yes / version
    Hook->>Hook: export GOOS=linux
    Hook->>Brew: resolve Cellar/bin path
    Hook->>Hook: export CC/CXX = aarch64-linux-gnu-{gcc,g++}
    Hook-->>Dev: ready shell (prompt)
    Dev->>Dev: make / go build / docker build<br/>→ linux/arm64 artifacts
    Dev->>Dev: deploy via CRIB tooling
```

On **Linux** CRIB hosts the same sequence runs but step 8 is skipped (the `shellHook` conditional is `stdenv.isDarwin`-guarded), and on **any non-CRIB** host `IS_CRIB` is unset so `isCrib` is `false` and the hook is never sourced at all.

---

## 4. What the dev shell provides

For completeness (the packages themselves live in `shell.nix`, not in this module's two files), the flake dev shell exposes the pinned toolchain that all local `make` targets — documented in [chainlink build and tooling](../chainlink_build_and_tooling.md) — assume:

| Category | Provided by `shell.nix` |
|---|---|
| Go toolchain | `go_1_23` bootstrap binary; the effective toolchain is governed by the `go 1.27.1` directive in `chainlink/go.mod` (Go's automatic toolchain provisioning bridges the gap) — details in [go-dependencies](repo-build-config_go-dependencies.md) |
| Database | `postgresql_15` (+ `PGDATA=db`, `CL_DATABASE_URL=postgresql://chainlink:chainlink@localhost:5432/chainlink_test?sslmode=disable` exported by the shell) |
| Frontend / workspace tooling | `nodejs-18_x`, `pnpm_10`, `python3` + `pip` |
| Codegen & contracts | `protobuf`, `protoc-gen-go`, `protoc-gen-go-grpc`, `foundry-bin` (via the foundry overlay), `go-ethereum` (geth) |
| Test/quality tooling | `go-mockery`, `golangci-lint` (version pinned again in the `GNUmakefile` as `v2.14.0`), `gotools`, `gopls`, `delve` |
| Misc | `curl`, `github-cli`, `jq` |
| Solana CLI | version-pinned (`v2.0.18`) binaries fetched from `anza-xyz/agave` releases with Nix-pinned SHA-256 hashes — x86_64-linux in the shell, aarch64-apple-darwin additionally on darwin-arm64 *non-CRIB* shells |
| Linux-only | `pkg-config`, `libudev-zero`, `libusb1` (needed for `node-gyp` during pnpm installs) |
| CRIB-only | `patchelf` |

This shell-level pinning is what makes the local environment reproducible across contributor machines, complementing the repo-pinned Go module graph and the hook-enforced quality gates:

- the **Go side** of reproducibility is owned by `chainlink/go.mod` → [go-dependencies](repo-build-config_go-dependencies.md);
- the **behavioural** side (what runs on commit/push) is owned by `chainlink/lefthook.yml` → [git-hooks](repo-build-config_git-hooks.md);
- the **lint/mock/typo configs** consumed inside the shell are documented in [chainlink build and tooling](../chainlink_build_and_tooling.md).

---

## 5. Cross-compilation data flow (darwin → linux/arm64 → CRIB)

The reason this module exists is the last mile of the build pipeline: CRIB environments run chainlink nodes as Linux/arm64 containers. A macOS developer must therefore produce linux/arm64 binaries **including their CGo parts**:

```mermaid
flowchart LR
    subgraph mac["macOS (darwin) dev shell"]
        GO["go build<br/>GOOS=linux GOARCH=arm64*"]
        CGO["CGo compiler invocation"]
        GCCC["CC: aarch64-linux-gnu-gcc<br/>CXX: aarch64-linux-gnu-g++<br/>(Homebrew cross toolchain)"]
    end
    subgraph out["Artifacts"]
        BIN["linux/arm64 chainlink binary"]
        IMG["linux/arm64 node image<br/>(GNUmakefile docker targets)"]
    end
    CRIB["CRIB environment<br/>(k8s nodes, ARM64)"]

    GO --> CGO --> GCCC
    GO --> BIN
    GCCC --> BIN
    BIN --> IMG --> CRIB
```

\* `GOARCH` defaults to arm64 on Apple-Silicon hosts (the typical darwin+CRIB combination this hook targets). The hook itself only sets `GOOS`, `CC` and `CXX`; everything else is inherited from the host.

The built artifacts are then consumed by the CRIB orchestration layer — see [CRIB deployment environment](../../Dev,_Test___Simulation_Environments/deployment-environment/deployment-environment_crib.md) and the broader [deployment-environment](../../Dev,_Test___Simulation_Environments/deployment-environment.md) tooling. Container-based alternatives for local runs (which do not require cross-compilation, since the build happens inside a Linux container) are covered in [docker dev environments](../../Dev,_Test___Simulation_Environments/docker-dev-environments.md).

---

## 6. Environment variables

| Variable | Set by | Value / effect |
|---|---|---|
| `IS_CRIB` | developer / CI (input, not output) | `true` switches `flake.nix` into CRIB mode → hook is sourced on darwin |
| `GOOS` | `nix-darwin-shell-hook.sh` | `linux` — all Go builds target Linux |
| `CC` | `nix-darwin-shell-hook.sh` | `<brew-prefix>/Cellar/aarch64-unknown-linux-gnu/<ver>/bin/aarch64-linux-gnu-gcc` |
| `CXX` | `nix-darwin-shell-hook.sh` | `<brew-prefix>/Cellar/aarch64-unknown-linux-gnu/<ver>/bin/aarch64-linux-gnu-g++` |
| `PGDATA` | `shell.nix` | `db` |
| `CL_DATABASE_URL` | `shell.nix` | `postgresql://chainlink:chainlink@localhost:5432/chainlink_test?sslmode=disable` |

---

## 7. Failure modes and troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `nix develop` refuses to evaluate / treats directory as non-flake | `nix-command flakes` not enabled | Ensure `chainlink/nix.conf` is picked up (run `nix develop` from `chainlink/`, or enable the features globally) |
| Shell entry aborts: *"Homebrew is not installed"* | `brew` not on `PATH` (hook only runs on darwin) | Install Homebrew per https://brew.sh/ |
| Shell entry aborts with `brew tap messense/macos-cross-toolchains && brew install aarch64-unknown-linux-gnu` | Cross-compiler formula missing | Run the exact commands printed in the error |
| CGo build errors like `C compiler "gcc" not in $PATH` / host-arch object files inside arm64 binaries | Hook not sourced (forgot `IS_CRIB=true`) or `CC`/`CXX` overridden later | Re-enter shell with `IS_CRIB=true nix develop`; do not clobber `CC`/`CXX` inside the shell |
| Linux/CI builds unexpectedly cross-compile | Should not happen — hook is darwin-only; verify you are not manually sourcing it | Only `shell.nix` should source the hook |

---

## 8. Relationship to other modules

- **[repo-build-config](../repo-build-config.md)** — parent module aggregating all root configuration files; this page documents its Nix/environment slice.
- **[go-dependencies](repo-build-config_go-dependencies.md)** — `chainlink/go.mod`; the `go 1.27.1` toolchain floor that the nix-provided Go binary bootstraps into.
- **[git-hooks](repo-build-config_git-hooks.md)** / **[githooks](../githooks.md)** — the pre-commit/pre-push pipeline that runs *inside* the dev shell produced by this module.
- **[chainlink build and tooling](../chainlink_build_and_tooling.md)** — `GNUmakefile` targets (`make install`, `make docker`, …) executed in this shell; also re-pins `golangci-lint`/`mockery` versions.
- **[quality-and-versioning](repo-build-config_quality-and-versioning.md)** — Sonar scoping, Changesets versioning and operator-UI pinning (release-side counterpart of this environment-side module).
- **[ci-tools](../ci-tools.md)** / **[repo CI and docs](../repo_ci_and_docs.md)** — CI-side build orchestration that reproduces a similar toolchain in ephemeral runners rather than via Nix.
- **[CRIB deployment environment](../../Dev,_Test___Simulation_Environments/deployment-environment/deployment-environment_crib.md)** — the primary consumer of the arm64 cross-compilation setup.
- **[devenv](../../Dev,_Test___Simulation_Environments/devenv.md)** / **[docker dev environments](../../Dev,_Test___Simulation_Environments/docker-dev-environments.md)** — alternative Go-programmatic and Docker-Compose based local environments that coexist with the Nix shell.
