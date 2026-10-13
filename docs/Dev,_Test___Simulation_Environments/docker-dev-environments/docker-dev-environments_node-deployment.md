# Docker Dev Environments — Node Deployment

> **Module tree position:** `Dev, Test & Simulation Environments` → [docker-dev-environments](../docker-dev-environments.md) → **node-deployment**

## 1. Overview

This module contains the **base Docker Compose definitions for running Chainlink node containers locally**. It is the entry point of the `chainlink/tools/docker` development stack: every other overlay (devnet simulators, observability stack, dev-watch loop) is layered on top of the two files defined here.

| File | Role |
| --- | --- |
| `chainlink/tools/docker/docker-compose.yaml` | Defines the Chainlink **node services** (`node`, `node-2`) built from `core/chainlink.Dockerfile`, together with the Docker **secrets** they mount (config, node password, API credentials, ETH keystore). |
| `chainlink/tools/docker/docker-compose.postgres.yaml` | **Overlay** that adds one PostgreSQL 15 database per node (`node-db`, `node-db-2`) and injects `CL_DATABASE_URL` into each node so the stack uses persistent Postgres storage instead of an unset database URL. |

These two files are *always loaded together* by the `chainlink/tools/docker/compose` helper script (`base_files="-f docker-compose.yaml -f docker-compose.postgres.yaml"`), which additionally layers the devnet/observability/dev overlays selected by environment variables. The resulting stack gives developers a fully functional multi-node Chainlink deployment — Operator UI, job pipeline, and on-chain connectivity — with a single command.

**What runs inside the containers** is the Chainlink node application itself; for the application lifecycle, configuration surface, and relay wiring that the containers execute, see [Node Application Core & Interfaces](../../Node_Application_Core___Interfaces.md).

## 2. Scope and boundaries

This module documents **only the node deployment files** (`docker-compose.yaml`, `docker-compose.postgres.yaml`). Sibling modules in the same folder cover the rest of the local environment:

- [Devnet simulators](docker-dev-environments_devnet-simulators.md) — `docker-compose.gethnet*.yaml`, `docker-compose.paritynet*.yaml`, and the `tools/gethnet` Dockerfiles that provide a local prefunded EVM chain.
- [Dev workflow overlay](docker-dev-environments_dev-workflow-overlay.md) — `docker-compose.dev.yaml` with the `develop.watch` rebuild-on-source-change loop.
- [Observability stack](docker-dev-environments_observability-stack.md) — `docker-compose.observability.yaml` with Prometheus, Grafana and Alertmanager.

Nearby modules that frequently operate on this stack: [devenv](../devenv.md) (programmatic Go environment for tests), [deployment-environment](../deployment-environment.md) (CRIB/deployment test environments), and [Build, CI & Release Infrastructure](../../Build,_CI___Release_Infrastructure.md) (the `make docker` image build target).

## 3. Key source files

| Path | Contents |
| --- | --- |
| `chainlink/tools/docker/docker-compose.yaml` | Services `node` + `node-2`; secrets `node_password`, `apicredentials`, `keystore`, `config`. |
| `chainlink/tools/docker/docker-compose.postgres.yaml` | Services `node-db` + `node-db-2` (postgres:15), named volumes, `CL_DATABASE_URL` wiring. |
| `chainlink/tools/docker/compose` | Shell wrapper that always combines the two files above, renders `config.toml`, and exposes `up`/`dev`/`clean`/`logs`/`connect`/`eth:restart`/`db:restart` commands. |
| `chainlink/tools/docker/config.toml.tmpl` | TOML template rendered into `config.toml` (mounted as the `config` secret). |
| `chainlink/tools/docker/README.md` | User-facing usage guide for the stack. |
| `chainlink/core/chainlink.Dockerfile` | Multi-stage build producing the `smartcontract/chainlink` image run by both node services. |
| `chainlink/GNUmakefile` | `docker` / `docker-ccip` / `docker-plugins` targets that build the same image outside Compose. |
| `chainlink/tools/clroot/password.txt`, `chainlink/tools/clroot/apicredentials` | Secret material: keystore password and Operator UI / API credentials. |
| `chainlink/tools/secrets/0xb90c7E3F7815F59EAD74e7543eB6D9E8538455D6.json` | Pre-funded ETH account keystore imported at node startup. |

## 4. Architecture

### 4.1 Deployment topology

The diagram below shows the runtime layout produced by the two compose files: two node containers, each backed by its own Postgres database, sharing Docker secrets and connected through the default Compose network.

```mermaid
flowchart LR
    subgraph host["Developer host"]
        UI["Operator UI<br/>http://localhost:6688"]
        UI2["Operator UI node-2<br/>http://localhost:6699"]
        ENV[".env<br/>CHAINLINK_PGUSER / CHAINLINK_PGPASSWORD / CHAINLINK_DB_NAME"]
    end

    subgraph net["Docker Compose network"]
        N1["service: node<br/>container: chainlink-node<br/>image: smartcontract/chainlink"]
        N2["service: node-2<br/>container: chainlink-node-2<br/>image: smartcontract/chainlink"]
        DB1["service: node-db<br/>container: chainlink-db<br/>postgres:15"]
        DB2["service: node-db-2<br/>container: chainlink-db-2<br/>postgres:15"]
    end

    subgraph sec["Docker secrets (bind-mounted files)"]
        SP["node_password<br/>../clroot/password.txt"]
        SA["apicredentials<br/>../clroot/apicredentials"]
        SK["keystore<br/>../secrets/0xb90c...5D6.json"]
        SC["config<br/>config.toml (rendered)"]
    end

    subgraph vol["Named volumes"]
        V1[("node-db-data")]
        V2[("node-db-2-data")]
    end

    UI -->|"host 6688 to container 6688"| N1
    UI2 -->|"host 6699 to container 6688"| N2
    ENV -.->|"env_file"| N1
    ENV -.->|"env_file"| N2
    N1 -->|"CL_DATABASE_URL @node-db:5432"| DB1
    N2 -->|"CL_DATABASE_URL @node-db-2:5432"| DB2
    SP -.->|"/run/secrets/node_password"| N1
    SA -.->|"/run/secrets/apicredentials"| N1
    SK -.->|"/run/secrets/keystore"| N1
    SC -.->|"/run/secrets/config"| N1
    SP -.-> N2
    SA -.-> N2
    SK -.-> N2
    SC -.-> N2
    DB1 --- V1
    DB2 --- V2
```

Key topology properties:

- **Two independent node instances.** `node` and `node-2` are identical services; only the host port mapping differs (`6688:6688` vs `6699:6688`). This enables two-node scenarios (e.g. OCR/P2P pairs) without duplicating configuration.
- **One database per node.** The Postgres overlay guarantees node data isolation; the databases are *not* exposed on host ports and are reachable only inside the Compose network via the service DNS names `node-db` / `node-db-2` on port `5432`.
- **Secrets, not env vars, for credentials.** Node passwords, API credentials, the ETH keystore, and the TOML config are mounted as Docker secrets under `/run/secrets/*`, avoiding secrets in process lists or image layers.
- **Persistence.** Database data survives container restarts via the `node-db-data` / `node-db-2-data` named volumes; they are only removed by `./compose clean` or `db:restart`.

### 4.2 Compose layering and the `compose` script

The two files in this module are the **base layers** of the stack. `chainlink/tools/docker/compose` composes them with the optional overlays:

```mermaid
flowchart TD
    subgraph files["Compose files (merged with -f)"]
        BASE["docker-compose.yaml<br/>node, node-2, secrets"]
        PG["docker-compose.postgres.yaml<br/>node-db, node-db-2, CL_DATABASE_URL"]
        NET["docker-compose.gethnet.yaml<br/>or docker-compose.paritynet.yaml<br/>devnet service"]
        OBS["docker-compose.observability.yaml<br/>prometheus, grafana, alertmanager"]
        DEV["docker-compose.dev.yaml<br/>develop.watch rebuild loop"]
    end

    subgraph script["chainlink/tools/docker/compose"]
        UP["compose up<br/>foreground, full stack"]
        DEVUP["compose dev<br/>single node, watch mode"]
    end

    BASE --> UP
    PG --> UP
    NET -->|"always added unless<br/>HTTPURL/WSURL are set"| UP
    OBS -.->|"WITH_OBSERVABILITY=true"| UP
    BASE --> DEVUP
    PG --> DEVUP
    NET --> DEVUP
    DEV --> DEVUP
```

Behavior of the script relevant to this module:

1. **Always** passes `-f docker-compose.yaml -f docker-compose.postgres.yaml` — a bare invocation of either file alone is not the supported path (without the Postgres overlay the nodes have no `CL_DATABASE_URL`).
2. If neither `HTTPURL` nor `WSURL` is set, it appends a devnet file (geth by default when `GETH_MODE=true`, otherwise parity) so the nodes have an EVM endpoint. See [Devnet simulators](docker-dev-environments_devnet-simulators.md).
3. `configure()` renders `config.toml` from `config.toml.tmpl`, substituting `CHAIN_ID` (default `34055` parity / `1337` geth), `WSURL` (`ws://devnet:8546`) and `HTTPURL` (`http://devnet:8545`). The rendered file is the `config` secret consumed by both nodes.
4. `dev` mode starts **only the `node` service** (plus Grafana if enabled) in the background and attaches `docker compose watch` so source changes trigger image rebuilds (see [Dev workflow overlay](docker-dev-environments_dev-workflow-overlay.md)); `up` runs the **full stack** (both nodes, both databases) in the foreground.

## 5. Component reference

### 5.1 `docker-compose.yaml` — node services and secrets

**Service `node`** (`chainlink/tools/docker/docker-compose.yaml`)

| Property | Value | Notes |
| --- | --- | --- |
| `container_name` | `chainlink-node` | Also used by `./compose connect` (`docker exec -it chainlink-node bash`). |
| `image` / `build` | `smartcontract/chainlink`, built from context `../../` (the `chainlink/` repo root) with `core/chainlink.Dockerfile` | Build arg `CL_AUTO_DOCKER_TAG: latest` is baked into the image as the `CL_DOCKER_TAG` env var. |
| `entrypoint` | `/bin/sh -c "chainlink -c /run/secrets/config node start -d -p /run/secrets/node_password -a /run/secrets/apicredentials"` | Overrides the image defaults (`ENTRYPOINT ["chainlink"]`, `CMD ["local","node"]`). |
| `restart` | `always` | Nodes survive daemon restarts. |
| `env_file` | `.env` | Injects variables from `chainlink/tools/docker/.env` (not committed) into the container. |
| `ports` | `6688:6688` | Operator UI + REST API. |
| `secrets` | `node_password`, `apicredentials`, `keystore`, `config` | See below. |

**Service `node-2`** — identical, except `container_name: chainlink-node-2` and port mapping `6699:6688`.

**Entrypoint flags explained**

| Flag | Secret | Purpose |
| --- | --- | --- |
| `-c /run/secrets/config` | `config` | TOML configuration file (rendered from `config.toml.tmpl`); parsed by the node's core config layer (see [node application config](../../Node_Application_Core___Interfaces/node_application/node_application_config.md)). |
| `-d` | — | Dev mode: relaxes security defaults. The template sets `SecureCookies = false` and `HTTPSPort = 0` accordingly. |
| `-p /run/secrets/node_password` | `node_password` | Password file used to unlock the imported keystore. |
| `-a /run/secrets/apicredentials` | `apicredentials` | `email@domain.com / password` credentials for the Operator UI and REST/CLI authentication. |

**Secrets section** (`secrets:` top-level key):

| Secret | Source file | Purpose |
| --- | --- | --- |
| `node_password` | `../clroot/password.txt` → `chainlink/tools/clroot/password.txt` | Keystore unlock password. |
| `apicredentials` | `../clroot/apicredentials` → `chainlink/tools/clroot/apicredentials` | Operator UI / API login. |
| `keystore` | `../secrets/0xb90c7E3F7815F59EAD74e7543eB6D9E8538455D6.json` | Pre-funded Ethereum account. As noted in the file's comment, *"the keystore import allows us to submit transactions immediately because addresses are specified when starting the parity/geth node to be prefunded with eth"*. |
| `config` | `config.toml` (generated, not committed) | Node TOML config; must be rendered by the `compose` script's `configure()` before `docker compose up` will work standalone. |

### 5.2 `docker-compose.postgres.yaml` — database overlay

This file *extends* the services from the base file and adds two database services:

| Service | Image | Container name | Consumed by |
| --- | --- | --- | --- |
| `node-db` | `postgres:15` | `chainlink-db` | `node` |
| `node-db-2` | `postgres:15` | `chainlink-db-2` | `node-2` |

Merge semantics applied to `node` / `node-2`:

```yaml
depends_on:
  - node-db                # (node-db-2 for node-2)
environment:
  - CL_DATABASE_URL=postgresql://$CHAINLINK_PGUSER:$CHAINLINK_PGPASSWORD@node-db:5432/$CHAINLINK_DB_NAME?sslmode=disable
```

- `depends_on` orders container startup (node waits for its DB container to start; note Compose `depends_on` here does *not* wait for Postgres readiness — the node retries its DB connection during boot).
- `CL_DATABASE_URL` is the canonical DSN consumed by the node's persistence layer (migrations, job ORM, pipeline runs). For how the node uses this URL internally, see [Database persistence](../../Node_Platform_Services/database_persistence.md) and the [node application lifecycle](../../Node_Application_Core___Interfaces/node_application/node_application_lifecycle.md).
- `sslmode=disable` is acceptable only because traffic never leaves the Compose network.
- The database containers take `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` from the same `CHAINLINK_PGUSER` / `CHAINLINK_PGPASSWORD` / `CHAINLINK_DB_NAME` variables, resolved by Compose **variable interpolation from the project `.env` file**. Both nodes may share one `CHAINLINK_DB_NAME` because they connect to separate database *servers*.
- Data lives in named volumes `node-db-data` and `node-db-2-data` (mounted at `/var/lib/postgresql/data`).

## 6. Node image build (`core/chainlink.Dockerfile`)

Both node services build the same image from the repository root (`context: ../../`). The Dockerfile is a heavily cached multi-stage build whose stages mirror the GNUmakefile targets in [Build, CI & Release Infrastructure](../../Build,_CI___Release_Infrastructure.md):

```mermaid
flowchart TD
    CTX["Build context: chainlink/ repo root<br/>(compose build context ../../)"]
    ARGS["Build args from compose<br/>CL_AUTO_DOCKER_TAG=latest"]

    subgraph df["core/chainlink.Dockerfile stages"]
        D1["deps-base<br/>go.mod/go.sum + go mod download<br/>(optional GIT_AUTH_TOKEN secret for private modules)"]
        D2["deps<br/>full source tree copy"]
        D3["build-remote-plugins<br/>loopinstall: make install-plugins-public<br/>/ -private / -testing"]
        D4["build-local-plugins<br/>make install-plugins-local"]
        D5["build-chainlink<br/>make install-chainlink<br/>(or install-chainlink-dev)"]
        D6["final: ubuntu:24.04<br/>EXPOSE 6688<br/>HEALTHCHECK curl /health<br/>ENTRYPOINT chainlink, CMD local node"]
        D7["debug = final + delve"]
    end

    CTX --> D1
    D1 --> D2
    D1 --> D3
    D2 --> D4
    D2 --> D5
    D3 --> D6
    D4 --> D6
    D5 --> D6
    ARGS --> D6
    D6 --> D7
```

Points relevant to this module:

- **Build args passed by Compose:** only `CL_AUTO_DOCKER_TAG: latest`. Other args (`CL_GOPRIVATE`, `CL_INSTALL_PRIVATE_PLUGINS`, `CL_INSTALL_TESTING_PLUGINS`, `CL_IS_PROD_BUILD`, `COMMIT_SHA`, `VERSION_TAG`, `CHAINLINK_USER`, `APT_CACHE_BUST`) fall back to Dockerfile defaults. Note that Compose passes no `GIT_AUTH_TOKEN` secret, so builds here resolve **public** modules/plugins only; private-plugin images are produced by `make docker` in `chainlink/GNUmakefile` (tag `chainlink:develop`, requires `GITHUB_TOKEN` when private/testing plugins are enabled).
- **Image contents:** the `chainlink` binary plus local and remote LOOPP plugin binaries installed into `/usr/local/bin` (the plugin/loop runtime is described in [Plugin Process Framework (Loop)](../../Plugin_Process_Framework_(Loop).md)), `postgresql-client-18` for DB backups (using the vendored keyring `chainlink/tools/docker/postgresql-archive-keyring.asc`), and a configurable non-root user (`CHAINLINK_USER`, default `root` in dev).
- **Runtime contract of the image** (overridden by the Compose `entrypoint`): `EXPOSE 6688`, `HEALTHCHECK CMD curl -f http://localhost:6688/health`, `ENTRYPOINT ["chainlink"]`, `CMD ["local", "node"]`. A `debug` target stage adds `dlv` for delve-based debugging.

## 7. Startup and runtime flow

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant CS as tools/docker/compose
    participant DC as Docker Compose
    participant N as chainlink-node container
    participant DB as node-db (postgres:15)

    Dev->>CS: ./compose up (or ./compose dev)
    CS->>CS: configure() renders config.toml from config.toml.tmpl<br/>(CHAIN_ID, WSURL, HTTPURL substitution)
    CS->>DC: docker compose -f docker-compose.yaml<br/>-f docker-compose.postgres.yaml [-f devnet ...] up
    DC->>DB: start postgres containers<br/>(POSTGRES_USER/DB/PASSWORD from .env)
    DC->>N: start node containers (depends_on node-db)
    N->>N: chainlink -c /run/secrets/config node start -d<br/>-p /run/secrets/node_password -a /run/secrets/apicredentials
    N->>DB: connect via CL_DATABASE_URL (node-db:5432, sslmode=disable)<br/>run schema migrations
    N->>N: import + unlock pre-funded keystore (/run/secrets/keystore)
    N->>N: load EVM chain config from config.toml<br/>(ChainID, primary-0 WSURL/HTTPURL)
    N-->>Dev: Operator UI ready at localhost:6688 / localhost:6699
    Dev->>CS: ./compose connect (docker exec -it chainlink-node bash)
```

Runtime interactions beyond startup:

- **EVM connectivity:** the `[[EVM]]` / `[[EVM.Nodes]]` stanza in `config.toml` points at the devnet service (`ws://devnet:8546` / `http://devnet:8545`) or at external endpoints supplied via `HTTPURL`/`WSURL`. The relay adapter that consumes this configuration is covered in [node application relay](../../Node_Application_Core___Interfaces/node_application/node_application_relay.md).
- **Telemetry/observability:** when `WITH_OBSERVABILITY=true`, Prometheus scrapes the nodes and Grafana provides dashboards — see [Observability stack](docker-dev-environments_observability-stack.md); the node-side config knobs are described in [core config observability](../../Node_Application_Core___Interfaces/core_config/core_config_observability.md).
- **Job execution:** jobs submitted through the UI/CLI are persisted in the per-node Postgres database and executed by the pipeline engine ([Pipeline](../../Oracle_Engines___Data_Pipelines/pipeline.md)), using the same `CL_DATABASE_URL`.

## 8. Configuration reference

| Variable / setting | Defined in | Consumed by | Purpose |
| --- | --- | --- | --- |
| `CHAINLINK_PGUSER`, `CHAINLINK_PGPASSWORD`, `CHAINLINK_DB_NAME` | `chainlink/tools/docker/.env` (create locally; loaded automatically for interpolation and via `env_file`) | Postgres services (`POSTGRES_*`) and node services (`CL_DATABASE_URL`) | Database credentials and DB name shared by the overlay. |
| `CL_DATABASE_URL` | `docker-compose.postgres.yaml` | Node process | Postgres DSN; drives the node's persistence layer. |
| `CL_AUTO_DOCKER_TAG` | `docker-compose.yaml` build args | Image build → `CL_DOCKER_TAG` env in the running node | Image provenance metadata. |
| `CHAIN_ID`, `HTTPURL`, `WSURL` (compose script) | Exported before `./compose ...` | `configure()` → `config.toml.tmpl` | Target EVM chain and RPC endpoints; setting both URLs skips the local devnet entirely. |
| `GETH_MODE` | Exported | `compose` script | Selects geth vs parity devnet file. |
| `WITH_OBSERVABILITY` | Exported | `compose` script | Adds the observability overlay. |
| `[Log]`, `[WebServer]`, `[JobPipeline.HTTPRequest]`, `[[EVM]]` | `config.toml.tmpl` | Node TOML config | Dev-tuned defaults: info logging, insecure cookies, no TLS, 5s job HTTP timeout, 1-confirmation incoming, `0.000001 link` min payment, one primary EVM node. |

## 9. Operations cheat sheet

All commands are run from `chainlink/tools/docker/` (see `chainlink/tools/docker/README.md`):

| Command | Effect on this module's services |
| --- | --- |
| `./compose up` | Full stack in foreground: `node`, `node-2`, `node-db`, `node-db-2` (+ devnet, + observability). Renders `config.toml` first. |
| `./compose dev` | Builds the image, starts **only `node`** (+ `node-db`, + devnet, + optional grafana) detached, then attaches `docker compose watch` for rebuild-on-change. |
| `./compose logs [service]` | Follows combined or per-service logs (`node`, `node-db`, …). |
| `./compose connect` | Shell into `chainlink-node`. |
| `./compose db:restart` | Stops `node`, deletes `node-db` container **and** the `node-db-data` volume, then restarts node + devnet — a full node-data reset. |
| `./compose eth:restart` | Resets the devnet to genesis (removes devnet container + chain volume). Does not touch node databases. |
| `./compose clean` | `docker compose down -v --remove-orphans` for both the base and dev file sets, and deletes the generated `config.toml`. |

Troubleshooting notes from the README: reclaim disk with `docker system prune`; limit parallel builds with `export DOCKER_COMPOSE_BUILD_OPTS=""`; if Compose swallows logs, use `docker logs -f chainlink-node` directly.

**Operational caveats:**

- `config.toml` is *generated*: invoking `docker compose` directly (without the `compose` script) on a fresh checkout fails on the `config` secret until `configure()`-equivalent rendering is done (`sed` substitutions in `config.toml.tmpl`).
- The Compose build uses no Git auth secret, so builds requiring private Go modules or private/testing plugins will fail here — use `make docker` (GNUmakefile) for those variants.
- Both nodes import the **same** pre-funded keystore and API credentials, and by default point at the **same** devnet; for two-node P2P/OCR scenarios configure distinct P2P settings per node via their config (the `-c` secret is shared — adjust the template or mount per-node configs if you need divergence).

## 10. Related documentation

- Parent overview: [docker-dev-environments](../docker-dev-environments.md)
- Sibling modules: [Devnet simulators](docker-dev-environments_devnet-simulators.md) · [Dev workflow overlay](docker-dev-environments_dev-workflow-overlay.md) · [Observability stack](docker-dev-environments_observability-stack.md)
- What runs inside the containers: [Node Application Core & Interfaces](../../Node_Application_Core___Interfaces.md) — in particular [application lifecycle](../../Node_Application_Core___Interfaces/node_application/node_application_lifecycle.md) and [node application config](../../Node_Application_Core___Interfaces/node_application/node_application_config.md)
- Persistence consumed via `CL_DATABASE_URL`: [Database persistence](../../Node_Platform_Services/database_persistence.md)
- Image build tooling: [Build, CI & Release Infrastructure](../../Build,_CI___Release_Infrastructure.md) (`make docker`, `install-chainlink*` targets)
- Larger-scale alternatives to this stack: [devenv](../devenv.md), [deployment-environment](../deployment-environment.md), [integration-tests](../integration-tests.md), [system-tests](../system-tests.md)
