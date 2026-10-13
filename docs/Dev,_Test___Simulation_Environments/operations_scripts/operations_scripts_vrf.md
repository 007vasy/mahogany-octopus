# Operations Scripts — VRF Node Cluster (`chainlink/core/scripts/common/vrf`)

> Part of the [operations scripts](../operations_scripts.md) family within
> [Dev, Test & Simulation Environments](../../Dev,_Test___Simulation_Environments.md).

## 1. Introduction

`operations_scripts_vrf` documents the **VRF operations tooling** that lives under
`chainlink/core/scripts/common/vrf/` in the standalone scripts Go module
(`github.com/smartcontractkit/chainlink/core/scripts`, declared in `chainlink/core/scripts/go.mod`,
Go 1.27.1 — see the [parent module page](../operations_scripts.md) for module identity and
`replace` directives).

The module provides everything an operator needs to stand up a **complete, self-hosted VRF V2 Plus
serving stack** for a testnet/devnet:

1. **A dockerized five-node Chainlink cluster** (`docker/docker-compose.yml`) with role-specialized
   nodes — a VRF primary, a VRF backup sharing the same proving key, two Blockhash Store (BHS)
   nodes, and a Blockheader Feeder (BHF) node — plus a shared PostgreSQL instance that provisions
   one database per node.
2. **A Go data model** (`model/model.go`) that types the cluster — node roles, sending keys, VRF
   keys, contract addresses, and job-spec configuration — and acts as the contract between the
   Docker topology and the bootstrap logic.

Around these two cores sit tightly-coupled companions in the same directory tree that make the
module end-to-end usable (documented here because they are inseparable from the core components):

- `setup-envs/main.go` + `setup-envs/README.md` — the interactive bootstrap CLI that creates keys,
  funds nodes, deploys the VRF contract universe and (re)creates jobs on every node.
- `jobs/jobs.go` — Go `fmt` templates for the three job types (`vrf`, `blockhashstore`,
  `blockheaderfeeder`).
- `constants/constants.go`, `util/util.go` — default values and `SendingKey` mapping helpers.
- `docker/` support files — layered TOML configs, Docker secrets, a multi-database init script and
  wait-for scripts.

The resulting cluster is the imperative, hands-on counterpart to the SDK-driven environments in
[devenv](../devenv.md) (whose [VRFv2Plus job templates](../devenv/devenv_products.md) mirror the
job specs generated here) and to the declarative node models in
[deployment-environment](../deployment-environment.md).

## 2. Module Inventory

| File | Role | Status |
|---|---|---|
| `chainlink/core/scripts/common/vrf/docker/docker-compose.yml` | **Core**: five Chainlink node services + `postgres:15`, with layered config mounts, Docker secrets and per-node databases | Documented core |
| `chainlink/core/scripts/common/vrf/model/model.go` | **Core**: `Node`, `SendingKey`, `JobSpecs`, `ContractAddresses`, `VRFKeyRegistrationConfig`, `CoordinatorJobSpecConfig`, `BHSJobSpecConfig` types + node-name constants | Documented core |
| `docker/sample.env` | Compose variables: `NODE_IMAGE_VERSION`, `CHAINLINK_DB_NAME`, `CHAINLINK_PGPASSWORD` | Supporting |
| `docker/secrets/{password.txt,apicredentials}` | Docker secrets injected at `/run/secrets/` (keystore password, API credentials) | Supporting |
| `docker/db/create-multiple-databases.sh` | Postgres entrypoint init: creates `chainlink_0_test` … `chainlink_4_test` from `POSTGRES_MULTIPLE_DATABASES` | Supporting |
| `docker/wait-for-others/*.sh` | Startup gating: block until `database:5432` is reachable, then `exec` the node command | Supporting |
| `docker/toml-config/*.toml` | Layered node configuration (see [Section 5](#5-configuration-layering)) | Supporting |
| `setup-envs/main.go` | Bootstrap orchestrator CLI (destructive: deletes all existing jobs) | Companion |
| `setup-envs/README.md` | Operator runbook with worked `go run .` examples | Companion |
| `jobs/jobs.go` | `VRFV2PlusJobFormatted`, `BHSPlusJobFormatted`, `BHFPlusJobFormatted` TOML templates | Companion |
| `constants/constants.go` | Defaults: subscription balances, `MinConfs=3`, funding `1e17`, fee/premium constants | Companion |
| `util/util.go` | `MapToSendingKeyArr` / `MapToAddressArr` conversions | Companion |

> **Note:** the same directory also contains `docker/toml-config/vrf-backup-other-chains.toml` and
> `secrets.toml`, which are *mounted* into `/opt/config` but not passed via any `-config` flag in
> the compose file — they are available for manual extension of the stack.

## 3. Architecture

### 3.1 Deployment topology (`docker-compose.yml`)

```mermaid
flowchart TB
    subgraph HOST["Docker Compose project (chainlink/core/scripts/common/vrf/docker)"]
        subgraph SEC["Docker secrets"]
            PW["node_password<br/>← secrets/password.txt"]
            APICRED["apicredentials<br/>← secrets/apicredentials"]
        end
        subgraph CFG["Read-only volume mounts"]
            WAIT["wait-for-others/<br/>docker-wait-for-others.sh<br/>+ docker-wait-for-it.sh"]
            TOML["toml-config/ → /opt/config"]
        end

        subgraph NODES["Chainlink node services (image: $NODE_IMAGE_VERSION)"]
            N0["chainlink-node-0<br/>container: vrf-primary-node"]
            N1["chainlink-node-1<br/>container: vrf-backup-node"]
            N2["chainlink-node-2<br/>container: bhs-node"]
            N3["chainlink-node-3<br/>container: bhs-backup-node"]
            N4["chainlink-node-4<br/>container: bhf-node"]
        end

        PG[("database<br/>postgres:15<br/>:5432")]
        INIT["docker-entrypoint-initdb.d/<br/>create-multiple-databases.sh"]
    end

    RPC["EVM JSON-RPC endpoints<br/>(edited into rpc-nodes.toml)"]
    OPS["setup-envs CLI<br/>(node API on :6610–:6614)"]

    N0 & N1 & N2 & N3 & N4 -->|"entrypoint waits<br/>for database:5432"| WAIT
    N0 & N1 & N2 & N3 & N4 -->|"CL_DATABASE_URL"| PG
    PG -.->|"init"| INIT
    N0 & N1 & N2 & N3 & N4 --> RPC
    OPS -->|"REST/CLI over<br/>host ports"| NODES
    SEC --> NODES
    CFG --> NODES
```

Key structural properties of the compose file:

- **One shared database, five logical databases.** Every node gets its own
  `CL_DATABASE_URL=postgresql://postgres:$CHAINLINK_PGPASSWORD@database:5432/chainlink_<N>_test?sslmode=disable`;
  the databases are created at first start by the mounted init script via
  `POSTGRES_MULTIPLE_DATABASES=chainlink_0_test,…,chainlink_4_test` (with
  `POSTGRES_PASSWORD: chainlink`).
- **Ordered startup.** Each node's entrypoint is
  `/opt/docker-wait-for-others.sh database:5432 --` (backed by the classic `docker-wait-for-it.sh`),
  so nodes only start the `chainlink` process once Postgres accepts connections. All services also
  declare `depends_on: database`.
- **Secrets, not env files.** Keystore password and API credentials are injected through
  `secrets:` (`node_password`, `apicredentials`) and consumed as `-p /run/secrets/node_password`
  and `-a /run/secrets/apicredentials`.
- **Immutable config.** `./toml-config` is bind-mounted read-only at `/opt/config`; nodes are
  launched with several `-config` flags that layer the files (see Section 5).
- **Fixed platform.** Every Chainlink service pins `platform: "linux/x86_64"`.

### 3.2 Node roles, config layers and port map

| Service | Container name | Role | `-config` layers | Host API port → 6688 | Host debug port → 6060 | Database |
|---|---|---|---|---|---|---|
| `chainlink-node-0` | `vrf-primary-node` | VRF V2 Plus primary fulfiller | `base.toml` + `rpc-nodes.toml` + `vrf-primary.toml` | `6610` | `6059` | `chainlink_0_test` |
| `chainlink-node-1` | `vrf-backup-node` | VRF V2 Plus backup (same proving key) | `base.toml` + `rpc-nodes.toml` + `vrf-primary.toml` + `vrf-backup.toml` | `6611` | `6060` | `chainlink_1_test` |
| `chainlink-node-2` | `bhs-node` | Blockhash Store | `base.toml` + `rpc-nodes.toml` + `bhs.toml` | `6612` | `6062` | `chainlink_2_test` |
| `chainlink-node-3` | `bhs-backup-node` | Blockhash Store backup | `base.toml` + `rpc-nodes.toml` + `bhs.toml` | `6613` | `6063` | `chainlink_3_test` |
| `chainlink-node-4` | `bhf-node` | Blockheader Feeder | `base.toml` + `rpc-nodes.toml` + `bhf.toml` | `6614` | `6064` | `chainlink_4_test` |
| `database` | — | Postgres 15 shared instance | — | `5432` | — | — |

Two notable details from the compose file:

- The **backup node is the only one that layers four configs**: it inherits the primary's
  `vrf-primary.toml` and adds `vrf-backup.toml`, letting it run both job variants with a deeper
  confirmation threshold.
- The primary's `command` spells the CLI as `chainlink -config … node start` while the other four
  use `chainlink node -config … start`; both are accepted global-flag orderings of the same node
  entry point and behave identically.

### 3.3 Go data model (`model/model.go`)

The model package is the shared vocabulary of the tooling. Its node-name constants
(`VRFPrimaryNodeName = "vrf-primary-node"`, …) are deliberately **identical to the compose
`container_name` values**, which is what allows `setup-envs` to key its `map[string]model.Node` by
role and to address each node by the same identifier used by Docker.

```mermaid
classDiagram
    class Node {
        +URL string
        +CredsFile string
        +SendingKeys []SendingKey
        +NumberOfSendingKeysToCreate int
        +SendingKeyFundingAmount *big.Int
        +VrfKeys []string
    }
    class SendingKey {
        +Address string
        +BalanceEth *big.Int
    }
    class JobSpecs {
        +VRFPrimaryNode string
        +VRFBackupyNode string
        +BHSNode string
        +BHSBackupNode string
        +BHFNode string
    }
    class ContractAddresses {
        +LinkAddress string
        +LinkEthAddress string
        +BhsContractAddress common.Address
        +BatchBHSAddress common.Address
        +CoordinatorAddress common.Address
        +BatchCoordinatorAddress common.Address
    }
    class VRFKeyRegistrationConfig {
        +VRFKeyUncompressedPubKey string
        +RegisterAgainstAddress string
    }
    class CoordinatorJobSpecConfig {
        +BatchFulfillmentEnabled bool
        +BatchFulfillmentGasMultiplier float64
        +EstimateGasMultiplier float64
        +PollPeriod string
        +RequestTimeout string
        +RevertsPipelineEnabled bool
    }
    class BHSJobSpecConfig {
        +RunTimeout string
        +WaitBlocks int
        +LookBackBlocks int
        +PollPeriod string
        +RequestTimeout string
    }

    Node *-- SendingKey : sending keys
    JobSpecs ..> Node : rendered per role
    ContractAddresses ..> JobSpecs : substituted into templates
    VRFKeyRegistrationConfig ..> JobSpecs : proving key → publicKey
    CoordinatorJobSpecConfig ..> JobSpecs : vrf job knobs
    BHSJobSpecConfig ..> JobSpecs : bhs job knobs
```

Semantic roles of the types:

| Type | Meaning in the workflow |
|---|---|
| `Node` | One role-addressed node handle: RPC URL, path to its API credentials file, the sending keys created/funded for it, and (for VRF roles) its VRF proving keys. |
| `SendingKey` | An EVM transactor key owned by a node, with its current native balance used for top-up math. |
| `JobSpecs` | Five fully rendered TOML job-spec strings, one per cluster role. (Field `VRFBackupyNode` carries a long-standing typo; it is referenced as-is by `setup-envs`.) |
| `ContractAddresses` | The deployed on-chain universe — LINK token, LINK/ETH feed, BHS, Batch BHS, Coordinator, Batch Coordinator. Zero-valued entries are deployed fresh; pre-populated entries are reused. |
| `VRFKeyRegistrationConfig` | Uncompressed proving key of the primary node plus the EOA against which it is registered on the Coordinator (enables `oracleWithdraw` of fulfillment earnings). |
| `CoordinatorJobSpecConfig` | VRF job knobs: batch fulfillment toggle and gas multiplier, gas-estimate multiplier, poll period, request timeout. `RevertsPipelineEnabled` is defined in the model but not populated by the current v2plus flow. |
| `BHSJobSpecConfig` | Blockhash Store job knobs: wait/lookback blocks, poll period, run timeout. |

## 4. Job-Spec Templates (`jobs/jobs.go`)

The three Go templates are the textual bridge between the model and the nodes' job engines:

| Template | Node type | Parameterized by |
|---|---|---|
| `VRFV2PlusJobFormatted` | `type = "vrf"` | Coordinator & Batch Coordinator addresses, `batchFulfillmentEnabled`, batch gas multiplier, proving `publicKey`, `minIncomingConfirmations` (3 for primary, **100 for backup**), chain ID, `fromAddresses` (node's sending keys), poll period, request timeout, and the pipeline `decode_log → generate_proof (vrfv2plus) → estimate_gas → simulate_fulfillment (ethcall)` with `simulationBlock` (`pending`/`latest`) |
| `BHSPlusJobFormatted` | `type = "blockhashstore"` | Coordinator v2/v2+ addresses, `waitBlocks`/`lookbackBlocks` (30/200 primary; 100/200 backup), BHS address, poll period, run timeout, chain ID, `fromAddresses` |
| `BHFPlusJobFormatted` | `type = "blockheaderfeeder"` | Coordinator v2+ address, fixed `waitBlocks = 256`, `lookbackBlocks = 1_000`, BHS & Batch BHS addresses, poll 10s, timeout 30s, batch sizes 50/10, chain ID, `fromAddresses` |

The deep-confirmation settings are the mechanism that turns the shared-key primary/backup pair into
an **active–passive redundancy scheme**: the backup only fulfills requests that are still
unfulfilled after 100 confirmations, i.e. when the primary has failed.

## 5. Configuration Layering (`docker/toml-config/`)

```mermaid
flowchart LR
    subgraph L1["Layer 1 — base.toml (all nodes)"]
        B["WebServer :6688, AllowOrigins '*'<br/>rate limits 2000/100, TLS off<br/>DB pool 20/40, MigrateOnStartup<br/>debug JSON logs, P2P.V2 :6690"]
    end
    subgraph L2["Layer 2 — rpc-nodes.toml (all nodes)"]
        R["EVM ChainID 11155111<br/>[[EVM.Nodes]] HTTPURL/WSURL<br/>(operator must edit placeholders)"]
    end
    subgraph L3["Layer 3 — role config"]
        VP["vrf-primary.toml<br/>LogPoller = false (Log Broadcaster)<br/>MinIncomingConfirmations = 3<br/>BlockBackfillDepth = 500<br/>gas: 3.5M limit, 30 gwei max"]
        VB["vrf-backup.toml<br/>MinIncomingConfirmations = 100"]
        BHS["bhs.toml<br/>LogPoller = true<br/>FinalityDepth = 10"]
        BHF["bhf.toml<br/>LogPoller = true<br/>FinalityDepth = 10"]
    end
    B --> EFF["Effective node config<br/>(later -config flags win)"]
    R --> EFF
    VP --> N0["node-0 primary"]
    VB --> N1["node-1 backup"]
    BHS --> N2["node-2 bhs"]
    BHS --> N3["node-3 bhs-backup"]
    BHF --> N4["node-4 bhf"]
```

Configuration input summary:

| Input | Where | Notes |
|---|---|---|
| `NODE_IMAGE_VERSION` | `sample.env` → compose | e.g. `public.ecr.aws/chainlink/chainlink:2.3.0` |
| `CHAINLINK_PGPASSWORD` | `sample.env` → `CL_DATABASE_URL` | Must match `POSTGRES_PASSWORD` (`chainlink`) |
| `rpc-nodes.toml` | manual edit before `docker compose up` | Placeholders `<RPC HTTP URL>` / `<RPC WS URL>` must be replaced with real endpoints |
| `ETH_URL`, `ETH_CHAIN_ID`, `ACCOUNT_KEY` | shell env for `setup-envs` | Bootstrap wallet used to fund nodes and deploy contracts (see [chain-common helpers](operations_scripts_chain_common.md)) |

## 6. Key Workflows

### 6.1 Stack bring-up (Docker) and bootstrap (`setup-envs`)

```mermaid
flowchart TD
    A["Operator: create .env from sample.env<br/>edit rpc-nodes.toml<br/>provide secrets/password.txt + apicredentials"] --> B["docker compose up<br/>(Postgres + 5 nodes, wait-for-db gating)"]
    B --> C["Run setup-envs with node URLs,<br/>creds files, key counts, funding,<br/>and job/contract flags"]
    C --> D{"Per node in nodesMap"}
    D --> E["Connect in-process Chainlink CLI Shell<br/>(remote-node-url, JSON renderer)"]
    E --> F["Create ETH sending keys if needed<br/>(num per role: VRF / BHS / BHF)"]
    F --> G{"Role?"}
    G -- "vrf-primary" --> H["Create VRF key, export it<br/>→ node.VrfKeys"]
    G -- "vrf-backup" --> I["List VRF keys<br/>(shared key imported later)"]
    G -- "bhs / bhs-backup / bhf" --> J["(sending keys only)"]
    H --> K["Top-up fund every sending key to<br/>--sending-key-funding-amount<br/>(helpers.FundNode)"]
    I --> K
    J --> K
    K --> L["ImportVRFKeyToNodeIfSet:<br/>ensure backup holds the primary's<br/>proving key"]
    L --> M{"--deploy-contracts-and-create-jobs?"}
    M -- "no" --> Z["Done — keys ready for infra-k8s<br/>(per-key PriceMax TOML snippets)"]
    M -- "yes" --> N["v2plusscripts.VRFV2PlusDeployUniverse<br/>(see 6.2)"]
    N --> O["Per node: DELETE ALL existing jobs<br/>(destructive!) then create the<br/>role-specific rendered job spec"]
    O --> P["Print contract addresses, sub ID,<br/>request/status commands"]
```

Two runbook patterns are called out in `setup-envs/README.md`: (1) keys-only bootstrap
(`--deploy-contracts-and-create-jobs=false`) whose key addresses are then copied into
infra-k8s deployment TOML with per-key `GasEstimator.PriceMax`, and (2) full bootstrap that also
deploys contracts and creates jobs.

### 6.2 Contract-universe deployment and job-spec rendering

`setup-envs` delegates the entire on-chain setup to
`v2plusscripts.VRFV2PlusDeployUniverse` (`chainlink/core/scripts/vrfv2plus/testnet/v2plusscripts/super_scripts.go`),
which consumes this module's `model` types and returns a filled `model.JobSpecs`:

```mermaid
flowchart LR
    subgraph INPUTS["Inputs from setup-envs"]
        ENV["helpers.Environment<br/>(ETH_URL / CHAIN_ID / ACCOUNT_KEY)"]
        NODES["nodesMap[string]model.Node"]
        ADDR["model.ContractAddresses<br/>(reuse-or-deploy)"]
        KEYREG["model.VRFKeyRegistrationConfig"]
        CJC["model.CoordinatorJobSpecConfig"]
        BJC["model.BHSJobSpecConfig"]
    end
    subgraph DEPLOY["Deploy / configure"]
        LINK["LINK token + LINK/ETH feed<br/>(skipped if addresses given or --native-only)"]
        STORES["BHS → Batch BHS"]
        COORD["Coordinator (layer1 / arbitrum / optimism)<br/>+ Batch Coordinator<br/>SetCoordinatorConfig (+ L1 fee mode)"]
        REG["Register proving key against EOA<br/>(keyHash printed)"]
        SUB["Deploy load-test consumer<br/>create + fund subscription<br/>(LINK juels / native wei)"]
    end
    subgraph OUTPUT["Render via jobs/*Formatted"]
        JS["model.JobSpecs:<br/>VRF primary · VRF backup · BHS ·<br/>BHS backup · BHF"]
    end
    INPUTS --> DEPLOY
    DEPLOY --> JS
    JS --> CREATE["setup-envs: delete-all + create<br/>per-node jobs via CLI Shell"]
```

Only the `v2plus` VRF version is supported by the current script (any other value panics), and
V2 Plus intentionally skips VRF-key-onchain registration prerequisites, the VRFV2Owner contract and
the test coordinator.

### 6.3 Runtime request flow across the cluster

The five-node topology exists to make the *serving path* redundant and the *blockhash
infrastructure* self-maintaining:

```mermaid
sequenceDiagram
    autonumber
    participant C as Consumer contract
    participant K as VRF Coordinator<br/>(+ Batch Coordinator)
    participant P as vrf-primary-node<br/>(vrf job, minConfs 3)
    participant B as vrf-backup-node<br/>(vrf job, minConfs 100)
    participant S as bhs-node / bhs-backup-node<br/>(blockhashstore jobs)
    participant F as bhf-node<br/>(blockheaderfeeder job)

    C->>K: requestRandomWords (subscription pays)
    K-->>P: RandomWordsRequested log
    K-->>B: RandomWordsRequested log
    P->>P: decode_log → generate_proof →<br/>estimate_gas → simulate_fulfillment
    P->>K: fulfillRandomWords (proof + tx)
    K-->>C: randomness delivered
    Note over B: waits 100 confirmations;<br/>fulfills only if primary never did
    S->>K: poll → store blockhashes<br/>(wait 30 / lookback 200; backup 100/200)
    F->>S: feed historical headers to BHS / Batch BHS<br/>(wait 256, lookback 1000, batches 50/10)
```

The BHS/BHF jobs exist because VRF V2 Plus proofs can require historical block hashes; the feeder
plus batch store keep that data available for fulfillments and subsequent verification (the
RLP-header/hash tooling used to verify this data lives in the sibling
[chain-common helpers](operations_scripts_chain_common.md) module).

## 7. Dependencies

**Within the scripts module** (`chainlink/core/scripts/go.mod`):

- `setup-envs` builds an in-process `clcmd.Shell` (the node's own CLI, rendered as JSON against a
  `remote-node-url`) — the same CLI surface documented in
  [Node Application Core & Interfaces → CLI commands](../../Node_Application_Core___Interfaces/cli_commands.md) —
  and reads key listings as `presenters.VRFKeyResource` (see
  [Web API presenters](../../Node_Application_Core___Interfaces/web_api.md)).
- On-chain work reuses the [chain-common helpers](operations_scripts_chain_common.md)
  (`SetupEnv`, `FundNode`, `DeployLinkToken`, `DeployLinkEthFeed`, `PanicErr`) plus
  `go-ethereum` (abi/bind, crypto, common) and `shopspring/decimal` for big-number flag parsing.
- Deployment primitives come from the in-repo `chainlink-deployments-framework` /
  `chainlink-evm` gethwrappers (Coordinator V2.5 bindings), per the module's `replace` directives
  (see [Deployment Framework](../../Deployment_Framework_Core___Product_Deployments.md)).

**Runtime inputs/outputs:** funded bootstrap wallet, reachable EVM RPC, node API credentials;
output is a funded, keyed, job-configured five-node cluster plus printed contract addresses,
subscription ID and ready-to-paste request commands (`core/scripts/vrfv2plus/testnet`
`eoa-load-test-request-with-metrics` / `eoa-load-test-read-metrics`).

## 8. Relationship to Other Modules

| Module | Relationship |
|---|---|
| [operations_scripts](../operations_scripts.md) | Parent module; owns the scripts `go.mod` and shared module identity |
| [operations_scripts_chain_common](operations_scripts_chain_common.md) | **Code dependency**: funding/deployment/env helpers and the header/RLP-hash utilities that underpin BHS/BHF verification |
| [operations_scripts_ccip](operations_scripts_ccip.md), [operations_scripts_cre_environment](operations_scripts_cre_environment.md) | Sibling ops tools in the same Go module (independent at runtime) |
| [VRF engine (OCR domain)](../../Oracle_Engines___Data_Pipelines/vrf.md) | **Product counterpart**: the cluster runs job types served by the `core/services/vrf` engine — `Config`/`FeeConfig`/`GethKeyStore` ([vrf_common](../../Oracle_Engines___Data_Pipelines/vrf/vrf_common.md)) and `SolidityProof` ([vrf_proof](../../Oracle_Engines___Data_Pipelines/vrf/vrf_proof.md)); job-spec pipeline steps (`vrfv2plus`, `ethabidecodelog`, `estimategaslimit`, `ethcall`) execute on the [pipeline engine](../../Oracle_Engines___Data_Pipelines/pipeline.md) |
| [devenv](../devenv.md) | SDK-based alternative; its [VRFv2Plus `JobSpec`/`TxPipelineSpec` templates](../devenv/devenv_products.md) generate the same job TOML for ephemeral environments, while this module targets long-lived dockerized clusters |
| [deployment-environment](../deployment-environment.md) | CRIB/node-client environments; its `nodeclient` models include `VRFJobSpec`, `VRFV2PlusJobSpec`, `VRFV2PlusTxPipelineSpec` — declarative analogues of the templates here |
| [docker-dev-environments](../docker-dev-environments.md) | Generic single-node/devnet compose stacks; this module is the role-specialized, product-specific variant |
| [integration-tests](../integration-tests.md) / [system-tests](../system-tests.md) | Automated E2E coverage for VRF flows; this module is for interactive operator use |

## 9. Operational Notes & Caveats

- **Destructive bootstrap** — `setup-envs` deletes *all* existing jobs on every node it touches
  and aborts if a node holds more than one VRF key. Never point it at a node with jobs you need.
- **Secrets hygiene** — the README recommends keeping credential files outside the repo; the
  compose `secrets/` directory is a local-only convenience.
- **RPC placeholders** — the stack is non-functional until `rpc-nodes.toml` placeholders are
  replaced; all nodes default to Sepolia (`ChainID 11155111`).
- **Top-up semantics** — funding is *to-balance*, not fixed-amount: each sending key receives
  `fundingAmount − currentBalance` wei (skipped if already at/above target).
- **Known quirks for maintainers**:
  - `model.JobSpecs.VRFBackupyNode` is misspelled ("Backupy") and is referenced as-is by
    `setup-envs`.
  - In `setup-envs`' `importVRFKeyToNodeIfSet`, the variable named `vrfPrimaryNode` is actually
    looked up from `nodes[model.VRFBackupNodeName]`, so the primary-vs-backup key comparison
    degenerates to comparing the backup node with itself; the import still triggers whenever the
    backup has no keys (the `len(VrfKeys) == 0` guard short-circuits), but the intended
    cross-node comparison does not happen.
  - `CoordinatorJobSpecConfig.RevertsPipelineEnabled` is defined in the model but not set by the
    current v2plus flag surface.
- **Build/test context** — the scripts module is built and linted through the repo's standard
  tooling (see [Build, CI & Release Infrastructure](../../Build,_CI___Release_Infrastructure.md));
  there is no dedicated Makefile for this sub-tree — run the CLI with `go run .` from
  `core/scripts/common/vrf/setup-envs`.
