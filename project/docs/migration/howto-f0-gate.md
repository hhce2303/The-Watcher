# How-to — Ejecutar el gate F0 (GO/NO-GO bloqueante)

Cómo probar los bloqueadores TIER-1 de la migración **antes** de comprometer 6-10 semanas de
reescritura. Al terminar tendrás una decisión GO/NO-GO documentada con criterios numéricos.

> F0 es un **gate, no exploración opcional**. Si algún criterio falla, se reevalúa la estrategia
> (transcode, frames server-side) o se aborta. Sin GO no se empieza la Fase 1.

## Prerequisitos

- Una **máquina REAL de operador** (imagen corporativa típica), **no** la dev box. Los tres
  bloqueadores fallan justo en máquinas sin GPU/codecs modernos.
- Node/npm y Rust (`rustup` + toolchain MSVC) para el shell Tauri; `cargo` en PATH.
- Un clip HEVC real generado por el recorder (los clips de producción son HEVC).
- FFmpeg disponible (ya se usa en el backend).

## Los 6 criterios de salida

| Spike | Criterio GO | Owner |
|-------|-------------|-------|
| **HEVC en WebView2** | Un clip HEVC real se reproduce en `<video>` en una máquina **sin** HEVC Video Extensions / sin GPU HEVC. Si NO → decidir transcode a H.264 en export o on-the-fly | QA |
| **Preview en vivo** | Latencia end-to-end (gdigrab→JPEG→transporte→canvas) **≤ 1 s** y **≤ 5% CPU por monitor**, multi-monitor | Backend |
| **Scrub frame-exact** | Seek error **≤ 2 frames** en `<video>` con archivos reales; si peor → prototipo de frames server-side | Frontend |
| **Seguridad IPC** | Prototipo named pipe (o token build-time); un `stopRecording` desde un cliente no autorizado es **rechazado** | Backend |
| **WebView2 ausente** | Instalación probada en VM con WebView2 desinstalado; experiencia de bootstrap documentada | QA |
| **Sidecar + daemon** | Tauri lanza el sidecar y lo mata limpio al cerrar; daemon arranca por scheduled-task y bindea el canal; **sin huérfanos** | Backend |

## Pasos

1. **Levanta un shell Tauri 2.0 + React mínimo en Windows.**

   ```bash
   npm create tauri-app@latest    # elegir React + TypeScript
   npm install && npm run tauri dev
   ```

   Verifica que la ventana abre y renderiza. Si WebView2 no está presente, anota qué pide el
   bootstrapper (esto ya cubre el spike "WebView2 ausente" si lo corres en la VM limpia).

2. **Spike HEVC (el más crítico).** Carga un clip HEVC real en un `<video>` dentro del webview en la
   máquina de operador.

   - GO: reproduce. NO-GO: pantalla negra / `error` del elemento. Comprueba también con las "HEVC
     Video Extensions" desinstaladas.
   - Si NO-GO, la decisión explícita es: transcode a H.264 en export (+tamaño/CPU) o transcode
     on-the-fly. Documenta cuál.

3. **Spike preview en vivo.** Conecta el pipeline actual (FFmpeg escribe JPEG @2 fps — ver
   `live_preview_service.py`) a un transporte candidato (custom protocol de Tauri, push binario, o
   MJPEG localhost) y **mide** latencia y CPU con 1, 2 y 3 monitores.

   - GO: ≤ 1 s y ≤ 5% CPU por monitor.

4. **Spike scrub frame-exact.** En el `<video>`, salta a un frame objetivo y mide el error real
   (frame mostrado vs pedido) con archivos reales del recorder.

   - GO: ≤ 2 frames. Si peor, prototipa extracción de frames server-side.

5. **Spike seguridad IPC.** Monta un named pipe (o TCP loopback + token) y prueba que un cliente sin
   token NO puede ejecutar `stopRecording`. Ver
   [ADR-0011](../editing/adr/ADR-0011-local-ipc-security.md).

6. **Spike sidecar/daemon.** Empaqueta el backend Python con PyInstaller como `externalBin`; que Tauri
   lo lance y lo mate limpio al cerrar (rol IT). Aparte, que el scheduled-task watchdog arranque el
   daemon (rol Operador) y bindee el canal. Comprueba con `tasklist` que no quedan huérfanos.

## Verificación

Escribe un documento GO/NO-GO con los 6 criterios y su resultado numérico. **GO** requiere los 6 en
verde (o una decisión explícita registrada para HEVC). Solo con GO se abre la Fase 1.

## Troubleshooting

- **`<video>` negro con HEVC:** esperado en muchas máquinas — es el hallazgo, no un bug tuyo. Pasa al
  plan de transcode.
- **Preview con lag:** prueba el custom protocol de Tauri (evita el overhead JSON) o delta-frames
  antes de declarar NO-GO.
- **`cargo` no encontrado:** instala rustup + toolchain MSVC; el shell Tauri no compila sin él.
- **Sidecar zombie al cerrar:** en Windows la terminación del hijo no es automática; Tauri debe
  matar el proceso explícitamente. Verifica con `tasklist`.

## Relacionado
- [Referencia — Arquitectura objetivo](reference-target-architecture.md) · [ADR-0008](../editing/adr/ADR-0008-tauri-ui-migration.md) · [ADR-0011](../editing/adr/ADR-0011-local-ipc-security.md)
