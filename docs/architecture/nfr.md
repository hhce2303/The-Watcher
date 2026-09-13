# Requisitos no funcionales — proyecto completo

> Complementa los `R-NF*` de [`goals.md`](goals.md) (*scoped* al tab de edición): este
> documento cubre NFRs de **todo el producto** — grabación, IPC, empaquetado,
> observabilidad. IDs estables `NFR-<área>-N`, referenciados desde [ADRs](adr/),
> `TODOS.md` (raíz) y commits. Términos: ver [`glossary.md`](glossary.md).
>
> Estado: vivo · Fecha: 2026-09-13

---

## 1. Rendimiento y gobernanza de recursos

| ID | Requisito | Métrica / objetivo | Estado / evidencia |
|----|-----------|---------------------|---------------------|
| **NFR-Perf-1** | CPU de captura por monitor dentro de SLA | ≤5% de CPU/monitor | ✅ Verificado en esta máquina: 1.06–1.19% (16 hilos) con zero-copy QSV — [ADR-0017](adr/ADR-0017-adr0007-sla-verdict-confirmed.md). **Pendiente**: confirmar en flota real con pocos núcleos/sin QSV-NVENC (la cola de riesgo) antes de dar el gate por cerrado en todas las estaciones. |
| **NFR-Perf-2** | Concurrencia de FFmpeg batch acotada | Como máximo `MAX_BATCH_FFMPEG` procesos FFmpeg *offline* vivos a la vez, sin importar cuántos monitores disparan builds simultáneos | ✅ Semáforo global + Job Object compartido — [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md) |
| **NFR-Perf-3** | Prioridad relativa batch vs. grabador | Los procesos FFmpeg batch corren en `BELOW_NORMAL_PRIORITY_CLASS`; el grabador nunca se ve forzado a ceder CPU por un *hard cap* | ✅ Verificado con `psutil.Process.nice()` — [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md) |
| **NFR-Perf-4** | Techo de memoria del Job batch | `JobMemoryLimit` configurable (`BATCH_JOB_MEMORY_LIMIT_MB`, default 1536 MB) | ⚠️ **Riesgo abierto** — validado solo por configuración aplicada (log + `SetInformationJobObject` sin error), **no forzando un OOM real**. Enforcement bajo presión de memoria real queda pendiente de despliegue piloto. Ver [`TODOS.md`](../../TODOS.md) (§ Gobernanza de recursos — riesgos abiertos). |
| **NFR-Perf-5** | El grabador no tiene techo de recursos por diseño | El proceso de grabación (`RecorderPort`) **deliberadamente no** entra al Job batch ni a ningún *hard cap* de CPU — un *hard cap* congelaría hilos al agotar el presupuesto del intervalo, lo cual es peor que dejarlo correr | ✅ Decisión consciente, no un descuido — [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md) §Contexto. **Trade-off aceptado**: bajo carga extrema (muchos monitores + eventos simultáneos) el grabador puede consumir CPU sin límite superior; el único freno indirecto es la prioridad `BELOW_NORMAL` del resto de procesos batch. |
| **NFR-Perf-6** | Latencia de compilación de segmentos | Remux/concat sin pérdida notablemente más rápido que el re-encode equivalente (dominado por I/O, no CPU) | 🟦 Medido a nivel R-NF2 de [`goals.md`](goals.md); benchmark formal pendiente sobre reel de ~5 min |
| **NFR-Perf-7** | Latencia y CPU de la preview en vivo | ≤1 s de latencia, ≤5% CPU/monitor | 🟦 Gate F0 — decidido usar WS binario/MJPEG, no invoke JSON de Tauri (TD-5, [`tech-debt-and-best-practices.md`](../migration/tech-debt-and-best-practices.md)) |

## 2. Confiabilidad y resiliencia

| ID | Requisito | Métrica / objetivo | Estado / evidencia |
|----|-----------|---------------------|---------------------|
| **NFR-Rel-1** | Detección de proceso *hung-but-alive* | El watchdog de SO solo relanza en salida del proceso (crash/kill); un proceso vivo pero congelado no se detecta hoy | ⚠️ **Riesgo abierto** — `TODOS.md` #1 (hang/liveness detection). Mitigado parcialmente en el recorder por `RecorderSupervisor`; el caso de *full-app freeze* sigue sin cobertura. |
| **NFR-Rel-2** | Cero huérfanos de procesos FFmpeg batch | Todo proceso FFmpeg *offline* (converter, analyzer, builders) se asigna a un Job con `KILL_ON_JOB_CLOSE` | ✅ Cerrado en [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md) (antes, `mp4_converter_adapter.py` y `batch_clip_analyzer.py` corrían fuera de cualquier Job) |
| **NFR-Rel-3** | Nunca concatenar segmentos incompatibles | Se respeta `segment_floor` de `buffer_manager.py`; jamás se mezclan segmentos de configuraciones de monitor distintas | Corresponde a R-NF5 de [`goals.md`](goals.md) |
| **NFR-Rel-4** | Shutdown correcto del sidecar PyInstaller | `process.kill()` no basta (solo mata el bootloader) — shutdown por comando stdin/stdout | ✅ Decisión — TD-3, ADR-0010. Test de ciclo de vida obligatorio en F1. |
| **NFR-Rel-5** | Auto-eventos no deben fallar en silencio | Un fallo de build de clip automático debe loguearse y reintentarse, no morir en un hilo sin manejo de excepciones | ✅ [ADR-0019](adr/ADR-0019-auto-event-clip-build-coalescing.md) — antes fallaba silenciosamente dentro de un hilo *timer* sin log alguno |
| **NFR-Rel-6** | Telemetría de procesos nunca rompe la grabación | Un error de `psutil` o un PID inválido en `ProcTelemetry` se traga silenciosamente | ✅ Decisión deliberada (best-effort) — [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md). **Contrapartida**: si la telemetría falla silenciosamente de forma sostenida, un abuso de recursos real podría pasar sin alerta — no hay hoy un umbral que escale a log de advertencia/incidente. |

## 3. Seguridad

| ID | Requisito | Métrica / objetivo | Estado / evidencia |
|----|-----------|---------------------|---------------------|
| **NFR-Seg-1** | Canal IPC local autenticado, nunca TCP loopback abierto | Named pipe *scoped* al usuario o token build-time | ✅ [ADR-0011](adr/ADR-0011-local-ipc-security.md) |
| **NFR-Seg-2** | El `IT_PIN` por defecto es un riesgo conocido | El default `"1234"` solo dispara una advertencia en arranque; no cambia comportamiento | ⚠️ **Riesgo abierto** — `TODOS.md` #10. Requiere decisión explícita (quitar el default con `None`-check, forzar set-up en primer uso, o aceptar el warning-only). |
| **NFR-Seg-3** | Auditoría de comandos sensibles | Todo intento de desbloqueo IT / cambio de rol se audita con origen + timestamp | ✅ `AuditPort` — [ADR-0011](adr/ADR-0011-local-ipc-security.md) |
| **NFR-Seg-4** | Preview HTTP solo localhost | El servidor de preview no debe exponerse a LAN | ✅ Regla activa — `AGENTS.md` (raíz) |
| **NFR-Seg-5** | Autorización identidad-a-identidad para `LiveViewPort` | Definir quién puede ver a quién (Supervisor↔Operador) antes de habilitar en flota real | ⚠️ **Riesgo abierto, hard gate** — `TODOS.md` #9. Hoy `RequestsApi.send_clip_request` no valida ninguna relación; cualquier Supervisor podría solicitar ver a cualquier Operador. |
| **NFR-Seg-6** | Capabilities Tauri default-deny | Superficie webview→Rust mínima, sin remoto | 🟦 Cheat-sheet en `CLAUDE.md` (raíz); verificar en `tauri.conf.json` antes de cada release |

| **NFR-Seg-7** | Canal navegador↔daemon local de mínimo privilegio | TLS sólo en loopback; `frame-ancestors` de origen exacto; assertion Ed25519 de 60 s/un uso; sesión en memoria ≤5 min; capabilities de media ≤30 s; nunca IPC Tauri/LAN | ✅ Implementado con `adapters/browser_local`; despliegue piloto condicionado a CSP de Daily, Edge Function y certificado mkcert. Ver [ADR-0020](adr/ADR-0020-browser-local-daily-channel.md). |

## 4. Empaquetado y portabilidad

| ID | Requisito | Métrica / objetivo | Estado / evidencia |
|----|-----------|---------------------|---------------------|
| **NFR-Pack-1** | Degradación elegante sin el motor Rust | Si falta el `.pyd`, la app arranca igual con *fallback* FFmpeg | Corresponde a R-NF4 de [`goals.md`](goals.md) |
| **NFR-Pack-2** | Sufijo `-<target-triple>` del sidecar | El bundle no debe romperse por arquitectura si falta el sufijo | ⚠️ TD-6 — automatizar en `build.ps1`/CI |
| **NFR-Pack-3** | CI/release del instalador Tauri + módulo Rust nativo | Pipeline reproducible (MSI/NSIS vía `tauri-action`) | ⚠️ **No existe aún** — `TODOS.md` #4. `.github/workflows/` está vacío para esta parte. |

## 5. Observabilidad

| ID | Requisito | Métrica / objetivo | Estado / evidencia |
|----|-----------|---------------------|---------------------|
| **NFR-Obs-1** | Telemetría de CPU/RSS por proceso trackeado | Muestreo periódico (`PROC_TELEMETRY_INTERVAL_SECONDS`, default 10 s) logueado estructurado | ✅ `proc_telemetry.py` — [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md) |
| **NFR-Obs-2** | Estado degradado del watchdog visible para IT | Si el registro del *scheduled task* falla y cae a `HKCU Run`, IT debe enterarse (no solo un log local) | ⚠️ **Riesgo abierto** — `TODOS.md` #2. Hoy solo se loguea; ni el tray de Rust ni la UI lo muestran. |
| **NFR-Obs-3** | Cobertura de test del *shell* React/Rust | La lógica de mayor riesgo (editor/export frame-exact, comandos Tauri) debe tener tests, no solo el backend Python | ⚠️ **Riesgo abierto** — `TODOS.md` #5/#6. ~55% de cobertura ponderada por riesgo al cierre de F1-F3; 38 de 39 archivos React nuevos y la capa `src-tauri/src/{commands,policy,tray,lib}.rs` sin test. |

## 6. Pureza arquitectónica

| ID | Requisito | Métrica / objetivo | Estado / evidencia |
|----|-----------|---------------------|---------------------|
| **NFR-Core-1** | `app/core/` no importa infraestructura | Ni Qt, ni FFmpeg, ni Rust, ni torch — verificable por inspección + tests sin dependencias gráficas | Corresponde a R-NF3 de [`goals.md`](goals.md); regla reforzada en `AGENTS.md` (raíz) |
| **NFR-Core-2** | `core/api` es el único puerto de entrada | Toda UI (named-pipe IPC hoy) es un adaptador intercambiable sobre `ApiLayer` | [ADR-0009](adr/ADR-0009-input-port-facade.md) |

---

## Notas sobre "abuso de recursos" (contexto para este documento)

Este proyecto **ya tiene** gobernanza de recursos parcial para el camino batch
(NFR-Perf-2/3/4, [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md)) y para el ciclo de
vida de procesos (NFR-Rel-2/4). Los huecos conocidos y **no fabricados** — todos trazables
a evidencia ya escrita en el repo — son:

1. El techo de memoria del Job batch (NFR-Perf-4) nunca se probó bajo presión real de OOM.
2. El grabador es intencionalmente **sin techo** de CPU/memoria (NFR-Perf-5) — una decisión
   consciente, pero sigue siendo la superficie más grande de abuso de recursos posible si algo
   sale mal en el pipeline de captura.
3. La telemetría de procesos es best-effort y traga errores en silencio (NFR-Rel-6) — puede
   enmascarar un problema de recursos real sin alertar a nadie.
4. No hay detección de *hang* a nivel de app completa (NFR-Rel-1), solo del recorder individual.
5. El estado degradado del watchdog no llega a IT salvo por log de archivo (NFR-Obs-2).

Ver la entrada correspondiente en [`TODOS.md`](../../TODOS.md) (raíz del repo,
sección "Gobernanza de recursos — riesgos abiertos") para el registro de seguimiento con
disparadores concretos.
