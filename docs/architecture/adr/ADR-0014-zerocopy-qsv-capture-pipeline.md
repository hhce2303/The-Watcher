# ADR-0014 — Pipeline de captura zero-copy (D3D11→QSV/CUDA) tras `ddagrab`

- **Estado**: Aceptado
- **Fecha**: 2026-07-05
- **Relación**: implementa el PoC-1 de
  [ffmpeg-pipeline-optimization-research.md](../../migration/ffmpeg-pipeline-optimization-research.md#8-plan-de-poc)
  (investigación `/deep-research` sobre consumo de CPU del pipeline FFmpeg). Se apoya en
  [ADR-0013](ADR-0013-ddagrab-capture-cursor-flicker.md) (ddagrab/DXGI), cuya sección de
  consecuencias dejaba el zero-copy explícitamente pendiente.

## Contexto

El pipeline `ddagrab` (ADR-0013) hace `hwdownload,format=bgra` en cada frame — copia GPU→RAM
antes de escalar por software y volver a subir a hardware para el encode. La investigación
`/deep-research` midió esto en la máquina de referencia (Intel Iris Xe, FFmpeg 8.1-full):
**0.68 núcleos/monitor** con `hevc_qsv`, contra **0.21-0.23 núcleos** manteniendo los frames en
GPU con `hwmap`+`vpp_qsv` (−66%). El SLA (≤5% CPU/monitor) solo se cumplía hoy en máquinas de
≥14 hilos; con zero-copy se cumple desde ~5 hilos.

## Decisión

Añadir `CAPTURE_PIPELINE=auto|zerocopy|legacy` (default `auto`) a `FFmpegRecorderAdapter`,
ortogonal a `CAPTURE_BACKEND`:

- Solo aplica cuando el backend resuelto es `ddagrab` **y** el encoder resuelto tiene una ruta
  GPU documentada: `*_qsv` → `hwmap=derive_device=qsv,vpp_qsv=...`; `*_nvenc` →
  `hwmap=derive_device=cuda,scale_cuda=...`. AMF y los encoders de software se quedan siempre en
  `legacy` (no existe ruta `hwmap` para ellos aquí).
- **Probe por monitor** (`_zerocopy_available`, memoizado por `family:monitor.index`): captura 2
  frames a `-f null` con el filtergraph real antes de confiar en él. Cubre el caso iGPU+dGPU
  (monitor en un adaptador distinto al del encoder resuelto) sin necesitar detección explícita de
  topología — si `hwmap` falla, se degrada.
- `auto` intenta zero-copy y cae a `legacy` si el probe falla; `zerocopy` lo fuerza pero conserva
  el mismo probe+fallback (nunca deja el grabador sin arrancar); `legacy` lo desactiva sin probar.
- `-async_depth 1` en el encoder QSV (validado sin efecto en CPU, reduce ~8% RAM por proceso).

**Corrección encontrada durante la validación de este ADR** (no prevista en la investigación):
`vpp_qsv` sin `out_range` explícito produce salida **full-range** (`yuvj420p`) porque los frames
D3D11 de ddagrab ya son full-range — mientras que el pipeline legacy (`scale` de CPU) normaliza a
**limited-range** (`yuv420p`) por defecto de `libswscale`. Sin corrección, esto habría dejado
segmentos zero-copy con rango de color distinto a los legacy: un salto de brillo visible si algún
día se concatenan sin pérdida segmentos de ambos tipos (cambio de topología GPU, reinicio del
supervisor con probe distinto, etc.). Fix: `vpp_qsv=...:out_range=tv`, verificado con `ffprobe`
(`pix_fmt=yuv420p`, `color_range=tv`, igual que legacy byte a byte en metadata).

Ruta NVENC/CUDA: `scale_cuda` no tiene opción de rango documentada; queda marcado en código para
que quien valide en una RTX real repita el mismo chequeo de paridad de color.

## Validación

Máquina de referencia (Intel Iris Xe, FFmpeg 8.1, `hevc_qsv`), a través de la clase real
`FFmpegRecorderAdapter` (no un script de benchmark aparte):

- `auto` resuelve a `zerocopy`, comando generado, arranque limpio, watchdog/supervisor sin tocar.
- Segmentos `.ts` válidos (`ffprobe`: hevc, Main, 1920x1080, 30fps, `yuv420p`/`tv` — idéntico a
  legacy salvo el fix de arriba), tamaño comparable a legacy en la misma ventana. `preview.jpg`
  vivo a 2 fps.
- CPU (`psutil`, 12 muestras/variante): legacy ~1.06 núcleos, zero-copy ~0.26 núcleos (**−75%**,
  supera el gate de "≤⅓ del actual").
- Suite pytest completa verde (516 passed) + 12 tests nuevos para resolución de pipeline,
  fallback por probe fallido, y la regresión de `out_range`.

## Consecuencias

- ✅ Cumple el gate de PoC-1: CPU/monitor muy por debajo de ⅓ del actual, sin tocar `core/`.
- ✅ Rollback trivial: `CAPTURE_PIPELINE=legacy` o fallback automático por probe; mismo binario
  FFmpeg, mismo formato de segmento — el compilador Rust de segmentos y el concat lossless no se
  enteran.
- ➖ La variante NVENC/CUDA no está validada en hardware real (no hay GPU NVIDIA en la máquina de
  referencia) ni tiene paridad de color-range confirmada — el probe la protege (cae a legacy si
  falla), pero el PoC-1 gate de RTX sigue abierto.
- 🔁 Deja lista la telemetría/comportamiento que alimenta el PoC-2 (gobernanza Job Objects) y el
  gate de profiling de ADR-0007 (§7 de la investigación).
