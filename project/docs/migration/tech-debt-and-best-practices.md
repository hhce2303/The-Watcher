# Deuda técnica y buenas prácticas — migración Tauri (+ endgame Rust)

Investigación aplicada (multi-fuente, `/deep-research` 2026-07-01) sobre el stack objetivo
**Tauri 2.0 + React + Python sidecar → hexágono Rust**. Tecnologías con estado de mantenimiento,
buenas prácticas accionables por área, y un **registro de deuda técnica / footguns** para vigilar.

> **Confianza:** los hallazgos vienen de fuentes nombradas (docs oficiales Tauri v2, crates
> mantenidos, repos de referencia). La verificación adversarial de 3 votos **no corrió** (rate-limit),
> así que trata los ⚠️ como "confirmar antes de comprometer". Cruza con los
> [ADRs](../editing/adr/README.md) y el [gate F0](howto-f0-gate.md).

## Tecnologías (con estado de mantenimiento)

| Área | Tecnología | Estado / nota | Fuente |
|------|-----------|---------------|--------|
| Sidecar | `externalBin` en `tauri.conf.json` | Oficial. Requiere sufijo `-<target-triple>` (`-x86_64-pc-windows-msvc.exe`) o el bundler no lo toma | [v2.tauri.app/develop/sidecar](https://v2.tauri.app/develop/sidecar/) |
| Python-en-Tauri | PyTauri (PyO3) | Alternativa al sidecar: embebe Python, sin overhead IPC, exe único. Más nuevo | [github.com/pytauri/pytauri](https://github.com/pytauri/pytauri) |
| IPC tipado | `tauri-specta` | Genera tipos TS desde comandos Rust. Mantenido | [docs.rs/tauri-specta](https://docs.rs/tauri-specta) |
| IPC tipado | `TauRPC` | IPC bidireccional tipado (comandos + eventos) | [github.com/MatsDK/TauRPC](https://github.com/MatsDK/TauRPC) |
| IPC binario | conduit `register_binary` | ~8-11× más rápido que la invoke JSON de Tauri para payloads binarios | [tauri-conduit/BENCHMARKS](https://github.com/userFRM/tauri-conduit/blob/master/BENCHMARKS.md) |
| Captura pantalla | **`windows-capture`** | **Bindings Rust Y Python (PyO3) en un solo codebase**, sobre WGC + DXGI Desktop Duplication. Semilla ideal del strangler | [github.com/NiiightmareXD/windows-capture](https://github.com/NiiightmareXD/windows-capture) |
| Mux/demux MP4 | **`shiguredo_mp4`** | Rust zero-dep, Sans-I/O, **soporta HEVC (`hev1`/`hvc1`)**. Candidato para `ClipPort` | [github.com/shiguredo/mp4-rust](https://github.com/shiguredo/mp4-rust) |
| FFmpeg en Rust | `ffmpeg-next` | ⚠️ **Modo mantenimiento** (solo compila FFmpeg 3.4-8.0, sin features nuevas) | [lib.rs/crates/ffmpeg-next](https://lib.rs/crates/ffmpeg-next) |
| Empaquetado Rust↔Py | `maturin` | 4 bindings (pyo3/cffi/uniffi/bin), auto-detecta pyo3. Ya usado en `watcher_segments` | [maturin.rs/bindings](https://www.maturin.rs/bindings.html) |
| Updater | Tauri updater | Firma minisign **obligatoria** (pubkey en `tauri.conf.json`, no desactivable) | [v2.tauri.app/plugin/updater](https://v2.tauri.app/plugin/updater/) |
| Seguridad | Capabilities | Default-deny a remoto; permisos por ventana/webview | [v2.tauri.app/security/capabilities](https://v2.tauri.app/security/capabilities/) |
| CI/packaging | `tauri-action` | Matriz macOS/Ubuntu/Windows → MSI + NSIS + GitHub Release | [github.com/tauri-apps/tauri-action](https://github.com/tauri-apps/tauri-action) |
| Playback web | WebCodecs + `@remotion/media-parser` | Camino para frame-accuracy en navegador (demux → VideoDecoder) | [remotion.dev/media-parser/webcodecs](https://www.remotion.dev/docs/media-parser/webcodecs) |

## Buenas prácticas por área

### Sidecar Python ↔ Tauri
- ✅ Empaqueta el backend con PyInstaller one-file como `externalBin`; nombra con el target-triple.
- ✅ **No confíes en `process.kill()`** para el sidecar one-file: Tauri solo conoce el PID del
  *bootloader* de PyInstaller, no del proceso Python. Manda un **comando de shutdown por stdin/stdout**
  al cerrar → evita zombies. (Test obligatorio en F1; riesgo F6.)
- ❌ **No** expongas el backend como un TCP loopback abierto con acceso solo por CORS (el patrón del
  ejemplo de referencia). En una herramienta de evidencia es la regresión de seguridad F4.

### Seguridad del canal local
- ✅ **Named pipe de Windows** (scoped al usuario) o **token burned-in en build-time** sobre loopback;
  nunca puerto TCP abierto. Ver [ADR-0011](../editing/adr/ADR-0011-local-ipc-security.md).
- ✅ **Audita** los comandos sensibles (`start/stop/unlock/setRole`) al event store con origen+timestamp.
- ✅ Aprovecha el modelo **capabilities** de Tauri (default-deny) para la superficie webview→Rust.
- ✅ Deja el updater con firma obligatoria (ya es el default seguro).

### Video: HEVC y frame-exact
- ⚠️ **HEVC en WebView2 es HW-dependiente y sin fallback por software.** WebView2 usa la ruta de Edge
  (MFT), que necesita la "HEVC Video Extension" del SO + hardware. En flota sin eso → pantalla negra.
  → **Plan de transcode a H.264** (en export o on-the-fly). Gate F0.
- ✅ **Scrub frame-exact NO desde `<video>`:** `currentTime` es tiempo (no frame), el framerate no se
  expone, `rVFC` es best-effort. Usa **frames server-side** (extrae el frame exacto y sírvelo como
  imagen) o **WebCodecs**. El export frame-exact ya es server-side (mantener).
- ⚠️ **MSE/fMP4 no resuelve el codec:** remuxar a fMP4 para `<video>` ayuda al streaming, pero el
  webview sigue necesitando decodificar HEVC. No te salva del gap HEVC.

### Preview en vivo (baja latencia)
- ✅ **No uses la invoke JSON de Tauri para frames** (serializa a strings → cuello de botella). Usa
  **WS binario** (~100 ms medidos), custom protocol, o buffer compartido (`PostSharedBufferToScript`).
- ✅ MJPEG por `<img src=stream>` es el más simple (sin JS de decode), a costa de más ancho de banda.
- ✅ SLA de F0 (≤1 s, ≤5% CPU/monitor) es alcanzable con WS binario; decide el transporte en el spike.

### Migración Python → Rust (strangler)
- ✅ Empieza por `RecorderPort`/`ClipPort` con **`windows-capture`** (ya Rust+Python) — adóptalo desde
  Python hoy, es la costura de menor fricción.
- ✅ Para el mux HEVC evalúa **`shiguredo_mp4`** (Sans-I/O, HEVC nativo) antes que reactivar `muxide`.
- ✅ Mantén la suite Python como **oráculo de paridad**; activa cada port por flag (`ENGINE_READY`).
- ⚠️ Si eliges bindings FFmpeg (`ffmpeg-next`), asume su modo mantenimiento; considera crates puros.

### Frontend / contrato IPC
- ✅ Genera los tipos TS desde el backend (`tauri-specta` o `TauRPC`) — un solo contrato, sin drift.
- ✅ CI con `tauri-action` (matriz de OS) para MSI/NSIS; reusa/evoluciona
  [`build.ps1`](../../installer/build.ps1) en lugar de scripts paralelos.

## Registro de deuda técnica / riesgos a vigilar

Formato: qué → por qué importa → disparador/mitigación. Espejo del estilo de `TODOS.md`.

| ID | Deuda / riesgo | Por qué importa | Disparador / mitigación |
|----|----------------|-----------------|--------------------------|
| TD-1 | HEVC no reproducible en WebView2 en parte de la flota | Editor/player rotos (evidencia) | Gate F0; transcode a H.264 (export u on-the-fly) |
| TD-2 | Canal local inseguro si se copia el patrón CORS/TCP abierto | Cualquier proceso local emite `stopRecording`/`unlockIT` | Named pipe/token + audit (ADR-0011); test en F0 |
| TD-3 | Zombie del sidecar PyInstaller (`process.kill()` no basta) | Procesos huérfanos, puerto colgado | Shutdown por stdin/stdout; test de ciclo de vida F1 |
| TD-4 | `ffmpeg-next` en modo mantenimiento | Dep de largo plazo sin features nuevas | Preferir crates puros (`shiguredo_mp4` + `windows-capture`) o asumirlo explícito |
| TD-5 | Invoke JSON de Tauri serializa a strings | Cuello de botella para frames binarios | IPC binario/custom protocol/WS para preview; no `invoke` JSON |
| TD-6 | Sufijo `-<target-triple>` del sidecar | Bundle roto por arquitectura si falta | Automatizar el naming en `build.ps1`/CI |
| TD-7 | Scrub frame-exact impreciso en `<video>` | UX de marcado del editor degradada | Frames server-side o WebCodecs; export ya server-side |
| TD-8 | Scaffold Rust `watcher_segments` sin probar (`ENGINE_READY=false`, dev box sin cargo) | Track R parte de algo no validado (riesgo F7) | Prerequisito R1: toolchain + spike de paridad + owner Rust |

## Fuentes (23 fetched; principales)
Docs oficiales Tauri v2 (sidecar, capabilities, updater), `tauri-specta`, `TauRPC`, `tauri-action`;
`windows-capture`, `shiguredo_mp4`, `ffmpeg-next` (lib.rs), `maturin`; StaZhu/enable-chromium-hevc,
web.dev/rvfc, w3c/media-and-entertainment#4, remotion media-parser; discusiones Tauri #15171/#5690,
wry#1110; benchmarks tauri-conduit; ejemplos python-server-sidecar y pytauri.

## Relacionado
- [Explicación](explanation-tauri-migration.md) · [Referencia](reference-target-architecture.md) · [Gate F0](howto-f0-gate.md) · [ADRs](../editing/adr/README.md)
