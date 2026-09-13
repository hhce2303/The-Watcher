# Spec kit — The Watcher

Especificación viva del producto a partir del código y la documentación revisados el **2026-09-13**. Sirve para orientar cambios, revisiones y nuevas implementaciones sin tener que reconstruir el contexto desde cero.

## Orden de confianza

1. Código ejecutable, pruebas y configuración CI.
2. Contratos en `project/app/core/api/dto.py`, `project/app/adapters/ipc/router.py`, `src/lib/ipc.ts` y `src/types/dto.ts`.
3. Este kit y los README actuales.
4. ADRs y documentos de migración: explican decisiones y restricciones, pero algunos describen estados transitorios ya terminados.

En particular, QML/PySide6 ya no existe. Tampoco existe `core/api/facade.py`: el puerto de entrada actual es `ApiLayer` y sus APIs especializadas. Si un documento antiguo afirma lo contrario, es contexto histórico, no una instrucción de implementación.

## Índice

| Documento | Pregunta que responde |
|---|---|
| [01-product-and-roles.md](01-product-and-roles.md) | ¿Qué problema resuelve y qué puede hacer cada rol? |
| [02-architecture-and-runtime.md](02-architecture-and-runtime.md) | ¿Cómo se construye, arranca y se conectan los procesos? |
| [03-functional-spec.md](03-functional-spec.md) | ¿Cuáles son los flujos y resultados funcionales? |
| [04-contracts-and-data.md](04-contracts-and-data.md) | ¿Cuáles son los contratos IPC, multimedia y datos persistidos? |
| [05-quality-operations-and-change-guide.md](05-quality-operations-and-change-guide.md) | ¿Qué restricciones, pruebas, riesgos y pasos de cambio aplican? |

## Fuentes primarias útiles

- `project/app/main.py`: composition root y ciclo de vida completo.
- `project/app/runtime/backend.py`: construcción del stack por rol.
- `project/app/core/ports/`: fronteras hexagonales.
- `project/app/core/api/`: único puerto de entrada al core.
- `project/app/adapters/ipc/`: pipe autenticado y router de comandos.
- `src-tauri/src/`: shell, ciclo de sidecar, seguridad de media y tray.
- `src/`: UI React, hooks y store.
- `project/.env.example`: referencia completa y comentada de configuración.
- `docs/architecture/adr/`: decisiones arquitectónicas durables.

## Alcance y estado

The Watcher es una aplicación de escritorio **solo Windows** para grabación continua de pantalla, generación de clips de evidencia y revisión/entrega de esos clips. Su release versionada es `0.1.0`; `CHANGELOG.md` documenta cambios posteriores no liberados. La UI vigente es Tauri 2 + React; Python continúa como backend headless y Rust se usa tanto en la shell como en el motor nativo opcional de segmentos.

