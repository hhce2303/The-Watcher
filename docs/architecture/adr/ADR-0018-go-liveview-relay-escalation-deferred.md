# ADR-0018 — Go como ruta de escalación para el relay de LiveViewPort: diferido

- **Estado**: Diferido (Python ahora vía `LiveViewPort`; Go queda documentado como escalación futura)
- **Fecha**: 2026-07-12
- **Origen**: `/office-hours` + `/autoplan` — diseño de "Live LAN Screen Viewing for Supervisors" (rama `feat/f1-backend-headless`)
- **Extiende**: [ADR-0009](ADR-0009-input-port-facade.md) (Facade/DTO), [ADR-0012](ADR-0012-rust-hexagon-endgame.md) (un solo lenguaje dueño del hexágono)

## Contexto

`LiveViewPort` (nuevo puerto hexagonal) da a Supervisor una vista en vivo, solo-lectura,
LAN-only, de la pantalla de un Operador — cerrando una brecha de paridad con IT (que ya
tiene acceso vía TeamViewer). Durante el diseño se propuso Go (con Pion, la librería
WebRTC pura-Go) como lenguaje para la pieza de networking/relay, dado su rendimiento
probado en streaming de video en tiempo real.

Investigación externa confirmó que la ventaja real de Go (goroutines superando a
`asyncio` en concurrencia, NAT traversal/TURN de Pion) está probada en el régimen de
**miles a millones** de conexiones simultáneas (Twitch migró su capa de transcoding a Go
en 2024: −65% memoria, 3x throughput, 100,000+ streams concurrentes) — cuatro órdenes de
magnitud por encima de la escala real de esta feature (single dígitos a bajas decenas de
sesiones **company-wide**, no por Operador; LAN plana, sin necesidad de NAT traversal,
que es exactamente donde vive la ventaja de Pion). Además, [ADR-0012](ADR-0012-rust-hexagon-endgame.md)
ya compromete al proyecto a **un solo lenguaje** dueño del hexágono a futuro (Rust vía
PyO3, no Go) — introducir Go ahora sería un tercer stack de lenguaje sin justificación
técnica en la escala actual.

## Decisión

**Diferir Go.** `LiveViewPort` se implementa en Python ahora (nuevo puerto, patrón
Facade/DTO de ADR-0009), consistente con el compromiso de un solo lenguaje de ADR-0012.
Go **no** se descarta permanentemente — queda documentado como ruta de escalación,
reconsiderable **solo si** se cumple uno o más de estos triggers concretos:

1. **Acceso fuera de la LAN corporativa** (internet-wide) — ahí sí aparece el problema
   real de NAT traversal/TURN que Pion resuelve y Python no tiene equivalente.
2. **El conteo de viewers concurrentes crece en órdenes de magnitud** — de single-dígitos
   company-wide a cientos o más.
3. **La feature crece a control remoto real** (no solo vista) — trae la maquinaria de
   data-channels/input-injection de WebRTC, que cambia el perfil de riesgo lo suficiente
   como para justificar un servicio de relay dedicado.
4. **Hay un owner con experiencia real en Go** dispuesto a cargar con un segundo runtime —
   sin esto, el costo de mantenimiento (dos runtimes, dos ecosistemas de dependencias) no
   se justifica por ninguno de los triggers anteriores por sí solo.

## Consecuencias

- ✅ No se añade un tercer lenguaje al hexágono antes de que haga falta; `LiveViewPort`
  entra en Python detrás del Facade existente, consistente con ADR-0012.
- ✅ Existen triggers concretos y falsables — la próxima vez que "¿deberíamos usar Go
  aquí?" salga a la mesa, se revisa este ADR primero en vez de re-litigar desde cero.
- ➖ Si algún trigger se cumple, la capa de relay LAN construida ahora (Python,
  `websockets`/`asyncio`) no es reusable tal cual para una ruta Go/Pion — sería una
  reescritura de la capa de relay, no un paso incremental (aunque el límite de
  puerto/Facade/DTO por encima se mantiene estable, por ADR-0009).
- ➖ Si un trigger se cumple, Go vs. un port a Rust (el destino final de todo puerto,
  por el endgame de ADR-0012) deben evaluarse uno contra el otro, no asumir Go por
  default — la ventaja real de Go (madurez WebRTC/TURN de Pion) tendría que pesarse
  contra el compromiso de un solo lenguaje de ADR-0012 en ese momento, no diferirse
  automáticamente hacia Go.
- 🔁 Cuando se retome (si algún trigger se cumple), será un ADR nuevo que supersede el
  estado "Diferido" de este, con el trigger específico documentado y una evaluación
  Go-vs-Rust explícita.

## Relacionado
- [Matriz de tecnología por puerto](../../migration/reference-target-architecture.md#matriz-de-tecnología-por-puerto-destino-rust--track-r) — `LiveViewPort` añadido como nuevo puerto, sin secuenciar aún en Track R.
