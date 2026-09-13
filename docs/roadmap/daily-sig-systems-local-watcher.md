# Roadmap — contenedor Daily SIG Systems para The Watcher

Estado: implementación base completada el 2026-09-13; liberación bloqueada
intencionalmente hasta configurar Daily (CSP, Edge Function, enrolamiento) y
validar el piloto en navegadores administrados.

## Resultado y frontera

Daily muestra un iframe `https://localhost:8765/embed` desde la página
autenticada `https://daily.sig.systems`. El daemon Operator entrega clips y
preview de **esa estación**. No se abre una ruta LAN y no cambia el pipe
Tauri/WebView2 de ADR-0009/0011.

```text
Daily (usuario autenticado)                         Daemon Operator local
──────────────────────────                         ──────────────────────
WatcherPage ─ iframe / postMessage ──────────────> /embed (UI navegador)
       └─ Edge Function: assertion Ed25519 ───────> WSS /events (sesión RAM)
                                                    └─ /api/v1/clips
                                                       /media/<cap> [Range]
                                                       /preview/<cap>
```

El iframe se ejecuta bajo `https://localhost:8765`, por ello su WSS lleva ese
`Origin`; el padre Daily no abre el socket directamente. `frame-ancestors` es
la política del hijo. El despliegue de Daily debe añadir la política inversa
del padre: `frame-src https://localhost:8765`.

## Fase 1 — daemon y enrolamiento (implementada)

- [x] ADR-0020 y adaptador `browser_local` separado de `adapters/ipc`.
- [x] HTTPS/WSS `aiohttp`, bind exclusivo `127.0.0.1` y `::1`, puerto 8765,
  activo únicamente para Operator con feature flag.
- [x] UI web de navegador independiente de Tauri; endpoints de lectura
  limitados y allowlist de directorios compuesta en `main.py`.
- [x] Identidad Ed25519 por instalación en
  `%LOCALAPPDATA%\The Watcher\browser_local\device_identity.json`, con intento
  de ACL privada. `Start-TheWatcher.ps1 -EnrollBrowserLocal` imprime sólo
  `device_id` y clave pública.
- [x] `Start-TheWatcher.ps1 -SetupBrowserLocalTls` crea un certificado mkcert
  para `localhost`, `127.0.0.1` y `::1`, fuera del repositorio.
- [x] Assertions EdDSA con validación de issuer, audience, dispositivo, sitio,
  scopes, tiempo, `jti` de un uso; sesión RAM 5 min y capabilities 30 s.
- [x] CSP `frame-ancestors https://daily.sig.systems`, sin X-Frame-Options,
  `Referrer-Policy: no-referrer`, Range para MP4 y logs con sujeto seudonimizado.

Configuración mínima local, entregada por gestión de endpoint y nunca en git:

```dotenv
BROWSER_LOCAL_ENABLED=true
BROWSER_LOCAL_PARENT_ORIGIN=https://daily.sig.systems
BROWSER_LOCAL_ISSUER=daily.sig.systems
BROWSER_LOCAL_AUDIENCE=the-watcher-local
BROWSER_LOCAL_ISSUER_KID=watcher-ed25519-2026-01
BROWSER_LOCAL_SITE_ID=<site id enrolado>
BROWSER_LOCAL_CERT_FILE=%LOCALAPPDATA%\The Watcher\browser_local\localhost.pem
BROWSER_LOCAL_KEY_FILE=%LOCALAPPDATA%\The Watcher\browser_local\localhost-key.pem
BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE=%LOCALAPPDATA%\The Watcher\browser_local\daily-issuer-public.pem
```

La clave pública del emisor puede distribuirse; su privada se queda sólo como
secreto de la Edge Function. Si falta certificado, key, sitio o clave pública,
el listener falla cerrado y la grabación sigue funcionando.

## Fase 2 — Daily SIG Systems (implementada en el repo hermano)

- [x] Migración `040_watcher_local_browser.sql`: catálogo de permisos,
  `watcher_devices`, auditoría y RPCs de gestión. Ver es para todos los roles;
  gestionar es sólo admin y lead supervisor.
- [x] Edge Function `issue-watcher-session`: verifica usuario Supabase,
  permiso efectivo, dispositivo activo y proof Ed25519; firma assertion de
  60 s con clave privada de secreto y audita sin token/capability.
- [x] `WatcherPage` bajo Operación con feature flag, iframe, estados de
  daemon/certificado/enrolamiento y puente `postMessage` de origen exacto.
- [x] Panel mínimo de admin/lead para enrolar, asignar sitio, activar y revocar.
- [x] Pruebas Vitest del parser de mensajes y nonce.

Pendiente de la persona/equipo que despliega Daily:

- [ ] Aplicar la migración y desplegar la Edge Function.
- [ ] Definir los secretos y distribuir la clave pública PEM a Watcher.
- [ ] Modificar la CSP del **host de producción**, no Vite, para conservar las
  directivas existentes y añadir `frame-src https://localhost:8765`.
- [ ] Activar `VITE_WATCHER_LOCAL_ENABLED=true` sólo en el build piloto.

## Contrato de seguridad

1. El hijo carga `/api/v1/health` y manda
   `{type:'watcher:ready', device_id}` al padre Daily con origen exacto.
2. El padre crea nonce aleatorio y manda
   `{type:'watcher:challenge', device_id, nonce}` al iframe local.
3. El hijo pide al daemon firmar el nonce y devuelve `watcher:proof`.
4. La Edge Function verifica el proof contra la clave pública enrolada y emite
   JWT con `iss`, `aud=the-watcher-local`, `sub`, `device_id`, `site_id`,
   `scope`, `nonce`, `jti`, `iat`, `nbf`, `exp` (60 s).
5. Daily manda `{type:'watcher:session', assertion}` con target local exacto.
   La UI abre WSS, manda assertion como primer mensaje y renueva a los 4 min.

Los mensajes se validan por `origin`, `source`, tipo y forma. Assertion y
capabilities nunca se ponen en query string, log, almacenamiento local ni
variables `VITE_`.

## Gate de piloto y rollback

Antes de habilitar un dispositivo, ejecutar:

```powershell
$env:PYTHONPATH = 'project'
$twPython = Join-Path $env:LOCALAPPDATA 'The Watcher\venv\Scripts\python.exe'
& $twPython -m pytest project/tests/test_browser_local_adapter.py -q
npm test
Push-Location src-tauri; cargo check; Pop-Location
```

En Chrome y Edge administrados, probar iframe desde el dominio productivo,
clips MP4 con seek/Range, preview, renovación a los 4 min, certificado ausente,
dispositivo revocado, assertion vencida/repetida y origen incorrecto. Vigilar
los logs locales `[browser-local]` y `watcher_session_audit` sin capturar
assertions/capabilities.

Rollback: apagar el flag de Daily, denegar `watcher.recordings.view` o revocar
el dispositivo. El Edge Function no emite nuevas assertions; las sesiones
locales expiran como máximo en cinco minutos. No borrar clips, certificados ni
la identidad del dispositivo salvo un procedimiento de decommission explícito.
