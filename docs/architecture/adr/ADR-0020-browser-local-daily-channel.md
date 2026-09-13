# ADR-0020 — Canal browser-local para Daily SIG Systems

- **Estado**: Aceptado
- **Fecha**: 2026-09-13
- **Requisitos**: NFR-Seg-7, NFR-Core-2

## Contexto

El named pipe autenticado y `watcher://` resuelven el canal interno
Tauri/WebView2 ↔ daemon (ADR-0009/ADR-0011), pero no son protocolos que un
navegador normal pueda usar. Daily SIG Systems necesita mostrar clips y preview
de la estación **del mismo navegador**, sin publicar el daemon a la LAN ni
convertir el router IPC en una API web.

El spike documentado en
[`daily-sig-systems-daemon-spike.md`](../../research/daily-sig-systems-daemon-spike.md)
confirmó que el daemon anterior no tenía HTTP(S), WSS, TLS ni una UI de
navegador apta para iframe.

## Decisión

Se agrega `adapters/browser_local/`, un segundo adaptador de entrada de
**solo lectura** sobre `core/api.ApiLayer`, con estas invariantes:

1. Sólo se construye para el daemon de rol Operator y sólo arranca con
   `BROWSER_LOCAL_ENABLED=true`.
2. Escucha TLS en `127.0.0.1` y `::1`, puerto fijo `8765`; no existe una
   configuración que abra una interfaz LAN.
3. Sirve una UI HTML/JS propia en `/embed`; no importa Tauri, `src/lib/ipc.ts`,
   eventos nativos ni `watcher://`.
4. Expone únicamente health, firma de bootstrap, listado de clips/monitores,
   media/preview con capabilities opacas y WSS `/events`. No expone
   `IpcRouter`, rutas absolutas, configuración, grabación, exportación ni roles.
5. La UI hija emite `Content-Security-Policy` con
   `frame-ancestors https://daily.sig.systems`, `Referrer-Policy: no-referrer`
   y nunca `X-Frame-Options: DENY|SAMEORIGIN`.
6. SIGDailyReport enrola por instalación un `device_id`, clave pública Ed25519,
   sitio y estado. La clave privada local queda bajo LocalAppData con ACL del
   usuario. La Edge Function firma una assertion Ed25519 de 60 s, un solo uso;
   Watcher verifica firma, `iss`, `aud`, dispositivo, sitio, scopes, tiempo y
   replay antes de crear una sesión de memoria de 5 min.
7. La assertion viaja exclusivamente por `postMessage` con `targetOrigin`
   exacto. El WebSocket autentica en su primer mensaje. El `Origin` de ese WSS
   es `https://localhost:8765` porque el código que abre el socket vive dentro
   del iframe local, no en la página Daily.

## Consecuencias

- El pipe Tauri mantiene su ACL y contrato actual; el navegador no puede
  alcanzar sus comandos privilegiados.
- Se incorpora `aiohttp` y PyJWT/cryptography al entorno Python, además de
  certificado mkcert y clave pública del emisor como configuración local.
- Los URLs de media son capabilities efímeras (30 s), vinculadas a una sesión y
  a un archivo permitido; `FileResponse` conserva Range sin filtrar paths.
- El deploy de Daily pasa a ser parte de la seguridad: su CSP debe permitir
  `frame-src https://localhost:8765` y la Edge Function requiere secretos.
- El enfoque depende de que Chrome/Edge confíen en la CA local y acepten la
  navegación pública → loopback. Se debe validar en la política administrada
  de cada flota; una falla muestra degradación explícita, no fallback HTTP.
- Hay dos superficies UI que mantener (Tauri y browser-local), deliberadamente
  separadas para impedir que una API de escritorio privilegiada se vuelva web.

## Opciones no elegidas

- Reutilizar `IpcRouter` o el build React/Tauri: requiere named pipes/Tauri y
  `watcher://`, imposibles para un navegador ordinario y demasiado privilegiados.
- Reusar el preview MJPEG actual: es HTTP, no tiene TLS, sesión ni `frame-ancestors`.
- Abrir HTTP/WS en LAN o usar el firewall como control: amplía la superficie y
  no satisface el requisito de acceso desde la misma estación.
- Pasar assertions en query string, cookie compartida o subprotocol: deja
  secretos en historial/logs o aumenta el acoplamiento cross-origin.
