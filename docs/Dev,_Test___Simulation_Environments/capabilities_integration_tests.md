# Capabilities Integration Tests (`capabilities_integration_tests`)

## Overview

The `capabilities_integration_tests` module (`github.com/smartcontractkit/capabilities/integration_tests`) is the **end-to-end integration test suite for the Chainlink Capability Runtime (CRE) capabilities** that live in the `capabilities/` workspace. Its own README states its purpose plainly:

> *"Contains integration tests to exercise and test capabilities in this repo."*
> — `capabilities/integration_tests/README.md`

Unlike unit tests, the tests in this module assemble a **miniature Decentralized Operator Network (DON)** from production components — capability plugins, workflow WASM binaries, gateway services and registry syncers — execute real workflows against a simulated EVM blockchain, and assert on the observable behaviour (emitted events, user logs, trigger ACKs) of the whole stack.

This page is part of the [Dev, Test & Simulation Environments](../Dev,_Test___Simulation_Environments.md) module group, alongside the [chainlink integration-tests suite](integration-tests.md), the [system-tests library](system-tests.md) and the [devenv](devenv.md) harness.

---

## Module Identity & Build Context

The module is defined by two core files:

| Component | Path | Role |
|---|---|---|
| `go.mod` | [`capabilities/integration_tests/go.mod`](#module-definition-gomod) | Go module definition and dependency wiring |
| Generated EVM contract binding | [`capabilities/integration_tests/evm/contract/MessageEmitter.go`](#evm-test-contract-binding-messageemittergo) | `abigen`-generated Go binding for the `MessageEmitter.sol` test contract |

### Nx project configuration

The module is registered in the `capabilities/` Nx monorepo workspace as an **`e2e` project** (`capabilities/integration_tests/project.json`) with three targets:

- **`test`** → `go test ./...`
- **`lint`** → `golangci-lint run ./...` (rules shared via `capabilities/.golangci.yml`)
- **`tidy`** → `go mod tidy`

The Nx workspace settings (`capabilities/nx.json`) wire these targets into the shared dependency graph, so the whole capability test surface can be driven with a single `nx run integration_tests:test` command (see [Running the Tests](#running-the-tests)). Workspace-wide Go module hygiene (tidying every `go.mod`, protoc/mockery tooling) is provided by the `capabilities/Makefile` — see [capabilities workspace tooling](../Build,_CI___Release_Infrastructure/capabilities_workspace_tooling.md).

### Repository layout

```
capabilities/integration_tests/
├── go.mod                     # Module definition (core component)
├── project.json               # Nx "e2e" project: test / lint / tidy
├── README.md                  # Usage + setup instructions
├── integrationtestsdiagram.png # Test-setup communication diagram
├── evm/                       # EVM log-trigger capability integration tests
│   ├── evm_logtrigger_test.go # Table-driven tests (Simple / MultiTopic / MultiAddress)
│   ├── logTriggerConfig.go    # RuntimeConfig (YAML) shared by tests + workflow
│   ├── contract/
│   │   ├── MessageEmitter.go  # abigen binding (core component)
│   │   └── MessageEmitter.abi # ABI file read at test runtime
│   └── workflow/
│       └── main_logtrigger_wasip1.go # Workflow source compiled to WASM
├── http/                      # HTTP capability integration tests
│   ├── http_test.go           # http_action in "gateway" proxy mode
│   ├── http_trigger_test.go
│   ├── http_action_routing_test.go
│   ├── gateway_config_test_helpers.go
│   └── kvstore.go
├── utils/                     # Shared test helpers
│   ├── deploy.go              # Build standard-capability binaries
│   ├── wasm.go                # Compile + brotli-compress workflow WASM
│   └── cron.go                # Cron trigger config helper
└── scripts/
    └── killAllZombieTestProcesses.sh # Cleanup for orphaned capability processes
```

---

## Architecture

### Component relationships

The tests do not contain their own DON implementation. They are orchestrated by the **test framework** shipped inside the `chainlink/v2` module (`github.com/smartcontractkit/chainlink/v2/core/capabilities/integration_tests/framework`), which provides `DonContext`, an Ethereum blockchain harness (`framework/ethereum.go`), fake OCR/dispatcher/billing/trigger components (`framework/fake_*.go`), and in-memory capabilities/workflow registries (`framework/capabilities_registry.go`, `framework/workflow_registry.go`).

```mermaid
flowchart TB
    subgraph IT["capabilities/integration_tests (this module)"]
        direction TB
        EVM["evm/ — Log-trigger tests<br/>(evm_logtrigger_test.go)"]
        HTTP["http/ — HTTP capability tests<br/>(http_test.go, routing, trigger)"]
        UTILS["utils/ — build &amp; WASM helpers"]
        BINDING["evm/contract — MessageEmitter<br/>abigen binding"]
        WF["evm/workflow — WASM workflow source<br/>(cre-sdk-go)"]
    end

    subgraph FRAMEWORK["chainlink/v2: core/capabilities/integration_tests/framework"]
        DON["DonContext / mini-DON harness"]
        ETH["Ethereum blockchain harness"]
        FAKES["Fake dispatcher / trigger /<br/>billing / libocr"]
        REGS["In-memory capabilities &amp;<br/>workflow registries"]
    end

    subgraph UNDER_TEST["Capabilities under test (capabilities/ workspace)"]
        EVMLT["EVM chain capability — LogTrigger<br/>(chain_capability_evm)"]
        HTTPACT["http_action / http_trigger<br/>capabilities"]
        CRON["cron capability"]
    end

    subgraph NODE["chainlink/v2 core services"]
        GW["Gateway services"]
        RS["Registry syncer v2"]
        BEHOLDER["Beholder telemetry / user logs"]
    end

    EVM --> UTILS
    EVM --> BINDING
    EVM --> WF
    HTTP --> UTILS

    EVM --> DON
    HTTP --> GW

    DON --> ETH
    DON --> FAKES
    DON --> REGS

    BINDING --> ETH
    WF --> REGS

    DON --> EVMLT
    DON --> CRON
    GW --> HTTPACT
    EVMLT --> RS
    EVMLT --> BEHOLDER
```

### Capability cross-references

The capabilities exercised by this suite are documented in the [Workflow & Capability Runtime (CRE Engine)](../Workflow___Capability_Runtime_(CRE_Engine).md) module:

- **EVM log trigger** — see [chain capability EVM](../Workflow___Capability_Runtime_(CRE_Engine)/chain_capability_evm.md) (`chain_capabilities/evm/trigger`): the `LogTriggerService` and its `LogTriggerStore` that subscribe to log-poller filters and deliver matched logs to workflows.
- **HTTP action / trigger** — see [http action capability](../Workflow___Capability_Runtime_(CRE_Engine)/http_action_capability.md) (gateway proxy mode, validators) and the http trigger capability page.
- **Cron trigger** — see [cron capability](../Workflow___Capability_Runtime_(CRE_Engine)/cron_capability.md) (`capabilities/cron/trigger`), exercised with the schedule config helper from `utils/cron.go`.

Shared types the tests rely on (capability contracts, service lifecycle helpers such as `servicetest.Runner`, tenant `settings/limits`, and `beholder` telemetry) come from the [Shared Foundation Libraries](../Shared_Foundation_Libraries___Domain_Types.md); the plugin-process model under which standard capabilities execute is described in the [Loop plugin framework](../Plugin_Process_Framework_(Loop).md).

### End-to-end data flow (EVM log-trigger test)

```mermaid
sequenceDiagram
    autonumber
    participant T as Test (evm_logtrigger_test.go)
    participant U as utils/
    participant C as contract binding (MessageEmitter)
    participant F as framework DonContext
    participant LT as EVM LogTrigger capability
    participant W as Workflow WASM (wasip1)
    participant B as Beholder user logs

    T->>U: CreateWasmBinary(workflow main file)
    U-->>T: WASM file (GOOS=wasip1, GOARCH=wasm)
    T->>C: DeployContract(txOpts, client)
    C-->>F: MessageEmitter instances on simulated chain
    T->>F: setupDon(wasm, 4 nodes, f=1, RuntimeConfig)
    F->>LT: Register EVM capability + log-poller filters
    F->>W: Register workflow (brotli+base64 WASM, RuntimeConfig YAML)
    T->>T: waitUntilLogPollerFiltersArePresent (zap observer)
    T->>C: EmitMultiTopic / EmitMessage (matching + non-matching)
    C-->>F: Transactions mined on simulated chain
    LT->>W: Matched log event (topic filters + confidence)
    W->>B: OnTrigger user log with decoded message
    T->>B: require.Eventually: quorum N-F nodes per matching message
    T->>T: Verify "Event ACK" per tx hash; assert NON MATCHING ignored
```

---

## Core Components

### Module definition (`go.mod`)

**Component:** `capabilities/integration_tests/go.mod::go.mod`

The module file defines both the test module's identity and, critically, **which code the tests actually run**:

- **Module path / Go version:** `github.com/smartcontractkit/capabilities/integration_tests`, `go 1.27.1`.
- **Workspace-local `replace` directives** pin the HTTP capabilities under test to sibling source directories, so tests always exercise the *local* implementation rather than a published version:
  ```
  replace github.com/smartcontractkit/capabilities/http_action  => ../http_action
  replace github.com/smartcontractkit/capabilities/http_trigger => ../http_trigger
  ```
  A third `replace` pins the Tron SDK (`fbsobreira/gotron-sdk`) to the `smartcontractkit/chainlink-tron` fork used across the ecosystem.
- **Capabilities under test (direct requires):**
  - `github.com/smartcontractkit/capabilities/chain_capabilities/evm` — the EVM chain capability whose `trigger` package is imported directly by the log-trigger tests.
  - `github.com/smartcontractkit/capabilities/http_action`, `.../http_trigger` — exercised via the local replaces above.
- **Runtime & framework dependencies:**
  - `github.com/smartcontractkit/chainlink/v2` — supplies the mini-DON test framework (`core/capabilities/integration_tests/framework`), gateway services (`core/services/gateway/*`), registry syncer v2, and the core logger.
  - `github.com/smartcontractkit/cre-sdk-go` (+ `.../capabilities/blockchain/evm`) — the Go SDK used to author the workflow that the tests compile to WASM.
  - `github.com/smartcontractkit/chainlink-evm/gethwrappers` — generated contract wrappers (e.g. capabilities registry v2).
  - `github.com/smartcontractkit/chainlink-protos/cre/go`, `.../workflows/go` — protobuf types for values, workflow events and registry payloads.
  - `github.com/smartcontractkit/chainlink-common` — `pkg/capabilities` contracts, `logger`, `services/servicetest`, `settings/limits`, `beholder` (test observations are asserted on Beholder user logs).
  - `github.com/smartcontractkit/chain-selectors` — chain selector for `GETH_TESTNET` (chain ID `1337`) used by the workflow trigger registration.
- **Test & utility libraries:** `go-ethereum` (ABI decoding, binding primitives, `bind.WaitMined`), `testify`, `go.uber.org/zap` + `zaptest/observer` (in-memory log capture), `BurntSushi/toml`, `yaml.v3`, `brotli` (WASM compression), `google/uuid`, `jonboulle/clockwork`, protobuf.

> **Why this matters for maintainers:** the `go.mod` is the contract that keeps the tests aligned with the code under test. Bumping `chainlink/v2` or `chainlink-common` here can change framework behaviour (fakes, registries) and thus test outcomes; the local `replace` directives guarantee HTTP-capability changes are picked up without publishing.

### EVM test contract binding (`MessageEmitter.go`)

**File:** `capabilities/integration_tests/evm/contract/MessageEmitter.go`
**Component IDs:** `ContractCallerRaw`, `ContractCallerSession`, `ContractRaw`, `ContractSession`, `ContractTransactorRaw`, `ContractTransactorSession`

This file is a **generated Go binding ("Code generated – DO NOT EDIT")**, produced by go-ethereum's `abigen` tool from a small Solidity helper contract whose sole purpose is to **emit EVM logs** that the log-trigger capability can be tested against. It embeds the contract ABI (`ContractMetaData.ABI`) and the deployment bytecode (`ContractMetaData.Bin`).

The contract exposes:

| Solidity surface | Go surface | Purpose in tests |
|---|---|---|
| `emitMessage(string)` — selector `0x2ac0df26` | `EmitMessage(opts, message)` | Emits `MessageEmitted(string message)` — a **single non-indexed topic** event, used for the simple log-trigger cases (one filter topic = topic0). |
| `emitMultiTopic(uint256,uint256,uint256,string)` — selector `0xc6aea905` | `EmitMultiTopic(opts, topic2, topic3, topic4, message)` | Emits `MultiTopicEmitted(uint256 indexed topic2, uint256 indexed topic3, uint256 indexed topic4, string message)` — **three indexed topics**, used to exercise multi-topic filtering (e.g. topic0 + topic2, topic0 + topic2 + topic4). |
| `MessageEmitted` event — hash `0x50ede1f1…` | `FilterMessageEmitted` / `WatchMessageEmitted` / `ParseMessageEmitted` | Generated filterer APIs (used by tests for log inspection if needed). |
| `MultiTopicEmitted` event — hash `0x815c4a45…` | `FilterMultiTopicEmitted` / `WatchMultiTopicEmitted` / `ParseMultiTopicEmitted` with topic rules | Topic-filter aware log iteration. |

The six named components follow the standard `abigen` layering:

```mermaid
classDiagram
    class Contract {
        +ContractCaller caller
        +ContractTransactor transactor
        +ContractFilterer filterer
    }
    class ContractSession {
        +Contract *Contract
        +CallOpts bind.CallOpts
        +TransactOpts bind.TransactOpts
        +EmitMessage(message) tx
        +EmitMultiTopic(t2, t3, t4, msg) tx
    }
    class ContractCallerSession {
        +Contract *ContractCaller
        +CallOpts bind.CallOpts
    }
    class ContractTransactorSession {
        +Contract *ContractTransactor
        +TransactOpts bind.TransactOpts
    }
    class ContractRaw {
        +Call(opts, result, method, params)
        +Transfer(opts)
        +Transact(opts, method, params)
    }
    class ContractCallerRaw {
        +Call(opts, result, method, params)
    }
    class ContractTransactorRaw {
        +Transfer(opts)
        +Transact(opts, method, params)
    }
    Contract o-- ContractSession
    Contract o-- ContractRaw
    ContractSession ..> ContractRaw : low-level fallback
    Contract o-- ContractCallerSession
    Contract o-- ContractTransactorSession
    ContractCallerSession ..> ContractCallerRaw : low-level fallback
    ContractTransactorSession ..> ContractTransactorRaw : low-level fallback
```

- **`ContractSession`** — the high-level binding used by the tests: it wraps a `*Contract` with pre-set `CallOpts`/`TransactOpts` and exposes `EmitMessage` / `EmitMultiTopic` as plain Go calls. The tests always call these through `donContext.EthBlockchain.TransactionOpts()`.
- **`ContractRaw`** — the low-level, method-name-as-string surface (`Call`, `Transfer`, `Transact`) that session types delegate to.
- **`ContractCallerSession` / `ContractCallerRaw`** — the read-only pair (constant calls); the contract has no view functions, so these exist purely as part of the generated pattern.
- **`ContractTransactorSession` / `ContractTransactorRaw`** — the write-only pair hosting the two mutator transactions.

Supporting generated API (same file):

- `DeployContract(auth, backend)` — deploys from the embedded bytecode and returns `(address, tx, *Contract, error)`. The tests call this via `defaultDeployContracts` and the multi-address test case (which deploys **two** instances to verify address filtering).
- `NewContract` / `NewContractCaller` / `NewContractTransactor` / `NewContractFilterer` / `bindContract` — bind instances to an already-deployed address.
- `ContractMessageEmittedIterator` / `ContractMultiTopicEmittedIterator` — channel-based log iterators with `Next`/`Error`/`Close` semantics, plus typed event structs carrying the decoded fields and the raw `types.Log`.

The ABI is additionally available to tests as a standalone file, `evm/contract/MessageEmitter.abi`, which the test reads to compute **topic0** (`event.ID`) for building `RuntimeConfig` filters — keeping the trigger registration in sync with the emitted events.

---

## Test Suites

### 1. EVM log-trigger tests (`evm/`)

`evm_logtrigger_test.go` is a **table-driven harness**. Each `logTriggerTestCase` declares:

- `workflowName` — the WASM workflow registered with the DON;
- `eventName` — `MessageEmitted` or `MultiTopicEmitted`;
- `matchingMessages` — payloads that must appear in workflow user logs;
- `deployContractsFn` / `buildRuntimeConfigFn` / `emitEventsFn` — pluggable strategies for deployment, trigger configuration and event emission;
- `verifyNonMatchingIgnored` — whether non-matching events (marked with the sentinel string `"NON MATCHING"`) must be proven *ignored*.

Executed test functions:

| Test | Scenario |
|---|---|
| `Test_SimpleLogTrigger` | One `MessageEmitted` topic0 filter, repeated for each confidence level — `SAFE` (0), `LATEST` (1), `FINALIZED` (2). |
| `Test_LogTriggerMultipleTopics` | Multi-topic filters: topic2 only; topic2 **and** topic4 (wildcard topic3). Non-matching emissions (e.g. topic2 = 999) must not surface in workflow logs. |
| `Test_LogTriggerMultipleAddressesAndTopics` | Two deployed `MessageEmitter` instances, topic2 allow-list `{42, 23}`, non-matching emissions from each contract ignored. |

Key mechanics:

- **Workflow under test** — `evm/workflow/main_logtrigger_wasip1.go` is a `cre-sdk-go` workflow registering an `evm.LogTrigger` on `chainselectors.GETH_TESTNET` (chain ID `1337`). It is compiled at test time by `utils.CreateWasmBinary` (`GOOS=wasip1`, `GOARCH=wasm`) and served to the DON compressed via brotli + base64 (`utils.GetCompressedWorkflowWasm`). The trigger config is the `RuntimeConfig` YAML structure from `evm/logTriggerConfig.go` — deliberately shared between test and workflow packages to avoid duplication.
- **DON sizing & quorum** — tests run **4 workflow nodes with f = 1**; a matching message counts as delivered once it appears in user logs from at least `N - F` nodes (`require.Eventually`, 90s window, 2s poll).
- **Assertions** — performed on two observation channels:
  1. **Beholder user logs** (`getBeholderLogsForWorkflow`) — each matching message must reach quorum; any occurrence of `"NON MATCHING"` in a workflow log fails the test.
  2. **Zap observer** (`zaptest/observer`) — waits for log-poller filters to register on all nodes, then verifies **trigger ACKs** (`Event ACK` log entries matched by the emitting transaction hash embedded in `eventID`).
- **Mining sync** — emitted transactions are awaited with `bind.WaitMined` against the framework's Ethereum client before assertions begin.

### 2. HTTP capability tests (`http/`)

The `http` package exercises the **http_action capability in `proxyMode: "gateway"`**: instead of invoking the capability in-process, tests wire the real **chainlink gateway stack** (`core/services/gateway`, `config`, `connector`, `network`) in front of a locally started HTTP server (`startTestHTTPServer` on `127.0.0.1:0`). Supporting files:

- `http_test.go` — core action round-trip through the gateway with signed (Ethereum `personal_sign`-style) challenge authentication between node and gateway; uses `servicetest.Runner` for lifecycle management and `settings/limits` configuration.
- `http_trigger_test.go` — the trigger counterpart, delivering webhook-style trigger events through the gateway into a workflow.
- `http_action_routing_test.go` — routing behaviours of the gateway proxy (`gateway_config_test_helpers.go` builds the node/service TOML+JSON configs; `kvstore.go` provides an in-test KV backend).

### 3. Shared helpers (`utils/`)

- **`deploy.go`** — `DeployCapability(t, name)` builds a standard-capability binary from the sibling workspace directory (`../../<name>`) with debug flags (`-gcflags "all=-N -l"`) into `integration_tests_temp/`; `CleanupCapabilitiesDir` removes built artefacts. This is how cron/standard capabilities get launched as real plugin processes (see the [Loop plugin framework](../Plugin_Process_Framework_(Loop).md)).
- **`wasm.go`** — `CreateWasmBinary` compiles a workflow main file to WASM; `GetCompressedWorkflowWasm` brotli-compresses it and returns the base64 string expected by workflow registration.
- **`cron.go`** — `GetCronConfig` serialises the cron trigger's `fastestScheduleIntervalSeconds` config for job specs.

### 4. Operational scripts

`scripts/killAllZombieTestProcesses.sh` kills orphaned standard-capability processes left behind when a test run is interrupted (the README notes these zombies can interfere with subsequent runs).

---

## How It Fits Into the System

```mermaid
flowchart LR
    BUILD["Build &amp; workspace tooling<br/>(nx.json, Makefile, .golangci.yml)"] --> IT
    subgraph GROUP["Dev, Test &amp; Simulation Environments"]
        DEVENV["devenv"] 
        DOCKER["docker-dev-environments"]
        DEPLOYENV["deployment-environment"]
        INTEG["integration-tests<br/>(chainlink product e2e)"]
        SYST["system-tests (CRE)"]
        IT["capabilities_integration_tests<br/>(capability e2e)"]
    end
    CRE["Workflow &amp; Capability Runtime<br/>(CRE Engine)"] -->|"capabilities<br/>under test"| IT
    FOUND["Shared Foundation Libraries<br/>(capabilities types, logger, servicetest)"] --> IT
    IT -->|"runs against"| CRE
    SYST -.->|"full CRE system coverage"| CRE
```

- **Within this module group** it is the *capability-focused* e2e layer: [devenv](devenv.md) and the [docker dev environments](docker-dev-environments.md) provide infrastructure simulation, the [deployment environment](deployment-environment.md) and [node web SDK](chainlink-node-web-sdk.md) target node/job management, while [integration-tests](integration-tests.md) and [system-tests](system-tests.md) validate whole products and CRE deployments. This module sits closest to the capability code itself.
- **Upstream**, the [CRE Engine](../Workflow___Capability_Runtime_(CRE_Engine).md) modules define the trigger/action capabilities these tests validate end-to-end, and the [Shared Foundation Libraries](../Shared_Foundation_Libraries___Domain_Types.md) supply the interfaces (`core.Capability`, `servicetest`, `settings`, `beholder`) the tests build upon.

---

## Running the Tests

From `capabilities/integration_tests/README.md`:

1. **Start PostgreSQL** and prepare the test database:
   ```bash
   go run github.com/smartcontractkit/chainlink/v2 local db preparetest
   ```
2. **Point the test runner at it:**
   ```bash
   export CL_DATABASE_URL=postgresql://chainlink_dev:insecurepassword@localhost:5432/chainlink_development_test?sslmode=disable
   ```
3. **Run tests** (from the workspace root, or directly from an IDE):
   ```bash
   ./nx run integration_tests:test -run ^TestHTTPTrigger$ -v
   ```
4. **If a run was killed**, clean up leftover standard-capability processes:
   ```bash
   ./scripts/killAllZombieTestProcesses.sh
   ```

The Nx targets (`test`, `lint`, `tidy`) are defined in `capabilities/integration_tests/project.json` and configured workspace-wide by `capabilities/nx.json`; Go module maintenance across all workspace modules is handled by the [capabilities workspace tooling](../Build,_CI___Release_Infrastructure/capabilities_workspace_tooling.md).

## Maintenance Notes

- **`MessageEmitter.go` is generated** — never hand-edit. Regenerate the binding (and keep `MessageEmitter.abi` in sync) whenever the Solidity helper contract changes; the tests read the `.abi` file at runtime to derive topic0 hashes.
- **Keep `RuntimeConfig` shared** — `evm/logTriggerConfig.go` is intentionally imported by both the tests and the WASM workflow so the YAML trigger config stays consistent; duplicating it in the workflow would break test fidelity.
- **Quorum-sensitive assertions** — the N−F user-log quorum (4 nodes, f=1) is coupled to the framework DON sizing; changing node counts in `assertLogTriggerWorks` requires revisiting timing windows (`require.Eventually` bounds).
- **Dependency bumps** — since `chainlink/v2` provides the test framework itself, treat `go.mod` upgrades of `chainlink/v2` and `chainlink-common` as behavioural changes to the harness, not just routine dependency updates.
