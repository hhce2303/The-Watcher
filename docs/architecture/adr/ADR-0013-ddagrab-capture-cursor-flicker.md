# ADR-0013 — Captura por ddagrab (DXGI) para eliminar el titileo del cursor

- **Estado**: Aceptado
- **Fecha**: 2026-07-04
- **Relación**: realiza parcialmente [ADR-0007](ADR-0007-dxgi-capture-deferred.md) (Captura DXGI: diferida) —
  ver "Consecuencias". No arranca Track R ni el port Rust `windows-capture`.

## Contexto

La captura usaba `ffmpeg -f gdigrab` (GDI BitBlt). En la ventana de Operador a pantalla completa, el
cursor del mouse **titilaba de forma continua** mientras grababa. Tras descartar ~10 hipótesis de UI
(bindings reactivos de `cursorShape`, `requestActivate`, overlays con `visible` vs `opacity`,
`monitorsChanged` duplicado, carrera de escritura del JPEG de preview, `-draw_mouse 1→0`), el titileo
persistía.

La causa raíz es el mecanismo de captura, no la UI:

- gdigrab captura con `BitBlt(..., SRCCOPY | CAPTUREBLT)`. El flag **`CAPTUREBLT`** obliga al driver de
  display a **ocultar y repintar el sprite del cursor por hardware en cada blit** (~30/s a 30 fps) para
  componer correctamente las ventanas layered. Eso es lo que se ve como titileo.
- `CAPTUREBLT` está **compilado sin opción de CLI** en `libavdevice/gdigrab.c`; no hay bandera para
  desactivarlo.
- `-draw_mouse 0` **no** lo arregla: solo evita que FFmpeg *pinte* el cursor dentro del frame capturado
  (paso posterior al blit); no toca el ocultar/repintar del sprite real que causa `CAPTUREBLT`.

Validación empírica en máquina real (Windows 11, FFmpeg 8.1-full con `ddagrab`, encoder `h264_qsv`):
el pipeline dual (segmentos `.ts` + preview `.jpg`) reproducido con `ddagrab` produce **ambas salidas
válidas** y no usa BitBlt/CAPTUREBLT.

## Decisión

**Cambiar el input de FFmpeg de `gdigrab` a `ddagrab`** (DXGI Desktop Duplication API) en
`FFmpegRecorderAdapter`, con selección de backend `auto | ddagrab | gdigrab`:

- `ddagrab` es un **source filter** (sin `-i`): la cadena empieza con
  `ddagrab=output_idx=N:framerate=F:draw_mouse=0,hwdownload,format=bgra` y luego el mismo `split`
  segmento+preview de antes. Entrega frames GPU (D3D11) → `hwdownload,format=bgra` los baja a memoria
  de sistema antes del `scale`/encode por software o hardware.
- **Selección de monitor por `output_idx`** (= `MonitorInfo.index`), no por coordenadas del escritorio
  virtual. Captura en **píxeles físicos**; el `scale` existente a `output_width×output_height` absorbe
  la diferencia de DPI. No se pasan `offset_x/offset_y/video_size` (serían recortes intra-monitor).
- **`auto` (default)** hace un probe único (2 frames a `-f null`) al `start()`: si ddagrab funciona,
  lo usa; si no (Windows viejo / sin D3D11), **cae a gdigrab** con warning. Config vía `CAPTURE_BACKEND`.

## Consecuencias

- ✅ Elimina el titileo del cursor en la ruta crítica (Operador a pantalla completa grabando).
- ✅ Mantiene gdigrab como **fallback runtime** — cumple lo que ADR-0007 pedía para revisitar captura.
- ✅ ddagrab puede componer el cursor GPU-side sin coste de titileo, así que `draw_mouse` es libre
  (se deja en `0` por paridad con el comportamiento previo).
- ➖ `hwdownload` copia GPU→RAM cada frame; con `h264_qsv`/`nvenc` hay un re-upload (doble copia). La
  optimización *zero-copy* (mantener frames en GPU con `hwmap`/encoder HW directo) queda **pendiente**
  y no es requisito aquí (el objetivo es correctitud + sin titileo).
- ➖ El mapeo `MonitorInfo.index → output_idx` es un heurístico; en multi-monitor con orden DXGI
  distinto al posicional podría requerir ajuste. Aceptable para la flota actual.
- 🔁 **Realiza parcialmente ADR-0007** para la ruta FFmpeg (gdigrab→DXGI), motivado por el titileo (no
  por profiling de CPU). ADR-0007 seguía apuntando al port **Rust** `windows-capture` (Track R), que
  **no** se toca aquí: sigue diferido y arrancará con su propio ADR de profiling + spike de paridad.
