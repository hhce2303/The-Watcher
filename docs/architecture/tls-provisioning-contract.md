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
  operator-deployment.env      # LIVE_VIEW_* / BROWSER_LOCAL_* incl. the *_FILE paths below
  certs/
    <any files referenced by *_FILE=certs\...>
    trust/*.pem                # optional, public CAs only
```

Private keys never enter the repo or an installer beyond the station's own leaf key.
The CA private key stays with the provisioning service.

Evolution: [ADR-0023](adr/ADR-0023-external-tls-provisioning-service.md) defines a runtime CSR-based, issue-once service behind a `TlsMaterialPort`; this file contract stays as the `file` mode.
