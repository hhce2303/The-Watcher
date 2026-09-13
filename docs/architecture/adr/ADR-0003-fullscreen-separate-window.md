# ADR-0003 — Fullscreen en ventana propia con reparent del videoOutput

- **Estado**: Aceptado
- **Fecha**: 2026-06-22
- **Requisitos**: R-4, R-NF1

## Contexto

El requisito es ver el clip a pantalla completa **sin perder calidad**. Opciones:

1. **Maximizar el panel** del editor y escalar el `VideoOutput` dentro de la misma ventana → la
   imagen se escala dentro de un layout pensado para tamaño reducido; tiende a artefactos.
2. **Ventana propia** (`Window { visibility: Window.FullScreen }`) a la resolución nativa del monitor.
   Dentro, dos sub-opciones: (2a) un **segundo `MediaPlayer`** sincronizado → doble decodificación y
   riesgo de desincronía; (2b) **reparentar el `videoOutput`** del único `MediaPlayer` existente a la
   ventana fullscreen mientras está activa y restaurarlo al salir.

## Decisión

Opción **(2b)**: ventana propia a resolución nativa + **reparent del `videoOutput`** del player ya
inicializado. Reusa el patrón de ventana separada de `MiniMode.qml`. Toggle por botón + teclas F/ESC.

## Consecuencias

- ✅ Sin doble decodificación ni desincronía: hay un solo `MediaPlayer`.
- ✅ Render a resolución nativa del monitor (escalado por GPU vía RHI/D3D11) → sin pérdida hasta la
  resolución de origen.
- ✅ Respeta el *pitfall* de Qt: `addLibraryPath()` ya se ejecutó antes del primer `MediaPlayer`; la
  ventana fullscreen no instancia uno nuevo.
- ➖ Hay que gestionar el ciclo de vida del reparent (restaurar el `videoOutput` al cerrar fullscreen,
  incluso si la ventana se cierra de forma inesperada).
