# CLI Shell — Local Commands (`shell_local.go`)

> Parent module: [CLI Commands](../cli_commands.md) · Grandparent: [Node Application, Core & Interfaces](../../Node_Application_Core___Interfaces.md)
>
> **Core component:** `HealthCheckPresenter` — `chainlink/core/cmd/shell_local.go`

## 1. Purpose and Scope

This module implements the **local (server-side) command surface** of the `chainlink` binary — the commands under `chainlink node` (alias `local`) that *must* run on the same machine as the node because they operate directly on its database, keystore files, and process lifecycle:

| Responsibility | Key entry points |
|---|---|
| Boot and run the full node application | `RunNode` / `runNode` |
| Prepare per-process resources (LockedDB, keystore, Beholder telemetry) for any local command | `BeforeNode` / `beforeNode`, `AfterNode` / `afterNode` |
| Database administration (reset, migrate, rollback, fixtures, cleanup) | `db` subcommand family, `validateDB` |
| Emergency operations (transaction rebroadcast, log-poller block pruning) | `RebroadcastTransactions`, `RemoveBlocks` |
| Configuration validation | `ConfigFileValidate` |
| CCV (Cross-Chain Verification) chain-status management | `initCCVCommand` |
| Health-check result presentation (the module's core component) | `HealthCheckPresenter`, `HealthCheckPresenters.RenderTable` |

Unlike the [remote resource commands](cli_commands_remote_resources.md), which are thin authenticated HTTP clients of a *running* node, every command here instantiates or manipulates node state directly.

## 2. Architecture Overview

### 2.1 Component map

```mermaid
flowchart TD
    subgraph Wiring["Command wiring (app.go)"]
        APP["cmd.NewApp(s *Shell)"] -->|"node / local<br/>Before hook: parse TOML,<br/>rebuild logger + OTel core"| NODECMD["cli.Command 'node'<br/>initLocalSubCmds(s, build.IsProd())"]
    end

    subgraph ThisModule["This module (shell_local.go)"]
        NODECMD --> START["start (aliases: node, n)<br/>RunNode"]
        NODECMD --> REB["rebroadcast-transactions<br/>RebroadcastTransactions"]
        NODECMD --> DB["db subcommands<br/>reset · preparetest · version<br/>status · migrate · rollback<br/>create-migration · delete-chain"]
        NODECMD --> RB["remove-blocks<br/>RemoveBlocks"]
        NODECMD --> VAL["validate<br/>ConfigFileValidate"]
        NODECMD --> CCV["ccv chain-statuses<br/>initCCVCommand"]
        NODECMD --> HC["status (deprecated → admin status)"]

        HCP["HealthCheckPresenter /<br/>HealthCheckPresenters<br/>RenderTable(RendererTable)"]
    end

    subgraph Rendering["Rendering framework (renderer.go)"]
        TR["TableRenderer interface"]
        RT["RendererTable (io.Writer)"]
        RL["renderList helper"]
    end

    HC -.->|"admin status<br/>(admin_commands.go) GET /health?full=1"| HCP
    HCP -->|"implements"| TR
    HCP -->|"uses"| RL
    TR -.->|"type-switch dispatch"| RT

    subgraph Downstream["Downstream subsystems"]
        APPSVC["services/chainlink<br/>Application (AppFactory)"]
        KS["services/keystore<br/>Master"]
        PG["pg.LockedDB +<br/>core/store/migrate"]
        BH["Beholder telemetry client"]
        WEBHC["core/web HealthController<br/>/health · /health/readyz"]
        CCVSVC["chainlink-ccv chainstatuses<br/>PostgresChainStatusStore"]
    end

    START -->|AppFactory.NewApplication| APPSVC
    START -->|Import / EnsureKey| KS
    START -->|EmitNodeConfig / Start| BH
    DB --> PG
    RB --> APPSVC
    CCV --> CCVSVC
    WEBHC -->|"presenters.Check payloads"| HCP
```

### 2.2 The `safe` flag and build modes

`initLocalSubCmds(s *Shell, safe bool)` receives `build.IsProd()` from the `node` command registration in `chainlink/core/cmd/app.go` (`Subcommands: initLocalSubCmds(s, build.IsProd())`). Destructive commands (`db reset`, `db preparetest`, `db create-migration`, `db delete-chain`) are marked `Hidden: safe` — they are **hidden in production builds** and only exposed in dev builds. This is controlled by the build tooling in [`chainlink/GNUmakefile`](../../Build,_CI___Release_Infrastructure/chainlink_build_and_tooling.md): `CL_IS_PROD_BUILD ?= true` for default builds, while the `install-chainlink-dev` target compiles with `go install -tags dev`, flipping `build.IsProd()` to `false`. Legacy deprecation warnings also live here: the old `node status` and `node profile` commands are hidden and redirect operators to `admin status` / `admin profile`.

## 3. Core Component: `HealthCheckPresenter`

### 3.1 Structure

```go
type HealthCheckPresenter struct {
    webPresenters.Check   // Name, Status, Output (+ embedded JAID.ID)
}

func (p *HealthCheckPresenter) ToRow() []string

type HealthCheckPresenters []HealthCheckPresenter

func (ps HealthCheckPresenters) RenderTable(rt RendererTable) error  // implements cmd.TableRenderer
```

- It embeds [`webPresenters.Check`](../web_api.md) (`chainlink/core/web/presenters/check.go`): the JSONAPI resource emitted by the node's health endpoints, carrying `Name`, `Status` (`web.HealthStatusPassing = "passing"` / `web.HealthStatusFailing = "failing"`, defined in `chainlink/core/web/health_controller.go`) and an `Output` message (the failing check's error string).
- `ToRow()` colorizes the status with `fatih/color` — **red** for `failing`, **green** for `passing` — and returns the `Name / Status / Output` triple. Unknown statuses are rendered uncolored, making the presenter forward-compatible with new health states.
- `HealthCheckPresenters.RenderTable` implements the [`TableRenderer`](cli_commands_renderer.md) contract and renders via the shared `renderList` helper (`renderer.go`) with headers `Name, Status, Output`. Dispatch happens through the `RendererTable.Render` type-switch `case TableRenderer`, so the global `--json` flag (which swaps the Shell's `Renderer` for `RendererJSON`) automatically yields JSON instead.

### 3.2 Data flow: node health report → terminal

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator
    participant CLI as chainlink admin status<br/>(Shell.Status, admin_commands.go)
    participant HTTP as AuthenticatedHTTPClient
    participant Node as Running node<br/>(web.HealthController)
    participant Checker as App.GetHealthChecker()
    participant HCP as HealthCheckPresenters<br/>(this module)
    participant RT as RendererTable

    Op->>CLI: chainlink admin status
    CLI->>HTTP: GET /health?full=1
    HTTP->>Node: request (session cookie)
    Node->>Checker: IsHealthy() → map[name]error
    Checker-->>Node: per-service errors (nil = passing)
    Node-->>HTTP: JSONAPI []presenters.Check<br/>{id, name, status, output}
    HTTP-->>CLI: *http.Response
    CLI->>CLI: renderAPIResponse → parse into &HealthCheckPresenters{}
    CLI->>RT: s.Render(model) → type-switch → RenderTable(rt)
    loop for each check
        HCP->>HCP: ToRow(): colorize status (red/green)
    end
    HCP->>RT: renderList(["Name","Status","Output"], rows)
    RT-->>Op: formatted health report
```

The same presenter type is deserialization *and* rendering target: because it embeds the JSONAPI-tagged `Check` resource plus `JAID`, `web.ParsePaginatedResponse` can unmarshal directly into `HealthCheckPresenters{}` before any rendering occurs — no intermediate DTO. The (hidden, deprecated) local `node status` command in this file invokes the very same `s.Status` implementation but prints a deprecation warning first, steering operators to `admin status`.

## 4. Node Startup Lifecycle (`RunNode`)

`chainlink node start` is the module's most complex command. It is a three-phase pipeline — **prepare (`BeforeNode`) → boot (`runNode`) → run & shut down**:

```mermaid
flowchart TD
    subgraph Phase1["Phase 1 — BeforeNode / beforeNode"]
        P1A["Load --password / --vrfpassword files<br/>Config.SetPasswords"] --> P1B["pg.NewLockedDB → Open<br/>(advisory lock + connection)"]
        P1B --> P1C["handleNodeVersioning:<br/>semver check · upgrade backup<br/>auto-migrate · upsert node version<br/>startup health-report server"]
        P1C --> P1D["sqlutil.WrapDataSource<br/>(TimeoutHook + MonitorHook)"]
        P1D --> P1E["keystore.New (scrypt params)<br/>KeyStoreAuthenticator.Authenticate"]
        P1E --> P1F["keystore.BuildBeholderAuth (CSA)<br/>→ Beholder client (real or Noop)"]
        P1F --> P1G["initGlobals: Prometheus · loop.GRPCOpts<br/>OTel providers / tracing"]
        P1G --> P1H["setupLogStreaming: otelzap core<br/>→ UpdatableCore (if LogStreamingEnabled)"]
        P1H --> P1I["BeholderClient.Start<br/>+ EmitNodeConfig (effective TOML)"]
    end

    subgraph Phase2["Phase 2 — runNode"]
        P2A["Beholder config recorder service<br/>Config.Validate · dev-mode warning<br/>RootDir 0700"] --> P2B["signal handler:<br/>SIGINT/SIGTERM → cancelRootCtx;<br/>grace period exceeded → close DB, exit(-1)"]
        P2B --> P2C["AppFactory.NewApplication<br/>(chainlink.Application)"]
        P2C --> P2D["Key provisioning per enabled relay:<br/>import + EnsureKey for EVM, Solana,<br/>Aptos, Stellar, Tron, TON, Sui, StarkNet,<br/>P2P, OCR, OCR2, DKG, Workflow, CSA"]
        P2D --> P2E["checkFilePermissions (warn/tighten)"]
        P2E --> P2F["API initializer:<br/>NewFileAPIInitializer or<br/>FallbackAPIInitializer (prompt)"]
        P2F --> P2G["app.Start(rootCtx)"]
    end

    subgraph Phase3["Phase 3 — run & shutdown"]
        P3A["errgroup:<br/>• ctx.Done → app.Stop()<br/>• Runner.Run → web router"] --> P3B{"SIGINT / SIGTERM?"}
        P3B -->|no| P3A
        P3B -->|yes| P3C["cancelRootCtx → app.Stop()<br/>→ grp.Wait returns"]
        P3C --> P3D["AfterNode / afterNode<br/>sync.Once: LDB.Close · CloseLogger<br/>BeholderClient.Close"]
    end

    Phase1 --> Phase2 --> Phase3
```

Key behaviors worth noting:

- **Idempotent key provisioning.** Each enabled chain family (gated by `GeneralConfig`, see [core config](../core_config.md)) gets `Import` for keys listed in config (tolerating `keystore.ErrKeyExists`) followed by `EnsureKey` for auto-creation. OCR2 keys are ensured only for the *enabled* relay set (EVM, Solana, StarkNet, Aptos, Tron, TON, Sui, Stellar). See the [keystore module](../../Node_Platform_Services/keystore.md).
- **Admin auth always local.** Unlike remote sessions ([sessions & auth](../sessions_auth.md)), startup initializes `app.BasicAdminUsersORM()` and seeds the API user from the `--api` credentials file, falling back to the interactive `FallbackAPIInitializer`.
- **Bounded shutdown.** `shutdown.HandleShutdown` cancels `rootCtx`; if the configured `ShutdownGracePeriod` elapses before `app.Stop()` completes, the shutdown handler explicitly closes the LockedDB (releasing file locks) and calls `os.Exit(-1)`, because deferred functions do not run after `os.Exit`. Graceful shutdown duration is logged via `static.InitTime`/timestamp.
- **Telemetry wiring.** `EmitNodeConfig` publishes the effective (defaults-applied) TOML through a `custmsg.Labeler` labelled with `system=Application`, version, and commit — a Beholder `pb.BaseMessage`. Details in [Beholder telemetry](../../Telemetry___Observability_Platform/beholder-telemetry.md). The application itself is documented in [node application lifecycle](../node_application/node_application_lifecycle.md).

## 5. Database Administration Commands

All `db` subcommands run `Before: s.validateDB` (which invokes `Config.ValidateDB`) and resolve the database URL from `CL_DATABASE_URL` or the secrets TOML (`Database.URL`), failing with `errDBURLMissing` when unset. Underlying persistence primitives are documented in [database persistence](../../Node_Platform_Services/database_persistence.md).

| Command | Implementation | Safety semantics |
|---|---|---|
| `db reset` | `store.ResetDatabase` (drop/create/migrate) | Refuses databases not suffixed `_test` unless `--dangerWillRobinson`; uses `DROP DATABASE … WITH (FORCE)` (PostgreSQL 13+) |
| `db preparetest` | `db reset` + `store.PrepareTestDB` fixtures | `--user-only` loads only the test-user fixture |
| `db migrate` | `migrate.SetMigrationENVVars(EVMConfigs)` → `migrate.Migrate` | Applies pending migrations |
| `db rollback` | `migrate.Rollback` | Optional version argument; one migration if omitted |
| `db version` / `db status` | `migrate.Current` / `migrate.Status` | Read-only |
| `db create-migration` | `migrate.Create` | Generates `.sql` (default) or `.go` migration files |
| `db delete-chain` | dynamic `DELETE … WHERE evm_chain_id = $1` against every table discovered via `information_schema` | EVM-only (`--type`); refuses non-`_test` databases without `--danger` |

```mermaid
flowchart LR
    CMD["chainlink node db …"] --> VDB["validateDB<br/>Config.ValidateDB"]
    VDB --> URL{"Database URL set?"}
    URL -->|no| ERR["errDBURLMissing"]
    URL -->|yes| KIND{Command}
    KIND -->|reset / preparetest| RST["store.ResetDatabase<br/>+ PrepareTestDB"]
    KIND -->|migrate / rollback / version / status / create-migration| MIG["core/store/migrate"]
    KIND -->|delete-chain| DEL["information_schema scan →<br/>DELETE rows by evm_chain_id"]
```

## 6. Operational Commands

### 6.1 `rebroadcast-transactions`

Emergency recovery for a stuck EVM transaction queue. The flow:

1. Validate config and construct an `Application` via `AppFactory`.
2. Fetch the legacy EVM chain service: `app.GetRelayers().LegacyEVMChains().Get(chainID)` and assert it to `legacyevm.Chain` — rebroadcast is **not available in loop (plugin-process) mode** (marked with a `//nolint:staticcheck` and TODO BCF-2511 for a chain-agnostic design; relay architecture in [node application relay](../node_application/node_application_relay.md)).
3. Dial the EVM client, unlock the keystore, and verify the signer address is enabled for the chain (`keyStore.Eth().CheckEnabled`).
4. Assemble the `txmgr` stack — `TxStore`, `EvmTxAttemptBuilder`, `EvmTxmFeeConfig`, `StuckTxDetector`, `EVMTxmMetrics`, `EvmConfirmer` — and call `ec.ForceRebroadcast(ctx, nonces, gas.EvmFee{GasPrice}, address, overrideGasLimit)` for the inclusive nonce range.
5. Reject gas prices exceeding `math.MaxInt64` (overflow guard).

### 6.2 `remove-blocks`

Prunes log-poller data: requires `--start` (positive) and `--evm-chain-id`, validates config, builds an `Application`, and delegates to `app.DeleteLogPollerDataAfter(ctx, chainID, start)`. Signal handling closes the DB and releases the lock via `afterNode`.

### 6.3 `ccv chain-statuses`

`initCCVCommand` builds a `ccv` → `chain-statuses` command tree from the external `chainlink-ccv/verifier` module (`chainstatuses.InitCCVChainStatusesCommandsWithFactory`). The factory injects:

- a `ccvLoggerAdapter` that augments the shell logger with an `Errorw` method the CCV library expects, and
- a `chainstatus.NewPostgresChainStatusStore` backed by the shell's `DataSource` (`s.DS`, set up by `BeforeNode`).

Commands list/enable/disable chain statuses and set finalized block heights; the usage text warns that the node must be shut down first since changes take effect on next start. Related configuration in [core config CCV](../core_config/core_config_ccv.md).

### 6.4 `validate`

`ConfigFileValidate` pretty-prints the merged, defaults-applied configuration (`Config.LogConfiguration`), then runs `Config.Validate` through `configExitErr` (pretty-prints `Invalid configuration: …` and exits non-zero). This is the supported replacement for the deprecated remote `config validate`.

## 7. Security Posture

The module enforces several defensive measures on every startup or privileged local command:

1. **Directory permissions** — `utils.EnsureDirAndMaxPerms(RootDir, 0700)` before boot.
2. **TLS directory hardening** — `checkFilePermissions` walks `<root>/tls` and demotes any file exceeding the `ownerPermsMask` (`0o700`).
3. **Protected files** — `secret`, `cookie`, `.password`, `.env`, `.api` under the root dir are permission-tightened and checked for chainlink-user ownership (`utils.IsFileOwnedByChainlink`); non-owned files log a warning that will become mandatory.
4. **Destructive-command gating** — the `safe` build flag and `_test`-suffix / `--danger*` guards described in §2.2 and §5.
5. **Dev-mode disclosure** — `build.IsDev()` prints a prominent warning that the node must not run in production.

## 8. Dependencies and Related Modules

| Dependency | Relationship | Documentation |
|---|---|---|
| `cmd/renderer.go` | `HealthCheckPresenters` implements `TableRenderer` and uses `renderList`; `RendererTable`/`RendererJSON` chosen by the global `--json` flag | [CLI rendering framework](cli_commands_renderer.md) |
| `cmd/admin_commands.go`, `shell_remote.go` | Consumers: `admin status` / `health` fetch node health over authenticated HTTP and render through this module's presenter | [CLI remote resource commands](cli_commands_remote_resources.md), [CLI commands overview](../cli_commands.md) |
| `core/web` | Source of `presenters.Check` and the `passing`/`failing` status constants; the JSONAPI health contract | [Web API](../web_api.md) |
| `services/chainlink.Application` | Created by `RunNode`, `RebroadcastTransactions`, `RemoveBlocks` via `AppFactory` | [Node application](../node_application.md), [lifecycle](../node_application/node_application_lifecycle.md) |
| `GeneralConfig` | Gates every key-provisioning branch and validation path | [Core config](../core_config.md) |
| Keystore & `pg.LockedDB` / migrations | Initialized in `beforeNode`; all key ensure/import and `db` operations flow through them | [Keystore](../../Node_Platform_Services/keystore.md), [Database persistence](../../Node_Platform_Services/database_persistence.md) |
| Beholder / OTel | Config emission, log streaming core, global providers | [Beholder telemetry](../../Telemetry___Observability_Platform/beholder-telemetry.md) |

## 9. Extending the Module

1. **New local command** — add it to `initLocalSubCmds`; use `Before: s.BeforeNode` / `After: s.AfterNode` when it needs DB, keystore, or telemetry access, and route errors through `s.errorOut` for consistent exit codes. Destructive commands must be gated with `Hidden: safe` plus explicit runtime confirmation flags.
2. **New renderable output** — implement `TableRenderer` (`RenderTable`) on a presenter pair (single + slice) and reuse `renderList`; do not extend the legacy `RendererTable.Render` type-switch (see [rendering framework](cli_commands_renderer.md)).
3. **New chain family in startup** — the key-provisioning block in `runNode` follows a fixed pattern: read imported keys from `GeneralConfig`, `Import` (tolerate `ErrKeyExists`), then `EnsureKey`. Extend `keystore.Master` and the config tree together (see [keystore](../../Node_Platform_Services/keystore.md)).
