# ADR-0021 — Supervisión LAN autenticada para vistas en vivo

- **Estado**: Aceptado
- **Fecha**: 2026-09-13
- **Requisitos**: NFR-Seg-4, NFR-Seg-5

## Contexto

Daily SIG Systems ya autentica personas mediante `rpc_me` y `browser_local`
permite que un Operator vea su propia estación en loopback. Ninguno permite que
un Supervisor vea otro PC: el primero no informa salud del daemon y el segundo,
por diseño, solo escucha en `127.0.0.1`/`::1`.

El producto requiere un roster de PCs Operator con heartbeat operativo y una
vista de un monitor seleccionado a 8–10 fps en LAN. Supervisor, Lead
Supervisor y Admin pueden mirar; Operator no. La visualización es de solo
lectura y se limita a tres espectadores simultáneos por equipo.

## Decisión

1. Crear `live_view_lan`, separado de `browser_local`, `watcher://` y el pipe
   IPC. Solo inicia en daemon Operator, usa TLS de la CA interna y queda
   limitado por firewall a la LAN corporativa.
2. Reutilizar JPEG del recorder y distribuirlo como MJPEG, sin otra captura.
3. Enviar heartbeats firmados con la clave Ed25519 enrolada; Daily declara
   offline una señal de más de 90 s.
4. Daily emite assertion EdDSA de un uso, ligada a usuario, equipo, estación y
   monitor, con scope exacto `live:read`. El daemon verifica firma, expiración,
   replay y el límite de tres sesiones.
5. Daily entrega la assertion al iframe LAN por `postMessage` de origen exacto.
   Assertions, capabilities, paths y clips no se guardan ni se incluyen en URL.

## Consecuencias

- Daily requiere migración, Edge Functions, permisos y tab; The Watcher
  requiere puerto/adaptador nuevo, TLS y pruebas de autorización.
- El despliegue distribuye CA/certificados y firewall. Sin esos requisitos,
  falla cerrado; nunca baja a HTTP ni a acceso sin autenticación.
- No hay relay de Internet, control remoto, clips ni reutilización de
  `browser_local`. Si la escala exige relay/WebRTC, se revisa ADR-0018.

## Opciones no elegidas

- Abrir `browser_local` a LAN: viola ADR-0020.
- Enviar video por Supabase, JSON IPC o `watcher://`: rompe las fronteras de
  media y seguridad.
- Usar el heartbeat de sesión de Daily como salud del daemon: solo prueba que
  el navegador sigue activo.
