# Deploy del daemon Operador — runbook de campo

Este runbook cubre el despliegue de The Watcher en modo daemon (rol Operador) a una máquina
nueva, usando el paquete headless PyInstaller (`installer/build.ps1`). No incluye la UI Tauri
(diferida — ver CLAUDE.md, sección "Tauri Migration").

## 1. Preparar el `.env` del sitio

Copia `.env.example` a `site.env` y ajusta al menos:

- `IT_PIN` — cambiar el default `1234`.
- `NAS_USERNAME` / `NAS_PASSWORD` si la estación necesita autenticarse contra
  `SLC_STORAGE_HOST` explícitamente.
- `RETENTION_HOURS`, `SEGMENT_DIR`, `CLIPS_DIR` si el sitio usa una unidad distinta a
  `C:\WatcherData`.

No es necesario tocar las variables `BROWSER_LOCAL_*` — el paso 3 las completa automáticamente
para las que dependen de esta máquina (certificado, identidad). Tampoco es necesario tocar
`SLC_STORAGE_HOST` — el instalador la pregunta interactivamente (paso 3).

## 2. Copiar el paquete a la máquina destino

Copia `dist\The Watcher\` completo (o el ZIP) más tu `site.env` (renombrado exactamente
`site.env`, en la misma carpeta que `Setup.bat`) a la máquina — USB, carpeta compartida, etc.

## 3. Ejecutar

Doble clic en `Setup.bat`. Si detecta `site.env`, instala en modo desatendido:

1. Copia los archivos a `%LOCALAPPDATA%\The Watcher`.
2. Pre-siembra `user_config.json` con `role: "operator"`.
3. Copia `site.env` como `.env`.
4. **Pregunta la ruta UNC del NAS** donde quedarán las grabaciones accesibles para IT/
   Supervisor (`SLC_STORAGE_HOST`, default `\\SIG-SLC-Storage`) y la escribe en `.env`. Es la
   única pregunta que sobrevive al modo desatendido — se puede saltar pasando
   `-SlcStorageHost <ruta>` a `install.ps1` en despliegues masivos scripteados.
5. Corre `The Watcher Enroll.exe`: genera/lee el certificado TLS loopback (mkcert) y la
   identidad Ed25519 del dispositivo, y parchea `.env` con las rutas resultantes.
6. Imprime en la misma consola el bloque de enrollment:

   ```json
   {
     "device_id": "...",
     "public_key_pem": "-----BEGIN PUBLIC KEY-----...",
     "certificate_fingerprint_sha256": "AA:BB:...",
     "certificate_file": "C:\\Users\\...\\browser_local\\localhost.pem"
   }
   ```

7. Lanza `The Watcher.exe --daemon`.

## 4. Enrolar en Daily SIG Systems

Copia el `device_id` y el `public_key_pem` impresos en el paso anterior al panel admin de
SIGDailyReport (ver ADR-0020). Cuando Daily asigne un `station_id` y publique su clave pública
de emisor, vuelve a correr en la máquina destino:

```powershell
& "$env:LOCALAPPDATA\The Watcher\The Watcher Enroll.exe" `
    --station-id <N> --issuer-kid <KID> `
    --issuer-public-key-file <ruta-a-daily-issuer-public.pem>
```

Esto escribe `BROWSER_LOCAL_STATION_ID`, `BROWSER_LOCAL_ISSUER_KID`,
`BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE` y `BROWSER_LOCAL_ENABLED=true` en el `.env` desplegado.
Reinicia el daemon (o espera al próximo watchdog restart) para que tome el cambio.

## 5. Verificar

```powershell
schtasks /Query /TN TheWatcher-OperatorWatchdog     # debe existir
Get-Content "$env:LOCALAPPDATA\The Watcher\user_config.json"   # role: "operator"
Get-Content "$env:LOCALAPPDATA\The Watcher\.env" | Select-String BROWSER_LOCAL
Get-Content "$env:LOCALAPPDATA\The Watcher\.env" | Select-String SLC_STORAGE_HOST
```

## Fuera de alcance

- Empaquetar la UI Tauri como `externalBin` del daemon (bloqueado: CI inexistente, firma
  minisign no configurada, `tauri-action` no wireado — ver
  `docs/migration/tech-debt-and-best-practices.md`).
- Enrollment de la identidad `live_view_lan` (ADR-0021, canal LAN para Supervisores) — misma
  mecánica pero con certificado de CA interna (no mkcert) y su propio `DeviceIdentityStore`.
- El instalador Inno Setup (`The Watcher.iss`) sigue siendo el camino manual/interactivo; el
  flujo desatendido de este runbook usa el ZIP + `Setup.bat`/`install.ps1`.
