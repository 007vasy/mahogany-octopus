# TEE Attestation — Nitro Validation

> **Module**: `chainlink-common/pkg/teeattestation/nitro/validate.go`
> **Part of**: [Shared Foundation Libraries & Domain Types](../../Shared_Foundation_Libraries___Domain_Types.md) → [TEE Attestation](../tee-attestation.md)

## 1. Introduction

The **Nitro validation module** provides the public, policy-level API for validating **AWS Nitro Enclave attestation documents**. An attestation document is a COSE `Sign1`-signed structure produced by the Nitro hypervisor that proves *which enclave image is running* (via Platform Configuration Registers, PCRs) and *who signed it* (a certificate chain rooted in the AWS Nitro Enclaves CA).

This module answers the question a verifier cares about:

> *"Is this attestation genuine, fresh, produced by the enclave image I expect, and bound to the user data I sent?"*

It does so by layering **application-level validation policy** (this file — user-data binding, trusted PCR pinning, result parsing) on top of **low-level cryptographic verification** (the sibling [Nitro Verification](tee-attestation_nitro-verification.md) module — COSE/CBOR parsing, certificate chain validation, ES384/P-384 signature checks).

Within the broader system, this package is the trust anchor for workflows and components that operate inside (or talk to) Trusted Execution Environments — e.g. TEE-backed workflow execution in the [CRE engine](../../Workflow___Capability_Runtime_(CRE_Engine)/workflows/workflows_engine.md), where peers must prove their enclave identity and image integrity before being trusted.

---

## 2. Architecture

### 2.1 Layered design

```
┌─────────────────────────────────────────────────────────────────┐
│  validate.go (this module) — PUBLIC VALIDATION API               │
│  • nil/input guards          • user-data binding                │
│  • CA root selection         • trusted PCR0/1/2 pinning         │
│  • JSON decoding of PCRs     • parsed *Document result          │
└──────────────────────────────┬──────────────────────────────────┘
                               │ verifyAttestationDocument(...)
┌──────────────────────────────▼──────────────────────────────────┐
│  verify.go (nitro-verification module) — CRYPTO VERIFICATION     │
│  • COSE_Sign1 / CBOR decode  • payload shape validation         │
│  • certificate chain parse   • timestamp freshness              │
│  • x509 chain verify         • ES384 (P-384) signature verify   │
└─────────────────────────────────────────────────────────────────┘
```

All four exported entry points collapse into one core implementation, `ValidateAndParseWithRoots`, which distinguishes callers only by (a) whether they want the parsed result and (b) which CA root certificate is trusted.

### 2.2 Component relationship diagram

```mermaid
flowchart TB
    subgraph consumers["Consumers: node runtime &amp; TEE-capable engine components"]
        CALLER["Caller holding: attestation document,<br/>expected user data, trusted PCR measurements"]
    end

    subgraph nitroPkg["package nitro — chainlink-common/pkg/teeattestation/nitro"]
        subgraph validateLayer["validate.go — public validation API (this module)"]
            VA["ValidateAttestation"]
            VAWR["ValidateAttestationWithRoots"]
            VAP["ValidateAndParse"]
            CORE["ValidateAndParseWithRoots<br/>(core implementation)"]
            ROOTS["DefaultCARoots<br/>(AWS Nitro root CA PEM)"]
            TYPES["HexBytes / PCRs / Document"]
        end
        subgraph verifyLayer["verify.go — low-level verification (nitro-verification module)"]
            VAD["verifyAttestationDocument"]
            PAYLOAD["validateAttestationPayload"]
            CHAIN["parseCertificateChain"]
            SIG["verifyECDSASignature + hashForCurve"]
        end
    end

    subgraph externals["External / standard library"]
        CBOR["fxamacker/cbor/v2<br/>(COSE_Sign1 / CBOR decode)"]
        X509["crypto/x509<br/>(chain verification)"]
        ECDSA["crypto/ecdsa + crypto/sha512<br/>(ES384 / P-384 signature)"]
        AWSCA["AWS Nitro Enclaves Root CA"]
    end

    CALLER --> VA
    CALLER --> VAP
    VA --> VAP
    VAWR --> CORE
    VAP --> CORE
    ROOTS --> CORE
    CORE --> VAD
    CORE --> TYPES
    VAD --> PAYLOAD
    VAD --> CHAIN
    VAD --> SIG
    VAD --> CBOR
    CHAIN --> X509
    SIG --> ECDSA
    X509 -. trust anchor .-> AWSCA
```

**External dependencies** (see `chainlink-common/go.mod`): `github.com/fxamacker/cbor/v2` for COSE/CBOR decoding; everything else is Go standard library (`crypto/x509`, `crypto/ecdsa`, `crypto/sha512`, `encoding/json`, `encoding/hex`).

---

## 3. Public API Reference

### 3.1 Validation functions

All functions are pure (stateless, no goroutines or shared state) and **fail closed** — any failure returns a non-nil error and (where applicable) a `nil` document.

| Function | Returns | Trusted root | Intended use |
|---|---|---|---|
| `ValidateAttestation(attestation, expectedUserData, trustedMeasurements []byte) error` | `error` only | `DefaultCARoots` (AWS) | Production validation when the parsed result is not needed |
| `ValidateAttestationWithRoots(attestation, expectedUserData, trustedMeasurements []byte, caRootsPEM string) error` | `error` only | Custom PEM | Testing with fake enclaves that use self-signed CA roots |
| `ValidateAndParse(attestation, expectedUserData, trustedMeasurements []byte) (*Document, error)` | `*Document` | `DefaultCARoots` (AWS) | Production validation + identity binding / freshness checks |
| `ValidateAndParseWithRoots(attestation, expectedUserData, trustedMeasurements []byte, caRootsPEM string) (*Document, error)` | `*Document` | Custom PEM | Core implementation; testing with fake enclaves |

The wrapper relationships are strict delegation:

```mermaid
flowchart LR
    VA["ValidateAttestation"] --> VAP["ValidateAndParse"]
    VAP --> CORE["ValidateAndParseWithRoots<br/>(DefaultCARoots)"]
    VAWR["ValidateAttestationWithRoots"] --> CORE
    CORE --> CORE2["validate.go policy checks<br/>+ verify.go crypto verification"]
```

> ⚠️ `ValidateAttestationWithRoots` / `ValidateAndParseWithRoots` exist **primarily for testing** with fake enclaves signed by self-signed roots. Production code should use the AWS-root variants unless it deliberately operates in a private enclave fleet with its own CA.

### 3.2 Types

| Type | Kind | Purpose |
|---|---|---|
| `HexBytes` | `[]byte` with custom JSON codec | Decodes AWS Nitro measurements, which are **hex strings in JSON**, into raw bytes (`UnmarshalJSON`), and re-encodes bytes to hex on marshal. Keeps `trustedMeasurements` parsing symmetrical with the wire format. |
| `PCRs` | struct (`PCR0`, `PCR1`, `PCR2 HexBytes`, JSON tags `pcr0/pcr1/pcr2`) | The **trusted measurement set** a verifier pins an enclave image to. Decoded from JSON via `HexBytes`. |
| `Document` | struct | The **validated, parsed attestation fields** returned only after the full validation chain has passed. See [Data model](#5-data-model). |
| `DefaultCARoots` | `const string` | PEM of the AWS Nitro Enclaves root certificate (sourced from `https://aws-nitro-enclaves.amazonaws.com/AWS_NitroEnclaves_Root-G1.zip`). |

**Trusted measurements JSON format** (decoded by `HexBytes`):

```json
{
  "pcr0": "e2af3e01...ff",
  "pcr1": "9c5b2aff...11",
  "pcr2": "11d4c93a...72"
}
```

---

## 4. Validation Pipeline

### 4.1 End-to-end sequence

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant V as ValidateAndParse(WithRoots)
    participant R as verifyAttestationDocument<br/>(verify.go)
    participant AWS as AWS Nitro Root CA

    C->>V: attestation, expectedUserData,<br/>trustedMeasurements (JSON PCRs), caRootsPEM
    V->>V: reject nil attestation
    V->>V: build x509 CertPool from CA PEM<br/>(DefaultCARoots or custom)
    V->>R: verifyAttestationDocument(data, pool, time.Now())
    Note over R: CBOR-decode COSE_Sign1<br/>validate protected header algorithm (ES384)
    Note over R: validateAttestationPayload:<br/>mandatory fields, SHA384 digest,<br/>PCR cardinality 1..32, size bounds
    Note over R: parseCertificateChain:<br/>leaf must be ECDSA / ECDSA-SHA384<br/>CA bundle becomes intermediates pool
    Note over R: freshness: timestamp skew vs<br/>maxAttestationAge (both directions)
    R->>AWS: leafCert.Verify(roots, intermediates, now)
    AWS-->>R: chain valid
    Note over R: rebuild COSE Sig_structure,<br/>P-384 ECDSA verify, marshal leaf SPKI
    R-->>V: verifyResult{document, signatureOK, leafPublicKey}
    V->>V: enforce signatureOK (defense in depth)
    V->>V: bytes.Equal(expectedUserData, doc.UserData)
    V->>V: JSON-decode trustedMeasurements into PCRs<br/>(HexBytes: hex string to bytes)
    V->>V: require at least 3 PCRs present
    V->>V: compare PCR0, PCR1, PCR2 with trusted values
    V-->>C: *Document{PCRs, LeafPublicKey, PublicKey,<br/>UserData, Nonce, ModuleID}
```

Steps 1–12 (up to and including the signature result) are performed by the [nitro-verification module](tee-attestation_nitro-verification.md); steps 13–18 are the **policy layer owned by this module**.

### 4.2 Decision gates (this module)

```mermaid
flowchart TD
    A["attestation bytes"] --> B{"attestation == nil?"}
    B -- "yes" --> E1["error: attestation is nil"]
    B -- "no" --> C["parse CA roots PEM into x509 pool"]
    C --> C2{"PEM parse OK?"}
    C2 -- "no" --> E2["error: failed to parse CA roots"]
    C2 -- "yes" --> D["verifyAttestationDocument:<br/>CBOR + payload + chain + freshness + signature"]
    D --> D2{"err == nil?"}
    D2 -- "no" --> E3["error: failed to verify nitro attestation<br/>(wraps underlying verification failure)"]
    D2 -- "yes" --> S{"signatureOK flag?"}
    S -- "no" --> E4["error: signature verification failed"]
    S -- "yes" --> U{"UserData == expectedUserData?"}
    U -- "no" --> E5["error: expected user data X, got Y"]
    U -- "yes" --> T["unmarshal trustedMeasurements into PCRs"]
    T --> T2{"JSON + hex decode OK?"}
    T2 -- "no" --> E6["error: failed to unmarshal trusted PCRs"]
    T2 -- "yes" --> P{"at least 3 PCRs in document?"}
    P -- "no" --> E7["error: attestation document has N PCRs, need at least 3"]
    P -- "yes" --> Q{"PCR0 / PCR1 / PCR2 equal trusted values?"}
    Q -- "no" --> E8["error: PCRn mismatch: expected ..."]
    Q -- "yes" --> OK["return *Document"]
```

**Gate semantics:**

1. **Input guard** — a nil attestation is rejected immediately.
2. **Root selection** — the caller-supplied PEM (or `DefaultCARoots`) is compiled into an `x509.CertPool`; a malformed PEM fails fast.
3. **Cryptographic verification** — delegated wholesale to `verifyAttestationDocument`; any error is wrapped with `"failed to verify nitro attestation: ..."`. The `signatureOK` result flag is additionally re-checked as defense in depth.
4. **User-data binding** — the attestation's `user_data` field must be byte-identical to `expectedUserData`. This is how the verifier binds the attestation to *this specific interaction* (e.g. an expected workload descriptor or request hash).
5. **Trusted PCR pinning** — `trustedMeasurements` JSON is decoded into a `PCRs` struct; the document must expose at least 3 PCRs and **PCR0, PCR1 and PCR2 must match exactly** (`bytes.Equal` on hex-decoded values). These are the canonical build-time measurements of the enclave (image / kernel-bootstrap / application; exact semantics are defined by the enclave build pipeline that produced the measurements).

---

## 5. Data model

```mermaid
classDiagram
    class HexBytes {
        <<custom JSON codec>>
        +UnmarshalJSON(b) error
        +MarshalJSON() array
    }
    class PCRs {
        +PCR0 HexBytes
        +PCR1 HexBytes
        +PCR2 HexBytes
    }
    class Document {
        +PCRs - all PCRs keyed by index
        +LeafPublicKey - SPKI DER of leaf cert key
        +PublicKey - enclave-supplied identity key
        +UserData - verified against expected
        +Nonce - NOT auto-checked
        +ModuleID - attestation module_id
    }
    PCRs ..> HexBytes : fields are hex-decoded via
    Document ..> PCRs : PCR0/1/2 verified against trusted
```

### `Document` field semantics and caller guidance

| Field | Type | Semantics | Caller guidance |
|---|---|---|---|
| `PCRs` | `map[uint][]byte` | Every platform configuration register present in the attestation, keyed by index. PCR0/1/2 have already been checked against trusted measurements. | Higher PCRs (e.g. 3, 4, 8) are **exposed unchecked** — apply your own policy before trusting them. |
| `LeafPublicKey` | `[]byte` (SPKI DER) | Public key of the attestation's end-entity certificate. AWS rotates this certificate **per enclave instance (~every few hours)**. | Not a stable identity anchor on its own. Useful for correlating attestations within a short window. |
| `PublicKey` | `[]byte` | The enclave-supplied `public_key` field (nil if unset) — a **long-lived identity key generated inside the TEE**. | Preferred stable handle for binding an attestation to a specific enclave identity across restarts/certificate rotation. |
| `UserData` | `[]byte` | The attestation `user_data` field; already verified equal to `expectedUserData`. | Safe to treat as the verified request/context binding. |
| `Nonce` | `[]byte` | The attestation `nonce` field (nil if unset). **`ValidateAndParse` does NOT check it.** | For replay protection, compare it yourself against a freshly generated challenge you supplied to the enclave. |
| `ModuleID` | `string` | The attestation `module_id` field. | Informational; useful in logs/policy. |

### Trust chain overview

```mermaid
flowchart LR
    AWSROOT["AWS Nitro Root CA<br/>(DefaultCARoots)"] --> LEAFCERT["End-entity certificate<br/>(rotated per enclave instance,<br/>~hours)"]
    LEAFCERT -- "signs COSE_Sign1" --> DOC["Attestation document:<br/>PCRs, PublicKey, UserData,<br/>Nonce, ModuleID, Timestamp"]
    ENCLAVE["Enclave build pipeline"] -- "defines" --> PCR["Trusted PCR0/1/2<br/>(trustedMeasurements JSON)"]
    VERIFIER["Verifier (this module)"] -- "pins" --> PCR
    VERIFIER -- "validates" --> DOC
    VERIFIER -- "trusts" --> AWSROOT
```

---

## 6. Usage

### 6.1 Validate only (production)

```go
import nitro "github.com/smartcontractkit/chainlink-common/pkg/teeattestation/nitro"

// trustedMeasurements is the JSON document pinning PCR0/1/2 for the
// expected enclave image.
if err := nitro.ValidateAttestation(attestation, expectedUserData, trustedMeasurements); err != nil {
    // reject: untrusted attestation
}
```

### 6.2 Validate and bind identity + freshness

```go
doc, err := nitro.ValidateAndParse(attestation, expectedUserData, trustedMeasurements)
if err != nil {
    // reject
}

// Replay protection: the validator does NOT check Nonce — the caller must
// compare it against the fresh challenge it sent to the enclave.
if !bytes.Equal(doc.Nonce, issuedChallenge) {
    // replay attempt
}

// Stable identity: prefer the enclave-generated key over the rotating
// per-instance certificate key.
identity := doc.PublicKey      // long-lived (enclave-generated)
// doc.LeafPublicKey           // short-lived (rotated certificate key)
```

### 6.3 Testing with fake enclaves

```go
// Fake enclave signs attestations with a self-signed root:
err := nitro.ValidateAttestationWithRoots(att, wantUserData, trustedPCRs, fakeCAPEM)

doc, err := nitro.ValidateAndParseWithRoots(att, wantUserData, trustedPCRs, fakeCAPEM)
```

---

## 7. Security Model

**Guarantees provided (fail-closed):**

- **Authenticity** — COSE signature verified with ES384 (P-384 / SHA-384) against a leaf certificate that chains to the trusted root (AWS by default).
- **Integrity & shape** — payload structure, mandatory fields, digest algorithm (`SHA384`), PCR cardinality (1–32) and value sizes (32/48/64 bytes), and field size caps (≤1024 bytes for key/user-data/nonce; ≤1024 per CA-bundle item) are enforced by the verification layer.
- **Freshness** — the attestation timestamp (epoch milliseconds) must fall within `maxAttestationAge` of `time.Now()` in both directions (stale and far-future attestations are rejected).
- **Workload pinning** — PCR0/PCR1/PCR2 must byte-match the trusted measurements, binding the attestation to a specific enclave image build.
- **Context binding** — `user_data` must byte-match the caller's expected value.

**Explicit non-guarantees (caller responsibilities):**

| Concern | Status | Mitigation |
|---|---|---|
| Replay protection | `Nonce` is **returned, not checked** | Caller generates a fresh challenge, delivers it to the enclave (e.g. via `user_data` or `nonce`), and compares `doc.Nonce` |
| Long-term identity | `LeafPublicKey` rotates (~hours) | Bind to `Document.PublicKey` (enclave-generated key) |
| PCRs beyond 0–2 | Exposed in `Document.PCRs` **unchecked** | Apply caller-side policy before trusting higher PCRs |
| Custom roots in production | `*WithRoots` variants accept any PEM | Restrict custom-root calls to test builds / private enclave fleets with their own CA |

**Note on time:** the verifier pins `time.Now()` at call time; there is no injectable clock in this module, so testability of freshness windows is achieved via the custom-roots + fake-attestation path.

---

## 8. Dependencies

| Dependency | Used for | Source |
|---|---|---|
| `github.com/fxamacker/cbor/v2` | CBOR decoding of COSE `Sign1` structures and attestation payload | `chainlink-common/go.mod` |
| `crypto/x509`, `crypto/ecdsa`, `crypto/sha512` | Certificate chain verification, P-384 ECDSA signature verification | Go standard library |
| `encoding/json`, `encoding/hex` | `HexBytes` codec for trusted measurements | Go standard library |

---

## 9. Related Documentation

- **[Nitro Verification](tee-attestation_nitro-verification.md)** — the low-level cryptographic verification layer (`verify.go`) this module delegates to: COSE parsing, payload validation, certificate chain handling, ES384 signatures, freshness enforcement.
- **[TEE Attestation](../tee-attestation.md)** — parent module overview.
- **[Shared Foundation Libraries & Domain Types](../../Shared_Foundation_Libraries___Domain_Types.md)** — the foundation layer this package belongs to.
- **[CRE Workflow Engine](../../Workflow___Capability_Runtime_(CRE_Engine)/workflows/workflows_engine.md)** — the workflow runtime whose TEE-backed execution this attestation mechanism helps secure (the CRE TypeScript SDK exposes a corresponding `TeeRuntime`).
