# TLS provisioning contract

The Watcher does not issue, rotate or store the CA of any certificate. TLS material is
produced by an external provisioning service (repo `the-watcher-certs`) and consumed here
only as **files referenced by environment variables**. This repo contains no certificate
tooling, no key material and no CA names.

## What The Watcher consumes

1. **Runtime (daemon)** reads paths from `.env`: `LIVE_VIEW_CERT_FILE`, `LIVE_VIEW_KEY_FILE`,
   `LIVE_VIEW_ISSUER_PUBLIC_KEY_FILE`, `BROWSER_LOCAL_CERT_FILE`, `BROWSER_LOCAL_KEY_FILE`,
   `BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE` (`app/infrastructure/config.py`). Missing or unreadable
   files make the affected listener fail closed. TLS >= 1.2, served from
   `adapters/live_view_lan` and `adapters/browser_local`.
2. **Installer build** (`installer/build.ps1 -OperatorDeploymentConfig <bundle>/operator-deployment.env`)
   stages, byte for byte:
   - every file referenced by a `<NAME>_FILE=certs\...` line of the profile;
   - every `certs\trust\*.pem` in the bundle (public CA certificates).
3. **Install / update** (`The Watcher.iss`, `Update-Watcher.ps1`) add each `certs\trust\*.pem` to the
   current user's Root store. `Update-Watcher.ps1` never overwrites an existing `certs\`.

## Provisioning bundle (what the service must produce)

```
<bundle>/
  operator-deployment.env
  certs/
    <any files referenced by *_FILE=certs\...>
    trust/*.pem
```

Private keys never enter the repo or an installer beyond the station's own leaf key.
The CA private key stays with the provisioning service.

## `remote` mode: broker API (normative, ADR-0024)

`the-watcher-certs` exposes `POST /v1/certificates` only through its broker; step-ca is never reachable from a station. `browser_local` never calls this API.

The request JSON contains strings `version`, `audience`, `method`, `path`, `device_id`, `station_id`, `issued_at`, `nonce`, `idempotency_key`, `csr_der_b64`, and `signature`. The CSR is DER encoded as unpadded URL-safe base64. `version` is `v1`, `audience` is `the-watcher-certs`, `method` is `POST`, and `path` is `/v1/certificates`.

The signature uses the already-enrolled device Ed25519 key with domain `the-watcher-tls-issuance:v1:`. Its signed bytes are that domain prefix followed, in the listed field order excluding `signature`, by each UTF-8 field encoded as a 4-byte big-endian length and then the field bytes. The broker verifies this signature, derives SANs exclusively from Daily policy, and fails closed for unavailable/ambiguous policy.

A successful issue or exact idempotent retry returns `201` with `certificate_der_b64` and the server-derived `sans`. A nonce or idempotency key reused with different request content returns `409`; invalid input/signature returns `400`/`401`; disabled or mismatched stations return `403`; unavailable policy authority returns `503`. The daemon never receives a private key: it converts the returned DER leaf into its local PEM material and retains the private key generated for its CSR.

`GET /healthz` returns `200 {"status":"ok"}` only for liveness. It is never authorization evidence.

Evolution: [ADR-0023](adr/ADR-0023-external-tls-provisioning-service.md) defines the issue-once boundary; [ADR-0024](adr/ADR-0024-tls-issuance-governance.md) fixes the pilot governance and broker protocol.
