# Docker Dev Environments — Observability Stack

> **Module page:** `Dev,_Test___Simulation_Environments/docker-dev-environments/docker-dev-environments_observability-stack.md`
> **Primary artifact:** `chainlink/tools/docker/docker-compose.observability.yaml`

## 1. Introduction

The **observability stack** is an optional Docker Compose overlay that adds metrics collection, dashboarding, and alerting to the local Chainlink node development environment. It is deliberately lightweight — three off-the-shelf OSS containers with zero custom code — and is intended purely for **local development and experimentation**, not production observability.

The module consists of a single Compose file (`chainlink/tools/docker/docker-compose.observability.yaml`) that declares three services:

| Service | Image | Container name | Purpose |
|---|---|---|---|
| `prometheus` | `prom/prometheus:main` | `chainlink-prometheus` | Scrapes node `/metrics` endpoints, stores time series, evaluates alert rules |
| `grafana` | `grafana/grafana:10.4.3` | *(compose-generated)* | Visualization layer; auto-provisioned with Prometheus + Alertmanager datasources |
| `alertmanager` | `prom/alertmanager:main` | `chainlink-alertmanager` | Deduplicates, groups, and routes Prometheus alerts (email receiver) |

It is activated through the `compose` wrapper script (`chainlink/tools/docker/compose`) when the `WITH_OBSERVABILITY` environment variable is set, as documented in `chainlink/tools/docker/README.md`.

This page documents the stack's architecture, its configuration surface, the metrics/alerting data flow, and its relationship to the rest of the system.

---

## 2. Position in the System

This module is one of four overlays/services groups under the [Docker Dev Environments](../docker-dev-environments.md) umbrella:

```mermaid
flowchart TD
    ROOT["Dev, Test & Simulation Environments<br/>(../Dev,_Test___Simulation_Environments.md)"] --> DDE["docker-dev-environments<br/>(./docker-dev-environments.md)"]
    DDE --> ND["Node Deployment<br/>docker-compose.yaml + docker-compose.postgres.yaml<br/>(./docker-dev-environments_node-deployment.md)"]
    DDE --> DS["Devnet Simulators<br/>gethnet / paritynet<br/>(./docker-dev-environments_devnet-simulators.md)"]
    DDE --> DWO["Dev Workflow Overlay<br/>docker-compose.dev.yaml<br/>(./docker-dev-environments_dev-workflow-overlay.md)"]
    DDE --> OBS["<b>Observability Stack</b><br/>docker-compose.observability.yaml<br/>(this page)"]

    ND -- "exposes /metrics on :6688" --> OBS
    DS -- "provides blockchain for nodes" --> ND
    DWO -. "rebuilt node image" .-> ND
```

The observability stack is a **consumer** of the services defined by [Node Deployment](docker-dev-environments_node-deployment.md): the `node` and `node-2` containers (built from `core/chainlink.Dockerfile`, see [Chainlink Build and Tooling](../../Build,_CI___Release_Infrastructure/chainlink_build_and_tooling.md)) run the Chainlink node whose WebServer exposes a `/metrics` endpoint on port `6688` (see [Node Application Lifecycle](../../Node_Application_Core___Interfaces/node_application/node_application_lifecycle.md)).

---

## 3. Architecture

The stack is self-contained in a private Compose network; all inter-service communication uses Docker DNS names. Named volumes provide persistence for each component's data.

```mermaid
flowchart TB
    subgraph OBSFILE["chainlink/tools/docker/docker-compose.observability.yaml"]
        subgraph PROM["Service: prometheus (chainlink-prometheus)"]
            P1["prom/prometheus:main<br/>flags: --config.file, --storage.tsdb.path,<br/>--web.console.libraries, --web.console.templates"]
            P2["bind mount: ./prometheus/ → /etc/prometheus/"]
            P3[("named volume: prometheus_data → /prometheus (TSDB)")]
        end
        subgraph GRAF["Service: grafana (user 472)"]
            G1["grafana/grafana:10.4.3<br/>ports: 3000:3000"]
            G2["bind mount: ./grafana/provisioning/ → /etc/grafana/provisioning/"]
            G3["env_file: ./grafana/config.monitoring"]
            G4[("named volume: grafana_data → /var/lib/grafana")]
            G5["depends_on: prometheus, alertmanager"]
        end
        subgraph AM["Service: alertmanager (chainlink-alertmanager)"]
            A1["prom/alertmanager:main<br/>flags: --config.file=/config/alertmanager.yml<br/>--log.level=debug"]
            A2["bind mount: ./alertmanager/ → /config"]
            A3[("named volume: alertmanager-data → /data")]
        end
    end

    V["Named volumes: prometheus_data · grafana_data · alertmanager-data"]

    P2 -.-> P1
    P3 -.-> P1
    G2 -.-> G1
    G3 -.-> G1
    G4 -.-> G1
    A2 -.-> A1
    A3 -.-> A1
```

Key structural facts from `docker-compose.observability.yaml`:

- **All three services use `restart: always`** — the stack self-heals and survives Docker daemon restarts.
- **`grafana` is the only service with `depends_on`** (`prometheus`, `alertmanager`). Because the `compose` script explicitly starts only `node` and `grafana` (see §7), Grafana acts as the *entry service* that pulls the other two containers up.
- **Prometheus and Alertmanager are pinned to the floating `main` tag**, while Grafana is pinned to `10.4.3`. Expect `main`-tag images to drift; pin them for reproducibility if needed.
- Grafana runs as UID `472` (the official Grafana image user) so the `grafana_data` volume has correct ownership.
- Prometheus container console assets (libraries/templates) are enabled via command flags for the built-in UI.

---

## 4. Configuration Surface

The stack is entirely configuration-driven via files bind-mounted from `chainlink/tools/docker/`:

| File | Mounted into | Role |
|---|---|---|
| `chainlink/tools/docker/prometheus/prometheus.yaml` | `prometheus:/etc/prometheus/prometheus.yaml` | Scrape jobs, scrape intervals, Alertmanager routing |
| `chainlink/tools/docker/alertmanager/alertmanager.yml` | `alertmanager:/config/alertmanager.yml` | Alert routing tree and receivers |
| `chainlink/tools/docker/grafana/config.monitoring` | `grafana` env_file | Grafana env vars (admin password, sign-up policy) |
| `chainlink/tools/docker/grafana/provisioning/datasources/datasource.yml` | `grafana:/etc/grafana/provisioning/` | Declarative datasource provisioning |

### 4.1 Prometheus (`prometheus/prometheus.yaml`)

```yaml
global:
  scrape_interval: 5s
scrape_configs:
  - job_name: 'local_scrape'
    scrape_interval: 1s
    static_configs:
      - targets: ['chainlink-node:6688', 'chainlink-node-2:6688']
    metrics_path: '/metrics'
alerting:
  alertmanagers:
    - scheme: http
      static_configs:
        - targets: ['alertmanager:9093']
```

- **Global scrape interval 5s**, but the `local_scrape` job overrides it to **1s** for high-resolution local debugging.
- Targets use Docker service DNS names matching the `container_name` values from [Node Deployment](docker-dev-environments_node-deployment.md) (`chainlink-node`, `chainlink-node-2`), both on the node's internal port `6688`.
- Alerts are forwarded to `alertmanager:9093` over plain HTTP.

### 4.2 Alertmanager (`alertmanager/alertmanager.yml`)

- **Route:** all alerts go to the `mail` receiver; `group_by: [alertname]` batches alerts of the same name; `repeat_interval: 4h` limits re-notification noise.
- **Receiver:** a single SMTP email receiver targeting `smtp.gmail.com:465` with **placeholder credentials** (`your_mail@gmail.com` / empty `auth_password`). **You must edit this file** (and ideally supply the password via a secret rather than the bind-mounted file) before expecting email delivery.

### 4.3 Grafana environment (`grafana/config.monitoring`)

```
GF_SECURITY_ADMIN_PASSWORD=foobar
GF_USERS_ALLOW_SIGN_UP=false
```

- Admin UI password is the well-known development value `foobar`.
- Self sign-up is disabled; the `admin` account is the only entry point.

### 4.4 Grafana datasource provisioning (`grafana/provisioning/datasources/datasource.yml`)

Provisioned at container start, so a fresh volume needs no manual setup:

| Datasource | URL | Notes |
|---|---|---|
| `Prometheus` | `http://prometheus:9090` | Type `prometheus`, access `proxy`, **`isDefault: true`**, editable |
| `Alertmanager` | `http://alertmanager:9093` | Type `alertmanager`, `implementation: prometheus`, `handleGrafanaManagedAlerts: false` |

The provisioning file also declares a `deleteDatasources` entry for any stale `Prometheus` datasource in the database volume, guaranteeing a clean re-provision on restart.

---

## 5. Metrics & Data Flow

The end-to-end pipeline for one scrape/alert cycle:

```mermaid
sequenceDiagram
    autonumber
    participant N as chainlink-node / chainlink-node-2
    participant P as Prometheus (chainlink-prometheus)
    participant AM as Alertmanager (chainlink-alertmanager)
    participant G as Grafana
    participant D as Developer

    loop every 1s (local_scrape job)
        P->>N: GET http://chainlink-node:6688/metrics
        N-->>P: Prometheus exposition format metrics
        P->>P: Append samples to TSDB (prometheus_data volume)
    end

    P->>P: Evaluate alert rules against stored series
    P->>AM: POST firing alerts (http://alertmanager:9093)
    AM->>AM: Group by alertname · dedupe · 4h repeat interval
    AM-->>D: SMTP email (smtp.gmail.com:465, placeholder creds)

    G->>P: PromQL queries via default datasource
    G-->>AM: Alertmanager datasource (view alert state)
    D->>G: Browse dashboards & alerts (localhost:3000, admin/foobar)
    D->>P: Inspect raw metrics / UI (localhost:9090)
    D->>AM: Inspect routing / silences (localhost:9093)
```

Flow summary:

1. **Expose** — each Chainlink node serves `/metrics` on its WebServer port (`6688`); nothing in this module changes node configuration (the node's `config.toml` is generated from `config.toml.tmpl` by the `compose` script and contains no observability-specific settings).
2. **Scrape & store** — Prometheus pulls both nodes every second into its TSDB volume.
3. **Alert** — Prometheus evaluates rules and pushes alerts to Alertmanager, which routes them to the email receiver.
4. **Visualize** — Grafana queries Prometheus for dashboards and proxies Alertmanager state; humans interact only with Grafana on port `3000` in the common case.

---

## 6. Alerting Component Interaction

```mermaid
flowchart LR
    subgraph Sources
        N1["chainlink-node :6688"]
        N2["chainlink-node-2 :6688"]
    end
    subgraph Prometheus
        SC["local_scrape job<br/>(1s interval)"]
        TSDB[("prometheus_data")]
        RULES["Alert rule evaluation"]
    end
    subgraph Alertmanager
        RT["route tree<br/>group_by: alertname<br/>repeat_interval: 4h"]
        RC["receiver: mail<br/>SMTP gmail :465"]
        DATA[("alertmanager-data")]
    end
    subgraph Grafana
        DS1["Datasource: Prometheus<br/>(default, proxy)"]
        DS2["Datasource: Alertmanager"]
        UI["Dashboards / Alert UI :3000"]
    end

    N1 --> SC
    N2 --> SC
    SC --> TSDB --> RULES
    RULES -- "firing alerts" --> RT
    RT --> RC
    RT -.-> DATA
    DS1 -- "PromQL" --> TSDB
    DS2 -- "alert state" --> RT
    UI --> DS1
    UI --> DS2
```

---

## 7. Activation & Lifecycle

The stack is **not started by default**. It is wired into the developer workflow by the `compose` shell script (`chainlink/tools/docker/compose`):

```sh
# from chainlink/tools/docker
WITH_OBSERVABILITY=true ./compose up    # full cluster (2 nodes + 2 DBs + devnet + observability)
WITH_OBSERVABILITY=true ./compose dev   # single node, watch-mode rebuild + observability
```

```mermaid
flowchart TD
    A["./compose dev / up"] --> B{"WITH_OBSERVABILITY set?"}
    B -- "no" --> C["base files only:<br/>docker-compose.yaml<br/>+ docker-compose.postgres.yaml<br/>+ gethnet/paritynet (if no RPC URLs)"]
    B -- "yes" --> D["Append -f docker-compose.observability.yaml<br/>to the compose file list"]
    D --> E["Add 'grafana' to the service args<br/>(args = 'node grafana')"]
    E --> F["docker compose build && up -d node grafana"]
    F --> G["Grafana's depends_on pulls up<br/>prometheus + alertmanager"]
    G --> H["Datasources auto-provisioned from<br/>./grafana/provisioning/datasources/datasource.yml"]
    H --> I["Stack ready: scrape @1s, dashboards on :3000"]
```

Lifecycle notes (from the `compose` script):

- `./compose clean` runs `docker compose down -v` on the **full file list**, so when `WITH_OBSERVABILITY=true` is exported at clean time, the `prometheus_data`, `grafana_data`, and `alertmanager-data` volumes are deleted too.
- `./compose logs [service]` works for `prometheus`, `grafana`, and `alertmanager` since they run under the same Compose project.
- `db:restart` / `eth:restart` reset workflows only touch the base services; observability data is unaffected.
- The `up` command runs `$base up` with **no** service args, which starts every service in the merged file list — including the observability stack — in the foreground.

---

## 8. Access Points

| Component | URL / address | Credentials |
|---|---|---|
| Grafana UI | `http://localhost:3000` | user `admin`, password `foobar` (from `grafana/config.monitoring`) |
| Prometheus UI / API | `http://localhost:9090` | none (unauthenticated) |
| Alertmanager UI | `http://localhost:9093` | none (unauthenticated, `--log.level=debug`) |
| Node metrics (in-network) | `http://chainlink-node:6688/metrics`, `http://chainlink-node-2:6688/metrics` | n/a (host access via `6688` / `6699` from the node compose file) |

---

## 9. Persistence Model

All state is held in **named volumes** declared at the bottom of `docker-compose.observability.yaml` (`prometheus_data`, `grafana_data`, `alertmanager-data`), meaning:

- Metric history, Grafana dashboards/users, and Alertmanager silences/notifications survive container restarts and `stop`/`start` cycles.
- Configuration is *not* in volumes — it lives in the bind-mounted files under `chainlink/tools/docker/` and is version-controlled with the repo.
- Only `docker compose down -v` (e.g. `./compose clean`) wipes this state.

---

## 10. Relationship to Other Observability Modules

This stack is the **simplest tier** of Chainlink's observability tooling. For production-shaped or code-driven observability, see the [Telemetry & Observability Platform](../../Telemetry___Observability_Platform.md) module:

| Concern | This module | Related module |
|---|---|---|
| Local metrics scraping & alerting | ✅ Prometheus/Alertmanager/Grafana | — |
| Kafka-based monitoring pipeline for feeds (ZooKeeper/Kafka/Schema Registry) | — | [ops-monitoring-stack](../../Telemetry___Observability_Platform/ops-monitoring-stack.md) (`chainlink-common/ops/monitoring/docker-compose.yml`) |
| Programmatic Grafana dashboard provisioning (Go CLI/API client) | — | [observability-lib](../../Telemetry___Observability_Platform/observability-lib.md) |
| In-node OTLP telemetry emission (Beholder) | — | [beholder-telemetry](../../Telemetry___Observability_Platform/beholder-telemetry.md) |
| OCR/feed monitoring agents & Avro exporters | — | [monitoring](../../Telemetry___Observability_Platform/monitoring.md) |

Prometheus can scrape the same `/metrics` endpoint regardless of whether nodes emit OTLP telemetry via Beholder; the two mechanisms are complementary and covered respectively by this module and the Beholder page.

---

## 11. Operational Notes & Customization

- **Add a scrape target:** append to `static_configs.targets` in `chainlink/tools/docker/prometheus/prometheus.yaml`, then `docker compose restart prometheus` (Prometheus does not hot-reload static configs here).
- **Change alert delivery:** edit the `receivers` block in `chainlink/tools/docker/alertmanager/alertmanager.yml`. The shipped `mail` receiver is a template with placeholder Gmail credentials.
- **Dashboard management:** the shipped provisioning covers **datasources only** (no dashboards folder is mounted). Create dashboards in the UI (persisted in `grafana_data`), or manage them as code using [observability-lib](../../Telemetry___Observability_Platform/observability-lib.md).
- **Single-node dev (`./compose dev`):** Prometheus still scrapes two targets; `chainlink-node-2` will simply be `DOWN` in the targets view when only `node` is running — harmless, but expected.

### Security caveats (development-only)

1. All ports are published on all host interfaces (`0.0.0.0`), and Prometheus/Alertmanager expose unauthenticated UIs — **do not run this stack on a shared or internet-reachable host**.
2. The Grafana admin password is a hardcoded development default (`foobar`).
3. The Alertmanager email receiver invites putting SMTP credentials in a bind-mounted plaintext file; prefer Docker secrets or environment injection if credentials are required.

---

## 12. Summary

The observability stack is a three-service Compose overlay (`prometheus` + `grafana` + `alertmanager`) defined in `chainlink/tools/docker/docker-compose.observability.yaml`, activated by `WITH_OBSERVABILITY=true` through the `compose` wrapper script. It scrapes the local Chainlink nodes' `/metrics` endpoints at 1s resolution, persists time series and UI state in named volumes, provisions Grafana datasources declaratively, and routes Prometheus alerts to a configurable email receiver — providing a zero-code, batteries-included observability layer for local development, with heavier-duty alternatives documented under the [Telemetry & Observability Platform](../../Telemetry___Observability_Platform.md).
