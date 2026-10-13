# utils-hex

> Part of the [Shared Foundation Libraries & Domain Types](../Shared_Foundation_Libraries___Domain_Types.md) module group.

## 1. Introduction

The `utils-hex` module is a small, dependency-free hex-encoding utility package located at `chainlink-common/pkg/utils/hex` within the `github.com/smartcontractkit/chainlink-common` Go module (see `chainlink-common/go.mod`). It provides two complementary pieces of functionality that appear at nearly every boundary of the Chainlink system:

1. **`PlainHexBytes`** (`plainhex.go`) — a JSON-serializable byte-slice type that encodes to a *plain* hex string, i.e. **without** the `0x` prefix that go-ethereum's `hexutil.Bytes` assumes. The empty slice marshals as `""`.
2. **Hex-string helpers** (`hex.go`) — small utilities for the *prefixed* (`0x`-style) hex strings used throughout the EVM-facing parts of the node: prefix detection/normalization, `big.Int` parsing, and prefixed hex decoding.

The module is a classic **leaf utility**: it depends only on the Go standard library (`encoding/hex`, `encoding/json`, `errors`, `fmt`, `math/big`, `reflect`, `strings`) and imposes no transitive dependencies on its consumers. It is mirrored in spirit by the node-local utilities documented in [Core Shared Utilities](../Node_Application_Core___Interfaces/core_shared_utilities.md) (e.g. `abihelpers`), which build on top of such primitives.

---

## 2. Purpose and Role in the System

Binary blobs (key material, signatures, addresses, chain-specific payloads) frequently cross a JSON boundary in Chainlink:

| Boundary | Hex convention | Provided by |
|---|---|---|
| JSON APIs / TOML config for *non-EVM-specific* fields | plain hex, no `0x` | `PlainHexBytes` (`plainhex.go`) |
| EVM-facing values (addresses, hashes, tx payloads) | `0x`-prefixed (go-ethereum `hexutil` style) | helpers in `hex.go` |

Because the two conventions are easy to confuse, the package keeps them in one place with explicit, well-tested semantics:

- `PlainHexBytes` **rejects** any `0x`/`0X` prefix (the `x` is not a valid hex digit) and rejects odd-length input.
- `DecodeString` **requires** a `0x` prefix and silently zero-pads odd-length input (go-ethereum `FromHex`-like semantics).

This asymmetry is intentional and is covered by exhaustive, table-driven tests (see [§6 Testing](#6-testing)).

### Architectural position

```mermaid
flowchart TB
    subgraph foundation["Shared Foundation Libraries (chainlink-common)"]
        direction LR
        UT["pkg/utils/hex<br/>(this module)"]
        CODEC["pkg/codec"]
        VALS["pkg/values"]
        CFG["pkg/config"]
    end

    subgraph node["Node Application (chainlink core)"]
        KEEPER["Keystore services"]
        COREUTILS["core/utils &amp; abihelpers"]
        CONFIG["core/config parsing"]
    end

    subgraph plugins["Plugin &amp; capability ecosystem"]
        LOOP["loop (plugin processes)"]
        CAPS["capabilities"]
    end

    KEEPER -->|"0x-prefixed hex strings"| UT
    COREUTILS -->|"hex decode / prefix helpers"| UT
    CONFIG -->|"PlainHexBytes fields in TOML/JSON"| UT
    LOOP -->|"domain types embed hex fields"| UT
    CAPS -->|"chain configs / codecs"| UT

    UT --> STDLIB["Go stdlib only:<br/>encoding/hex, encoding/json,<br/>math/big, fmt, reflect, strings"]
```

Being a leaf with zero external dependencies, it is safe to import from almost any other module — including the standalone Go modules (`chainlink-common/keystore`, `chainlink-common/pkg/values`, the `capabilities/*` modules) that cannot depend on the root `chainlink-common` module itself.

---

## 3. Package Architecture

```mermaid
flowchart TB
    subgraph pkg["package hex (chainlink-common/pkg/utils/hex)"]
        subgraph plainhex["plainhex.go — JSON byte type"]
            PHB["type PlainHexBytes []byte"]
            MT["MarshalText() ([]byte, error)"]
            STR["String() string"]
            UJ["UnmarshalJSON(input []byte) error"]
            UT2["UnmarshalText(input []byte) error"]
            IS["isString(input []byte) bool<br/>(internal)"]
            CT["checkText(input, wantPrefix) ([]byte, error)<br/>(internal)"]
        end
        subgraph hexhelpers["hex.go — 0x-prefixed string helpers"]
            EP["EnsurePrefix(s string) string"]
            TP["TrimPrefix(s string) string"]
            HP["HasPrefix(s string) bool"]
            PB["ParseBig(s string) (*big.Int, error)"]
            DS["DecodeString(s string) ([]byte, error)"]
        end
        subgraph tests["plainhex_test.go — table-driven tests"]
            MARSHALTEST["type marshalTest {input, want}"]
            UNMARSHALTEST["type unmarshalTest {input, want, wantErr}"]
            TUB["TestUnmarshalBytes"]
            TMB["TestMarshalBytes"]
        end
    end

    UJ -->|"validates with"| IS
    UJ -->|"strips quotes, delegates"| UT2
    UT2 -->|"length/format checks"| CT
    UT2 -->|"hex.Decode"| STDLIBHX["encoding/hex"]
    MT -->|"hex.Encode"| STDLIBHX
    STR -->|"hex.EncodeToString"| STDLIBHX
    UJ -->|"non-string input"| STDLIBJ["encoding/json<br/>UnmarshalTypeError"]
    PB -->|"SetString(s, 16)"| BIG["math/big"]
    DS -->|"DecodeString"| STDLIBHX
    HP -.->|"used by"| TP
    HP -.->|"used by"| DS

    TUB -->|"iterates"| UNMARSHALTEST
    TMB -->|"iterates"| MARSHALTEST
    TUB -->|"exercises"| UJ
    TMB -->|"exercises"| MT
    TMB -->|"exercises"| STR
```

### 3.1 `PlainHexBytes` — JSON-friendly byte slice (`plainhex.go`)

```go
// PlainHexBytes marshals/unmarshals as a JSON string without a 0x prefix.
// The empty slice marshals as "".
type PlainHexBytes []byte
```

| Method | Behavior |
|---|---|
| `MarshalText()` | Encodes bytes to lowercase hex via `encoding/hex.Encode`; never fails for byte input. |
| `String()` | `hex.EncodeToString(b)` — same representation as `MarshalText`, returned as a `string`. |
| `UnmarshalJSON(input)` | Rejects non-string JSON values with `*json.UnmarshalTypeError{Value: "non-string"}`; otherwise strips the surrounding quotes and delegates to `UnmarshalText`. Errors are wrapped as `UnmarshalJSON failed: %w`. |
| `UnmarshalText(input)` | Empty string → empty slice. Odd-length input → `odd length` error. Invalid characters are rejected by `encoding/hex.Decode`. Errors are wrapped as `UnmarshalText failed: %w`. |

**Key semantic:** unlike go-ethereum's `hexutil.Bytes`, the `0x` prefix is *not* accepted. The literal `"0x"` fails with `encoding/hex: invalid byte: U+0078 'x'` — this is deliberately covered by the test table.

> Implementation note: `checkText(input, wantPrefix)` accepts a `wantPrefix` parameter for parity with go-ethereum's `hexutil`, but the current implementation ignores it (plain hex never wants a prefix). Empty input short-circuits to a `nil` slice; odd length yields the `odd length` error.

### 3.2 Prefixed hex-string helpers (`hex.go`)

| Function | Behavior |
|---|---|
| `EnsurePrefix(s)` | Prepends `0x` unless already present. Note: it checks only for a lowercase `0x` literal, so a string already starting with `0X` would gain a second prefix (`0x0X…`). |
| `HasPrefix(s)` | `true` if `s` starts with `0x` **or** `0X` (case-insensitive check). |
| `TrimPrefix(s)` | Strips a leading `0x`/`0X` (uses `HasPrefix`, so both cases are handled). |
| `ParseBig(s)` | Parses via `big.Int` `SetString(s, 16)`; on failure returns `failed to convert "%s" as hex to big.Int`. Because `math/big` accepts the `0x`/`0X` prefix for base 16, both plain and prefixed forms parse successfully. |
| `DecodeString(s)` | **Requires** a `0x` prefix (`hex string must have 0x prefix` otherwise), then zero-pads odd-length remainder and delegates to `encoding/hex.DecodeString`. Follows the semantics of go-ethereum's `FromHex`. |

### 3.3 Error taxonomy

Every failure mode is deterministic and string-asserted in tests:

```mermaid
flowchart TD
    A["Input value"] --> B{"JSON token is a string?"}
    B -->|"no (e.g. null, 123)"| C["*json.UnmarshalTypeError:<br/>'json: cannot unmarshal non-string into<br/>Go value of type hex.PlainHexBytes'"]
    B -->|"yes"| D{"String is empty?"}
    D -->|"yes"| E["OK — empty []byte"]
    D -->|"no"| F{"Length is even?"}
    F -->|"no"| G["'UnmarshalJSON failed:<br/>UnmarshalText failed: odd length'"]
    F -->|"yes"| H{"All chars are hex digits?"}
    H -->|"no (n, x, X, z, …)"| I["'UnmarshalJSON failed:<br/>UnmarshalText failed:<br/>encoding/hex: invalid byte: …'"]
    H -->|"yes"| J["OK — decoded []byte"]
```

Concrete reference table (as asserted by the test suite):

| JSON input | Result |
|---|---|
| *(empty JSON buffer)* | `unexpected end of JSON input` |
| `null` | `json: cannot unmarshal non-string into Go value of type hex.PlainHexBytes` |
| `"null"` | `UnmarshalJSON failed: UnmarshalText failed: encoding/hex: invalid byte: U+006E 'n'` |
| `"0x"` / `"0X"` | `UnmarshalJSON failed: UnmarshalText failed: encoding/hex: invalid byte: U+0078 'x'` / `'X'` |
| `"0"` | `UnmarshalJSON failed: UnmarshalText failed: odd length` |
| `"xx"`, `"01zz01"` | `UnmarshalJSON failed: UnmarshalText failed: encoding/hex: invalid byte: …` |
| `""` | empty byte slice |
| `"02"` | `[]byte{0x02}` |
| `"00000102"` | `[]byte{0x00, 0x00, 0x01, 0x02}` |

---

## 4. Data Flow

### 4.1 JSON round-trip through `PlainHexBytes`

```mermaid
sequenceDiagram
    participant App as Application code
    participant Enc as encoding/json
    participant PHB as hex.PlainHexBytes
    participant StdHex as encoding/hex

    Note over App,PHB: Marshaling (struct → JSON)
    App->>Enc: json.Marshal(payload containing PlainHexBytes)
    Enc->>PHB: MarshalText()
    PHB->>StdHex: hex.Encode(buf, b)
    StdHex-->>PHB: lowercase hex bytes (2 chars per byte)
    PHB-->>Enc: []byte("a1b2c3")
    Enc-->>App: {"field":"a1b2c3"}

    Note over App,PHB: Unmarshaling (JSON → struct)
    App->>Enc: json.Unmarshal(raw, &payload)
    Enc->>PHB: UnmarshalJSON(raw token)
    PHB->>PHB: isString()? strip quotes
    PHB->>PHB: UnmarshalText(body)
    PHB->>PHB: checkText(): empty? odd length?
    PHB->>StdHex: hex.Decode(dec, raw)
    StdHex-->>PHB: decoded bytes / error
    PHB-->>Enc: nil or wrapped error<br/>("UnmarshalJSON failed: UnmarshalText failed: …")
    Enc-->>App: populated struct or error
```

### 4.2 Prefixed-hex helper usage flow

```mermaid
flowchart TD
    IN["Incoming hex string<br/>(config value, API arg, chain response)"] --> Q{"Conventions differ by context"}

    Q -->|"EVM value, prefix unknown"| NORM["Normalize first"]
    NORM --> H{"HasPrefix(s)?"}
    H -->|"no"| EP2["EnsurePrefix(s)"]
    H -->|"yes"| TP2["TrimPrefix(s) if raw form needed"]
    EP2 --> PB2["ParseBig(s)<br/>→ *big.Int (amounts, numbers)"]
    EP2 --> DS2["DecodeString(s)<br/>→ []byte (addresses, hashes, payloads)"]

    Q -->|"Raw binary in JSON"| PHB2["Use PlainHexBytes field<br/>(no 0x, strict decode)"]

    PB2 --> OUT["Typed value for node logic"]
    DS2 --> OUT
    PHB2 --> OUT

    DS2 -.->|"missing 0x"| E1["error: hex string must have 0x prefix"]
    DS2 -.->|"odd length"| E2["auto zero-padded to even length"]
    PHB2 -.->|"odd length / 0x prefix /<br/>invalid chars"| E3["error surfaced with<br/>UnmarshalJSON/Text wrapping"]
```

**Guidance:** choose `PlainHexBytes` when *you* control both ends of the JSON contract and want strict, prefix-free encoding (TOML/JSON config fields, feeds configuration, non-EVM payloads). Use `DecodeString`/`ParseBig`/`EnsurePrefix` when consuming *external* EVM-style hex strings, which may or may not carry the prefix.

---

## 5. Component Interaction

`utils-hex` interacts with the rest of the system through plain Go interfaces — chiefly the standard library's `encoding.TextMarshaler`, `encoding.TextUnmarshaler`, and `json.Unmarshaler` contracts that `PlainHexBytes` implements. This means:

- **JSON APIs and config loaders** get correct hex handling automatically whenever a struct field is typed as `PlainHexBytes` — no custom marshal hooks required.
- **TOML configuration** (the node's primary config format, parsed via the TOML tooling in [Core Shared Utilities](../Node_Application_Core___Interfaces/core_shared_utilities.md) and validated by the patterns in [Config Validation](config-validation.md)) can bind hex fields directly, since TOML decoders honor `TextUnmarshaler`.
- **Domain types** elsewhere in `chainlink-common` — relayers, keystore bundles, and chain payloads (see [types-core](types-core.md), [types-chains](types-chains.md), and [Keystore](../Node_Platform_Services/keystore.md)) — rely on the same strict-decode behavior when serializing binary fields, keeping "plain hex" and "0x-prefixed hex" conventions consistent across module boundaries.
- **Encoding pipelines** that need richer struct-mapping should use the dedicated [codec](codec.md) module instead; `utils-hex` intentionally covers only flat byte-slice ↔ hex-string conversion.

```mermaid
flowchart LR
    subgraph consumers["Typical consumers"]
        JSON["JSON REST/GraphQL APIs"]
        TOML["TOML config binding"]
        KEYS["Keystore &amp; key bundles"]
        CHAINS["Chain adapters / relayers"]
    end

    subgraph hexmod["utils-hex"]
        A["PlainHexBytes<br/>(TextMarshaler / TextUnmarshaler / json.Unmarshaler)"]
        B["0x-prefix helpers<br/>EnsurePrefix / TrimPrefix / HasPrefix"]
        C["DecodeString / ParseBig"]
    end

    JSON -->|"field type"| A
    TOML -->|"TextUnmarshaler"| A
    KEYS -->|"encode/decode key bytes"| A
    CHAINS -->|"external 0x-hex strings"| B
    CHAINS -->|"numeric &amp; payload decoding"| C
```

---

## 6. Testing

The module is validated by exhaustive, table-driven tests in `plainhex_test.go`. The two core test fixtures are:

```go
type marshalTest struct {
    input any    // typically []byte
    want  string // expected hex (without JSON quotes)
}

type unmarshalTest struct {
    input   string // raw JSON token
    want    any    // expected []byte (when valid)
    wantErr string // exact expected error string ("" when valid)
}
```

Two data tables drive the suite:

- `unmarshalBytesTests` — covers invalid encodings (empty input, `null`, non-hex characters like `n`/`x`/`X`/`z`, odd length) and valid encodings (`""`, `"02"`, long strings).
- `encodeBytesTests` — covers marshaling edge cases (`[]byte{}` → `""`, `[]byte{0}` → `"00"`, multi-byte values).

```mermaid
flowchart TD
    START["go test ./pkg/utils/hex/..."] --> TU["TestUnmarshalBytes"]
    START --> TM["TestMarshalBytes"]

    TU --> L1{"for each entry in<br/>unmarshalBytesTests"}
    L1 --> A1["json.Unmarshal into hex.PlainHexBytes"]
    A1 --> A2{"error expected?<br/>(wantErr != '')"}
    A2 -->|"yes"| A3["checkError(): compare<br/>exact error string"]
    A2 -->|"no"| A4["bytes.Equal(result, want)"]
    A3 --> L1
    A4 --> L1

    TM --> L2{"for each entry in<br/>encodeBytesTests"}
    L2 --> B1["json.Marshal(hex.PlainHexBytes(in))"]
    B1 --> B2["assert output is quoted hex:<br/>'&quot;' + want + '&quot;'"]
    B2 --> B3["assert String() == want"]
    B3 --> L2

    A3 & A4 & B2 & B3 --> REPORT["Failures report input,<br/>got, and want values"]
```

Supporting helpers:

- `referenceBytes(s)` — decodes a reference hex literal via `encoding/hex.DecodeString`, panicking on programmer error (expected never to fail for valid test fixtures).
- `checkError(t, input, got, want)` — asserts the *exact* error string (both absence and presence are validated), which pins the wrapping conventions (`UnmarshalJSON failed: UnmarshalText failed: …`) as part of the public contract.

Tests run with plain `go test` inside the `chainlink-common` module; repo-wide linting for the module is provided by the `lint` / `lint-workspace` targets in `chainlink-common/Makefile` (backed by `script/lint.sh` and golangci-lint). API browsing is available via the `docs` target (`go doc -http`).

---

## 7. Related Documentation

- [Shared Foundation Libraries & Domain Types](../Shared_Foundation_Libraries___Domain_Types.md) — parent module group containing this package.
- [codec](codec.md) — full struct-level binary encoding/decoding pipeline (modifiers, builders, gRPC service); use for structured on-chain data rather than flat hex strings.
- [values](values.md) — the `values` package for chain-agnostic value wrapping.
- [types-core](types-core.md) / [types-chains](types-chains.md) — domain types whose binary fields typically serialize with the conventions defined here.
- [Keystore](../Node_Platform_Services/keystore.md) — a major consumer of strict hex handling for key material.
- [Core Shared Utilities](../Node_Application_Core___Interfaces/core_shared_utilities.md) — node-local utility packages (e.g. `abihelpers`) that operate at the layer above raw hex conversion.
- [Config Validation](config-validation.md) — validation patterns for configuration, including hex-typed fields bound from TOML/JSON.
