# ADR-0022 — Live view: H.264 sobre un único WebSocket, MJPEG como respaldo

- **Estado**: Aceptado (enmienda ADR-0021 puntos 2 y de 8–10 fps)
- **Fecha**: 2026-09-30
- **Requisitos**: NFR-Perf-5, NFR-Perf-7

## Contexto

ADR-0021 distribuía el JPEG del recorder como MJPEG, un `<img>` por monitor.
Pruebas en el PC Operator de 4 monitores (2026-09-30) mostraron tres límites:

1. **Conexiones.** Cada monitor es un stream HTTP/1.1 infinito. Los navegadores
   permiten 6 conexiones por host; 6 streams agotaban el cupo y el iframe de
   cualquier otra pestaña quedaba en `pending`, sin error ni rastro en el log.
2. **Fluidez.** El preview sale del recorder con `fps=10` y JPEG q:v 2. A 24 fps
   el MJPEG mide 18–29 Mbit/s **por monitor** con la pantalla casi quieta
   (≈200–350 Mbit/s con 3 supervisores × 4 monitores).
3. **Captura.** `gdigrab` entregó ~20 fps reales bajo carga, no 30.

## Decisión

1. **Un WebSocket por pestaña** (`/events`). Cada frame binario es
   `[tipo][monitor][payload]`; tipo 0 = JPEG, 1 = H.264 clave, 2 = H.264 delta.
2. **H.264 codificado una sola vez por monitor**, bajo demanda: un proceso
   FFmpeg (`h264_feed.py`) por monitor, independiente del recorder, que arranca
   con el primer visor y se detiene 10 s después del último. Todos los visores
   del monitor comparten ese encode. Reutiliza `encoder_selector` (AMD/Intel/
   NVIDIA, libx264 como último recurso), GOP de 1 s, sin B-frames, una slice.
3. El navegador decodifica con **WebCodecs** (`VideoDecoder`, Annex B) y pinta
   en `<canvas>`. Un visor nuevo espera al siguiente frame clave (≤ 1 s); uno
   lento descarta su cola y se resincroniza en el siguiente.
4. **Respaldo MJPEG** automático: si el navegador no tiene WebCodecs, si el
   decodificador falla, o si ningún encoder produce video, ese monitor se sirve
   como JPEG desde el recorder (ADR-0021). `LIVE_VIEW_TRANSPORT=mjpeg` lo fuerza.
5. Sin cambios de seguridad: misma assertion, mismo límite de 3 supervisores
   (por identidad), TLS de la CA interna, solo LAN, solo lectura.

## Alternativas descartadas

- **WebRTC (`aiortc`).** En LAN aporta poco sobre esta opción; `aiortc`
  re-codifica por cada par, multiplicando el CPU, y añade dependencias pesadas
  al empaquetado. Sigue siendo el camino si se requiere acceso fuera de la LAN,
  con un SFU externo y un ADR propio (ver ADR-0018).
- **Rama H.264 dentro del grafo del recorder.** Codificaría siempre, aunque
  nadie mire, y un fallo del encode de vista en vivo podría afectar la grabación.
- **MJPEG a 24 fps.** Inviable por ancho de banda (ver Contexto).

## Consecuencias

- Un segundo proceso de captura por monitor mientras hay visores; su CPU no está
  medido en hardware de flota. `LIVE_VIEW_VIDEO_FPS/WIDTH/KBPS` permiten bajarlo.
- `ddagrab` solo entrega frames cuando la pantalla cambia; la fluidez real
  depende de que los duplique para sostener el ritmo (registrado en el log
  `[live-h264] … fps kbit/s`).
- Validado con FFmpeg real y Chrome/Chromium headless (24.1 fps por monitor
  dibujados). Falta validar en el PC Operator con AMF y en WebView2.
