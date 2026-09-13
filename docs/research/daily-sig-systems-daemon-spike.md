# Spike técnico — Daily SIG Systems ↔ daemon local de The Watcher

Fecha: 2026-09-13  
Estado: **NO-GO para integrar con el daemon actual; GO condicionado para un adaptador web local nuevo.**

## Decisión

El daemon de The Watcher **no puede hoy** servir el canal externo que requiere una página de
`https://daily.sig.systems`: una UI web con HTTP(S), WSS, certificado local confiable y una
política `frame-ancestors`. No es una configuración faltante ni un cambio pequeño en el
named-pipe: esos protocolos no existen en el runtime actual.

La solución debe ser aditiva: un adaptador `browser_local` (nombre provisional) limitado a
loopback y una API externa de sólo lectura, conectada a la fachada de core mediante un contrato
estrecho. No se debe publicar `IpcRouter`, el pipe de Tauri ni el WebSocket Supervisor existente.
Esto preserva ADR-0009/ADR-0011 para el canal interno Tauri ↔ daemon y crea una frontera distinta
para navegador ↔ daemon.

La investigación previa recomendaba servir el build React/Tauri dentro de un iframe. El spike
refuta esa parte concreta: el build actual no es una aplicación web autónoma. Importa
`@tauri-apps/api`, invoca `ipc_send`, escucha eventos nativos de Tauri y obtiene vídeo por el
protocolo `watcher://`; un navegador normal no proporciona ninguno de esos mecanismos.

## Alcance y método

Se revisó el código de runtime, transportes y UI; se ejecutaron los tests de los dos servidores
existentes y se verificó la versión y firma de `websockets`. También se inspeccionó, sólo en
lectura, el repo hermano `SIGDailyReport`. Las conclusiones de este documento son la validación
técnica solicitada; no se exponen puertos nuevos, no se cambia el IPC interno y no se instala una
CA durante este spike.

Comandos ejecutados:

```powershell
cd project
uv run --python "$env:LOCALAPPDATA\The Watcher\venv\Scripts\python.exe" `
  python -m pytest tests/test_preview_server.py tests/test_ws_requests.py -q
# 18 passed
```

El paquete instalado es `websockets 16.0`. Su `serve()` acepta `origins`,
`process_request` y los argumentos TLS que delega al servidor asyncio. Es decir, la dependencia
actual **sí es capaz** de participar en una implementación WSS segura; el producto no la usa para
este propósito todavía.[^websockets]

`mkcert` no está instalado en esta estación. Además, al momento del spike C: tenía aproximadamente
0,93 GiB libres; no se instaló ni se ejecutó `mkcert -install`, porque eso modifica el almacén de
confianza del usuario y el espacio disponible no hace segura esa operación. Cuando se apruebe la
implementación, el despliegue administrado deberá instalar la CA local y proteger la clave privada;
mkcert genera una CA local y puede emitir certificados para `localhost`, `127.0.0.1` y `::1`.[^mkcert]

## Resultado del gate

| Control F0 | Evidencia observada | Resultado |
|---|---|---|
| Listener HTTP para navegador | `MjpegPreviewServerAdapter` usa `ThreadingHTTPServer`, normalmente en `127.0.0.1:8787`; sólo entrega `/health`, JPEG y MJPEG. | Falla para la UI/clip API externa. |
| TLS local | El preview construye `http://…`; no carga certificado ni `SSLContext`. El WS de solicitudes llama `websockets.serve()` sin TLS. | Falla. |
| WebSocket para navegador | `ClipRequestServer` es el protocolo IT/Supervisor, escucha `0.0.0.0`, y no entrega `origins` ni autenticación. | Falla; no reutilizable. |
| CSP de iframe | Ninguno de los servidores emite `Content-Security-Policy` o `frame-ancestors`. El preview emite `Access-Control-Allow-Origin: *`. | Falla. |
| UI servible por navegador | `src/lib/ipc.ts` usa Tauri `invoke`; stores/hooks usan `listen`; media usa `watcher://`. | Falla. |
| Protección de archivos/media | El protocolo Tauri sí implementa su propio allowlist/Range, pero no hay endpoint HTTP equivalente para clips. | Falla. |
| Aislamiento del IPC actual | `HeadlessRuntime` inicia `NamedPipeIpcServer(IpcRouter(api), api.bus)` y nada HTTP/WSS. El pipe tiene ACL por SID. | Pasa: se puede conservar intacto. |
| Regresión de servidores existentes | `test_preview_server.py` y `test_ws_requests.py`: 18 pruebas exitosas. | Pasa, pero no prueba el canal nuevo. |

Los archivos que sostienen el resultado son
[`mjpeg_server_adapter.py`](../../project/app/adapters/preview_server/mjpeg_server_adapter.py),
[`request_server.py`](../../project/app/adapters/ws/request_server.py),
[`headless.py`](../../project/app/runtime/headless.py),
[`main.py`](../../project/app/main.py),
[`ipc.ts`](../../src/lib/ipc.ts) y
[`mediaUrl.ts`](../../src/lib/mediaUrl.ts).

## Arquitectura mínima que habilita el GO

```text
daily.sig.systems (HTTPS, usuario autenticado)
  └─ iframe https://localhost:<puerto>/                 [CSP del padre: frame-src]
       └─ UI web específica de navegador
            ├─ HTTPS /api/clips, /media/<id> (Range)    [TLS + token]
            └─ WSS /events                              [Origin + token]
                 └─ BrowserLocalAdapter (loopback sólo)
                      └─ API externa estrecha → core/api Facade → servicios de dominio

Tauri/WebView2 ─ named pipe autenticado ─ IpcRouter ───┘  (sin cambios de protocolo)
```

El adaptador debe escuchar exclusivamente en `127.0.0.1` y, si se soporta IPv6, también en `::1`.
No debe aceptar `0.0.0.0`, interfaces LAN ni una opción de configuración que los habilite por
accidente. El firewall no sustituye ese bind.

### Contrato externo propuesto

El primer corte debe ser de lectura:

- `GET /` sirve una UI web nueva, pequeña e independiente de Tauri.
- `GET /api/v1/session` sólo informa estado no sensible después de autenticación.
- `GET /api/v1/clips` devuelve DTOs sin rutas absolutas de Windows.
- `GET /media/<opaque-id>` sirve sólo un clip autorizado, con allowlist, `Range`, límites de
  tamaño y `Content-Type` correcto.
- `WSS /events` entrega sólo eventos de reproducción/listado permitidos. No reexpone el bus
  completo ni comandos de grabación, configuración, OneDrive, exportación o rol.

La UI debe ser un target web separado o una capa de transporte web que abstraiga Tauri. Reutilizar
componentes presentacionales es posible, pero `src/lib/ipc.ts`, listeners Tauri y `watcher://`
deben sustituirse por puertos de navegador. Asimismo, los clips HEVC no son portables de forma
fiable en navegadores/WebView2; la API deberá anunciar sólo H.264 reproducible o proporcionar una
transcodificación explícita y controlada.

Esto requiere una ADR que permita a `adapters/browser_local` ser un segundo llamador autorizado de
la fachada de core. No requiere ampliar ni debilitar `adapters/ipc`; de hecho, exponer su router
convertiría comandos internos de gran privilegio en una superficie web.

## TLS, CSP y WebSocket

El hijo local debe emitir, como mínimo y ajustado a los assets reales, una CSP similar a:

```http
Content-Security-Policy: default-src 'self'; base-uri 'none'; object-src 'none';
  frame-ancestors https://daily.sig.systems; connect-src 'self' wss://localhost:<puerto>;
  img-src 'self' data:; media-src 'self'; style-src 'self'
```

No se debe mandar `X-Frame-Options: DENY` ni `SAMEORIGIN`: contradicen el iframe entre orígenes.
`frame-ancestors` define quién puede embeber al hijo; la CSP del padre es otra política:
`frame-src https://localhost:<puerto>` define desde dónde el padre puede cargar iframes. No hay un
"frame-ancestors inverso".[^csp][^frame-src][^xfo]

Para WebSocket, pasar el allowlist exacto al servidor (`origins=["https://daily.sig.systems"]`),
rechazar ausencia de `Origin` y no aceptar comodines. La librería soporta esa defensa contra
Cross-Site WebSocket Hijacking.[^websockets] `Origin` no sustituye la autenticación: cualquier
sitio permitido puede ser atacado mediante XSS o una sesión robada.

La navegación pública HTTPS hacia loopback está sujeta a evolución de controles del navegador
como Private/Local Network Access; la especificación cubre explícitamente software con interfaz
en loopback y Chromium declara restricciones para solicitudes de público a local/loopback.[^pna]
Por tanto, el gate de implementación debe probar Chrome/Edge administrados y Firefox con la misma
política empresarial de SIG, no asumir que una excepción de `localhost` equivale a soporte
garantizado de `ws://`. Usar HTTPS/WSS con una CA local confiable es el requisito base.

## Modelo de sesión definido para la épica

La propuesta previa de que el daemon genere un secreto y que `daily.sig.systems` lo inyecte en el
`src` del iframe tiene una circularidad: el padre remoto no conoce un secreto creado sólo en la
máquina local antes de hablar con ella. El modelo siguiente elimina esa dependencia.

| Elemento | Decisión |
|---|---|
| Emisor | Backend autenticado de SIGDailyReport, no el daemon. Firma assertions con Ed25519/ES256 y publica claves por `kid` (pin/JWKS administrado). |
| Identidad de dispositivo | Instalación enrolada: `device_id` no secreto, clave pública y asignación usuario/sitio en el backend SIG. El daemon conserva su clave/certificados con ACL del usuario/servicio. |
| Bootstrap | El iframe local carga sin datos sensibles y comunica `ready`, `device_id` y nonce efímero al padre. El padre obtiene una assertion para ese usuario/dispositivo y la entrega con `postMessage` al origen exacto `https://localhost:<puerto>`. |
| Assertion | JWT firmado con `iss`, `aud=the-watcher-local`, `sub`, `device_id`, `site_id`, `scope=recordings:read`, `nonce`, `jti`, `iat`, `nbf`, `exp` y `kid`. TTL: **60 segundos**, un uso. |
| Sesión | Tras validar firma, audiencia, usuario/dispositivo, nonce, tiempo y replay, el hijo abre WSS y envía `auth` como primer mensaje. El daemon emite un identificador de sesión en memoria con TTL máximo de **5 minutos**. |
| Rotación | A los 4 minutos el padre solicita una assertion nueva y la manda por `postMessage`; el daemon invalida la sesión anterior al canjearla. No hay refresh token persistente en navegador. |
| Replay/revocación | Cache atómica de `jti` hasta `exp`; invalidación al cerrar iframe/WSS, cambiar rol o detener daemon. La vida corta limita revocación; una lista de revocación o versión de enrolamiento se consulta/cachea cuando haya conectividad. |
| Registro | Nunca poner assertion/sesión en query string, subprotocolo, URL de medios, logs ni errores. Redactar `Authorization`, `token`, `jti` y fragmentos JSON sensibles. |

`postMessage` es el puente correcto entre el padre y el hijo de distintos orígenes, siempre que ambos
comprueben `event.origin`, el tipo/esquema del mensaje y usen un `targetOrigin` exacto, nunca `*`.[^postmessage]
El WebSocket debe cerrar si no recibe `auth` en pocos segundos y no emitir metadatos antes de ella.

## Dependencia SIGDailyReport: lo que se pudo y no se pudo confirmar

En el checkout local de `SIGDailyReport`, `src/App.tsx` es una SPA dinámica que selecciona vistas
con estado (`currentView`), no un árbol de rutas de React Router. No existe un componente ni ruta
de Watcher. El repo contiene Vite para desarrollo/build estático; no contiene configuración de
headers CSP de producción ni manifiesto de reverse proxy. Por tanto:

- Es razonable implementar el contenedor como una vista/componente dinámico nuevo, pero es una
  **inferencia de código local**, no una confirmación de despliegue.
- No se puede determinar desde este repo quién controla la CSP/headers de `daily.sig.systems` ni
  si una CDN, WAF, Nginx u otro host añade políticas en producción.
- No se contactó a un equipo ni se cambió SIGDailyReport; eso requiere confirmación humana.

Mensaje de decisión para el equipo SIGDailyReport:

> ¿Cuál artefacto sirve `daily.sig.systems` en producción y quién administra sus headers CSP?
> Para el piloto necesitamos una vista autenticada que inserte un iframe a
> `https://localhost:<puerto>/` y una CSP del padre que incluya
> `frame-src https://localhost:<puerto>` (o el host/puerto final). Confirmen si se entrega como
> componente de la SPA, ruta, microfrontend o HTML estático, y quién puede desplegar esa política
> en staging y producción.

## Precedentes ampliados

Los precedentes no cambian la decisión, pero sí apoyan el patrón de exponer un servicio local de
forma explícita y con límites claros:

- Docker Desktop publica puertos de contenedores en `localhost`; no es evidencia de que un sitio
  público deba poder controlar cualquier API local.[^docker]
- Jellyfin trata HTTPS como una configuración explícita y por defecto no habilita su puerto HTTPS;
  una UI de vídeo local todavía necesita operación de certificados.[^jellyfin]
- Ollama usa una allowlist configurable de orígenes para peticiones de navegador, no una confianza
  implícita por ser local.[^ollama]

## Criterios de salida del siguiente spike implementable

1. Un proceso de prueba separado del daemon productivo carga certificado mkcert de un directorio
   con ACL restringida, escucha sólo `127.0.0.1`/`::1` y pasa health check HTTPS.
2. Una página de staging de Daily puede embeber el iframe; un origen distinto falla por
   `frame-ancestors` y por `frame-src` del padre.
3. WSS acepta el origen Daily y una assertion válida; rechaza origen distinto, falta de token,
   token vencido, `jti` repetido y `device_id` distinto.
4. Un clip permitido se lista y reproduce con Range; no se filtran rutas absolutas ni se accede a
   una ruta fuera del allowlist.
5. La UI ofrece estado claro cuando daemon, certificado o enrolamiento no están disponibles.
6. `pytest` del backend, `npm test`, `cargo check` y pruebas de named pipe siguen pasando; no hay
   listener LAN nuevo ni cambios al contrato IPC Tauri.

Hasta pasar estos criterios, no crear historias de producción que prometan el iframe. Sí se puede
crear una épica de descubrimiento/implementación con este modelo de sesión y las dependencias de
despliegue señaladas.

## Fuentes

[^websockets]: [websockets — servidor asyncio: allowlist de Origin](https://websockets.readthedocs.io/en/stable/reference/asyncio/server.html)
[^mkcert]: [mkcert — CA local y certificados de desarrollo](https://github.com/FiloSottile/mkcert)
[^csp]: [MDN — Content-Security-Policy y `frame-ancestors`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy)
[^frame-src]: [MDN — `frame-src`](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-src)
[^xfo]: [MDN — X-Frame-Options](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options)
[^pna]: [WICG — Local Network Access](https://wicg.github.io/local-network-access/)
[^postmessage]: [MDN — `Window.postMessage()`](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)
[^docker]: [Docker Desktop — networking](https://docs.docker.com/desktop/features/networking/networking-how-tos/)
[^jellyfin]: [Jellyfin — networking](https://jellyfin.org/docs/general/post-install/networking/)
[^ollama]: [Ollama — FAQ: additional web origins](https://docs.ollama.com/faq)
