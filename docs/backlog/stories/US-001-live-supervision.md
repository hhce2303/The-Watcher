# US-001: Ver estado y pantalla de un operador
- **Epic:** EPIC-001
- **Feedback origin:** FB-001
- **Related ADR:** ADR-0021
- **As a** Supervisor, **I want** consultar el heartbeat de los equipos Operator y abrir un monitor, **so that** pueda verificar la operación sin intervenir la estación.

## Acceptance criteria

```gherkin
Scenario: Supervisor consulta la flota
  Given a Supervisor autenticado en Daily
  When abre Supervisión de The Watcher
  Then ve cada dispositivo enrolado con última señal, grabación, salud y monitores

Scenario: Supervisor abre una pantalla autorizada
  Given un Operator online y un Supervisor autorizado
  When el Supervisor selecciona uno de sus monitores
  Then recibe una vista MJPEG LAN de solo lectura a 8–10 fps
  And no recibe rutas de clips ni controles remotos

Scenario: Límite de observadores
  Given tres sesiones activas para un Operator
  When un cuarto Supervisor intenta abrir un monitor
  Then el daemon rechaza la sesión y Daily muestra la causa
```

- **Priority:** MoSCoW: Must
- **Status:** in-progress
