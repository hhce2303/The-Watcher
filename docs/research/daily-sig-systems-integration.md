# Investigación: Contenedor en SIGDailyReport para la UI de The Watcher

> Documento de investigación previo a convertirse en GOAL/épica. Responde a la pregunta:
> ¿cómo hace `daily.sig.systems` (página pública, HTTPS) para mostrar dentro de un
> contenedor la UI de The Watcher, cuyo backend (daemon) corre en la máquina local del
> operador?
>
> Estado: **investigación completada** · Fecha: 2026-09-13 · Fuente: workflow `deep-research`
> (5 ángulos de búsqueda, 20 fuentes, 25 claims verificados por voto adversarial 3/3).
> Repo relacionado: `SIGDailyReport` (`C:\Users\hcruz\OneDrive - SIG Systems, Inc\Desktop\PROJECTS-HH\SIGDailyReport`).

---

## 1. Resumen ejecutivo / recomendación

**Patrón recomendado: iframe same-origin servido por el propio daemon local, sobre `wss://localhost`
con CA local instalada (tipo mkcert) + token de sesión, sin túnel público.**

- El "contenedor" en `daily.sig.systems` debe ser un `<iframe>` que apunta a
  `https://localhost:<puerto>` (el daemon de The Watcher sirve su propia UI HTML/JS ya
  compilada). **No** conviene embeber la UI de React directamente en el DOM de
  SIGDailyReport hablando por WS/HTTP al daemon: así se evita CORS, preflight `OPTIONS`,
  y el problema de credenciales cross-origin (§2, §3).
- El daemon debe exponer `wss://localhost:<puerto>` (no `ws://`), con un certificado de
  una CA local instalada en el trust store del sistema (mkcert), porque los navegadores
  modernos **no garantizan de forma uniforme** una excepción de mixed-content para
  WebSocket-a-localhost (a diferencia de `fetch`/XHR, donde sí hay más consenso) — ver §3.
- El daemon debe enviar `Content-Security-Policy: frame-ancestors https://daily.sig.systems`
  para permitir explícitamente ser embebido solo por ese origen (§2).
- Autenticación: token de sesión (no depender solo de que la conexión sea loopback —
  "local no es lo mismo que confiable", §1.1) pasado vía query param o mensaje
  post-conexión (el navegador no permite headers custom en el handshake WS), validando
  además el header `Origin` en el servidor para evitar Cross-Site WebSocket Hijacking.
- **No se necesita túnel tipo ngrok/cloudflared** para este caso: el modelo es
  "página remota embebe/consulta algo que corre en `localhost` del mismo navegador/PC del
  usuario", no "acceso remoto desde otra máquina". El precedente de VS Code Tunnels (relay
  en la nube + auth de cuenta) es arquitectónicamente distinto y **no aplica directamente**
  (ver §4 — este paralelismo fue explícitamente descartado en la verificación).
- UX cuando el daemon no está corriendo: el iframe debe hacer fallback a un estado
  "Watcher no detectado en este equipo" con instrucciones, en vez de mostrar un error de
  certificado o una pantalla en blanco (no hay fuente verificada específica para esto —
  es recomendación de buenas prácticas generales de resiliencia, no un claim investigado).

---

## 2. Arquitectura del contenedor: iframe vs UI embebida

| Opción | Descripción | Pros | Contras |
|---|---|---|---|
| **A. iframe → UI servida por el daemon (recomendada)** | El daemon local expone HTTP+WS en `localhost` y sirve su propia UI (HTML/JS ya empaquetado, p. ej. el build de Tauri/React de The Watcher). SIGDailyReport solo pone un `<iframe src="https://localhost:PUERTO">`. | Same-origin dentro del iframe → sin problemas de CORS entre el iframe y su propio backend; el daemon controla su propio `frame-ancestors`; aísla el dominio de fallos (un crash de la UI de Watcher no rompe SIGDailyReport). | Requiere que el daemon sirva contenido estático + WS; certificado local necesario para que el iframe (dentro de una página HTTPS) no dispare mixed-content. |
| **B. UI React embebida en SIGDailyReport, hablando directo por WS/HTTP al daemon** | El bundle de React vive en el propio código de SIGDailyReport; hace fetch/WS a `https://localhost:PUERTO/api`. | Una sola SPA, sin iframe. | Cross-origin real: cada request dispara CORS (y preflight `OPTIONS` para requests "no simples"); si usa credenciales, el servidor no puede responder con `Access-Control-Allow-Origin: *` sino el origen exacto; acopla el ciclo de release de SIGDailyReport al de Watcher. |
| **C. Otras alternativas** | WebRTC data channel (pensado para P2P navegador-navegador, no para hablar con un proceso nativo — no hay evidencia de uso típico aquí); protocolo custom vía extensión de navegador (viable pero requiere que el usuario instale una extensión, fuera de alcance salvo que ya exista). | — | Mayor complejidad de despliegue sin beneficio claro sobre A. |

Puntos de CSP/CORS confirmados por la investigación:
- `frame-ancestors` (CSP) es el mecanismo correcto y moderno para controlar quién puede
  embeber una página en iframe — reemplaza a `X-Frame-Options`. Solo puede enviarse como
  **header HTTP**, nunca vía `<meta>`, y si el servidor no lo especifica explícitamente
  **no hay restricción por defecto** (no hace fallback a `default-src`). En iframes
  anidados, cada nivel de ancestro debe estar permitido explícitamente. *(Fuente: MDN
  CSP frame-ancestors)*
- CORS con credenciales (cookies/token) exige origen exacto en
  `Access-Control-Allow-Origin`, nunca `*`; y cualquier request "no simple" (headers
  custom, métodos distintos de GET/POST simple) dispara un preflight `OPTIONS` que el
  daemon debe manejar. *(Fuente: MDN CORS)*

---

## 3. Conectividad web pública → daemon local: opciones y riesgos

### 3.1 WebSocket local con token (recomendado para este caso)

- Los navegadores **no aplican Same-Origin Policy al handshake de WebSocket**: cualquier
  origen puede intentar abrir un WS hacia cualquier otro. Si el servidor no valida el
  header `Origin`, queda expuesto a **Cross-Site WebSocket Hijacking (CSWSH)**.
  *(Fuente: Ably — WebSocket authentication)*
- La API `WebSocket` del navegador **no permite fijar headers HTTP arbitrarios** (p. ej.
  `Authorization`) en el handshake. Los cuatro patrones de auth viables son: token en
  **query param**, **cookie**, mensaje **post-conexión**, o campo
  **`Sec-WebSocket-Protocol`** (subprotocolo). La autenticación debe ocurrir en el
  handshake o inmediatamente después de conectar (a diferencia de REST, que autentica
  cada request). *(Fuentes: Ably, OneUptime — WebSocket authentication)*
- Recomendación concreta para The Watcher: token de sesión de vida corta generado por el
  daemon al arrancar, inyectado en el iframe `src` como query param, validado en el
  handshake junto con el header `Origin` esperado (`https://daily.sig.systems`).

### 3.2 Named pipes (si se usara IPC nativo en vez de WS — contexto Tauri)

- El *security descriptor* por defecto de un named pipe de Windows (NULL) otorga acceso
  no solo a admins/`LocalSystem`, sino también **read access al grupo `Everyone` y a la
  cuenta anónima** — un pipe sin configurar explícitamente **no** está restringido a un
  único usuario autenticado. *(Fuente: Microsoft Learn — Named Pipe Security)*
- Conectar exitosamente a un pipe solo prueba que el cliente tenía permiso de *abrirlo*,
  **no** que sea la aplicación esperada ni autoriza operaciones específicas — se necesita
  autorización por mensaje además del ACL del pipe. Y en general: **"local" no implica
  "confiable"** — otro proceso en la misma máquina, bajo otro usuario, puede acceder si
  conoce el nombre del pipe y tiene permiso. *(Fuente: BleepingComputer — Named Pipes
  Under Attack)*
- Esto es coherente con el ADR-0011 ya vigente en el proyecto (IPC local autenticado,
  nunca solo por ser loopback) — la investigación lo confirma como buena práctica externa,
  no solo como decisión interna.

### 3.3 Túneles (ngrok/cloudflared/SocketXP) — no aplica a este caso

- Estas herramientas crean un túnel **saliente** desde el dispositivo local hacia un
  gateway en la nube, asignando una URL pública HTTPS, evitando exponer directamente el
  servidor o hacer port-forwarding. *(Fuente: SocketXP)* Es el patrón correcto cuando
  **otra persona/máquina remota** necesita alcanzar tu proceso local. **No es el caso de
  daily.sig.systems**, donde el mismo usuario que tiene el daemon corriendo es quien abre
  la página en su propio navegador — ahí el daemon ya es alcanzable directamente por
  `localhost` sin necesidad de túnel.

### 3.4 WebRTC data channel

- No se encontró evidencia de que sea un patrón usado para "página pública habla con
  proceso nativo local"; está diseñado para conexiones P2P navegador-navegador. Se
  descarta por complejidad innecesaria frente a WS+token.

---

## 4. Buenas prácticas: mixed content, certificados, CSP, UX de fallback

### 4.1 Mixed content HTTPS → localhost

- Una página HTTPS haciendo `fetch()`/`XHR` hacia un endpoint HTTP se clasifica como
  contenido *"blockable"* y el navegador lo **bloquea directamente** (no solo advierte).
  *(Fuente: MDN — Mixed content)*
- Excepción histórica: Firefox 55 (2017) dejó de bloquear mixed content para
  **direcciones IP loopback literales** (`127.0.0.1`, `::1`); el hostname `localhost`
  necesitó un fix aparte y posterior. *(Fuente: Bugzilla #903966)*
- **Importante — matiz verificado**: esa excepción de mixed-content para loopback
  **no se traduce igual a WebSocket**. Hay una asimetría real: el bloqueo de `ws://`
  (no `wss://`) desde una página HTTPS hacia `localhost` sigue vigente y es inconsistente
  entre navegadores en 2026 (Chromium tiene un issue abierto sin resolver sobre tratar
  WebSocket-a-localhost como contenido seguro). **Conclusión práctica: no asumir que
  `ws://localhost` funcionará sin problemas solo por la excepción de loopback de HTTP —
  usar `wss://` con certificado de confianza.**

### 4.2 Certificados para localhost

- Un certificado autofirmado **no da garantía de identidad** al visitante sin validación
  de una CA externa (un MITM podría presentar su propio autofirmado para el mismo
  nombre). *(Fuente: Wikipedia — Self-signed certificate, con matiz de la verificación
  adversarial)*
- **Recomendación correcta (confirmada, no lo que sugería la fuente inicial)**: no usar
  un certificado autofirmado suelto, sino **instalar una CA local en el trust store del
  sistema operativo** (herramienta tipo `mkcert`) para que el navegador confíe en
  `wss://localhost` sin advertencias. Esto es exactamente lo que ya usan flujos de
  desarrollo local modernos (web.dev, Let's Encrypt, mkcert).

### 4.3 UX cuando el daemon no está corriendo

- No hubo claims específicos verificados sobre este punto en la investigación (vacío de
  cobertura). Recomendación de buen juicio, no investigada: el iframe debe detectar el
  fallo de conexión (timeout del WS / `onerror`) y mostrar un estado explícito
  ("Watcher no está corriendo en este equipo — ábrelo para ver esta sección") en vez de
  dejar un iframe en blanco o un error de certificado crudo.

---

## 5. Precedentes de productos similares

| Producto | Patrón | Aplica a este caso? |
|---|---|---|
| **VS Code Remote Tunnels** | Túnel saliente hacia el servicio de relay "Microsoft Dev Tunnels"; sin puertos entrantes abiertos; ambos extremos (host y cliente) se autentican con la **misma cuenta** GitHub/Microsoft. Internamente sí usa una conexión cifrada (SSH) sobre el túnel para cifrado end-to-end. *(Fuente: VS Code docs — Tunnels)* | **Parcialmente.** Buen precedente para "auth de cuenta + túnel-relay", pero **no** es análogo a "página pública habla directo con localhost" — ese paralelismo fue explícitamente descartado en la verificación adversarial (vscode.dev no conecta navegador→localhost directo, sino navegador→relay-en-la-nube-de-Microsoft→servidor). |
| **SocketXP / ngrok / cloudflared** | Túnel saliente + URL pública HTTPS, evita exponer el WS local directamente. *(Fuente: SocketXP)* | Solo si se necesitara acceso desde **otra máquina** distinta a la del usuario — no es el caso de daily.sig.systems. |
| **Plex** (`X-Plex-Token`) | Mencionado en resultados de búsqueda (token de sesión en headers/query) pero **sin verificación adversarial independiente** — tratar como pista, no como claim confirmado. | Pista para el diseño del token de sesión, no confirmado. |
| Docker Desktop, Jellyfin, Ollama web UIs, OBS remote control | **No se encontraron ni verificaron claims** — vacío de cobertura de esta investigación (el ángulo de búsqueda de precedentes no profundizó en estos productos). | Pendiente si se quiere ampliar la investigación. |

---

## 6. Claims descartados en verificación adversarial (para no repetir errores)

- ~~Un origen HTTPS remoto puede hacer fetch a `http://localhost` sin bloqueo de mixed
  content, por la excepción de "recursos locales como origen seguro"~~ — **refutado**:
  la excepción de MDN habla de recursos cargados *por* una página ya en localhost, no de
  un origen remoto apuntando *a* localhost; el comportamiento real es inconsistente entre
  navegadores.
- ~~Los certificados autofirmados son la opción apropiada para un daemon localhost~~ —
  **refutado**: la práctica correcta es una CA local instalada (mkcert), no un
  autofirmado suelto.
- ~~vscode.dev es precedente directo de "página pública conecta a localhost"~~ —
  **refutado**: es un modelo de relay-en-la-nube con auth de cuenta, arquitectónicamente
  distinto.
- ~~Un hilo de GitHub de un proyecto pequeño (`maw-rs`) mostraba una inconsistencia de
  diseño deliberada entre clientes loopback sin token y páginas de navegador con token
  obligatorio~~ — **refutado**: los propios mantenedores lo calificaron de bug/regresión
  ya corregido, no de patrón de diseño a seguir.

---

## 7. Siguientes pasos sugeridos

1. Validar con un spike técnico (similar al gate F0 de la migración Tauri) si el daemon
   de The Watcher ya puede servir HTTP+WS con TLS local (mkcert) y `frame-ancestors`, o
   si requiere trabajo adicional en `adapters/ipc`.
   Nota importante: la investigación no cubrió expresamente Tauri/WebView2 IPC vs.
   navegador — para el canal *interno* de la app de escritorio ya rige ADR-0009/ADR-0011;
   este documento es específico al canal *externo* (navegador de daily.sig.systems →
   daemon).
2. Confirmar con el equipo de SIGDailyReport el mecanismo de despliegue del iframe
   (¿ruta estática, componente dinámico?) y quién gestiona la CSP de esa página para
   permitir el `frame-ancestors` inverso si aplica.
3. Definir el modelo de token de sesión (vida, rotación, dónde se genera) antes de
   convertir esto en épica/historias en `docs/backlog/`.
4. (Opcional) Ampliar la investigación de precedentes a Docker Desktop, Jellyfin y Ollama
   si se quiere más cobertura antes de comprometer la arquitectura.

---

## 8. Fuentes citadas

- MDN — [Mixed content](https://developer.mozilla.org/en-US/docs/Web/Security/Mixed_content)
- MDN — [CSP: frame-ancestors](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy/frame-ancestors)
- MDN — [CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS)
- Ably — [WebSocket authentication](https://ably.com/blog/websocket-authentication)
- OneUptime — [WebSocket authentication](https://oneuptime.com/blog/post/2026-01-24-websocket-authentication/view)
- Microsoft Learn — [Named Pipe Security and Access Rights](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)
- BleepingComputer — [Named Pipes Under Attack](https://www.bleepingcomputer.com/news/security/named-pipes-under-attack-securing-windows-interprocess-communication/amp/)
- Mozilla Bugzilla — [Bug 903966: mixed content loopback exception](https://bugzilla.mozilla.org/show_bug.cgi?id=903966)
- Wikipedia — [Self-signed certificate](https://en.wikipedia.org/wiki/Self-signed_certificate)
- TechNetExperts — [Connect local WS from HTTPS](https://www.technetexperts.com/connect-local-ws-from-https/)
- VS Code docs — [Remote Tunnels](https://code.visualstudio.com/docs/remote/tunnels) · [VS Code Server](https://code.visualstudio.com/docs/remote/vscode-server)
- SocketXP — [Remote access WebSocket server from internet](https://www.socketxp.com/iot/remote-access-websocket-server-from-internet/)

> Metodología: workflow `deep-research` con 5 ángulos de búsqueda, 20 fuentes fetcheadas,
> 72 claims extraídos, 25 verificados por voto adversarial (2/3 o 3/3), 20 confirmados y
> 5 refutados. El paso de síntesis automática del workflow falló (bug de schema); este
> documento se reconstruyó manualmente a partir del journal crudo de resultados
> verificados para no perder el trabajo ya hecho.
