# ADR-0026 — Pasos de campo del piloto como scripts versionados instalados con el daemon

- **Estado**: Aceptado (piloto `file`)
- **Fecha**: 2026-10-04
- **Requisitos**: NFR-Seg-4, NFR-Seg-5
- **Relacionado**: [ADR-0021](ADR-0021-supervision-lan-live-view.md),
  [ADR-0025](ADR-0025-persistent-pilot-ca-in-github-secret.md)

## Requisitos

- Desplegar una estación no debe exigir editar, pegar ni adaptar scripts en la máquina.
- La regla de entrada 8767 debe aplicar en estaciones unidas al dominio `sig.com`.
- El enrolamiento en Daily no debe exponer la clave privada del dispositivo.

## Contexto

En los despliegues de COPERATOR03 y COPERATOR08 los dos pasos manuales fallaron de formas repetidas:

- El instalador creaba la regla con `netsh … profile=private`. Las estaciones están en dominio (perfil Domain),
  así que la regla no aplicaba, y cada reinstalación la duplicaba (B-21).
- El script de firewall de la guía se pegaba en la consola (rompía el pegado multilínea), se editaba por estación
  y resolvía el `.exe` con `$env:LOCALAPPDATA`, que al elevar con la cuenta de IT apunta a otro perfil.
- Un `.ps1` UTF-8 sin BOM se leía en PowerShell 5.1 como ANSI y corrompía los mensajes.
- El enrolamiento dependía de un bloque PowerShell copiado de la guía y de teclear el `station_id` a mano.

## Decisión

1. Cada paso de campo es **un script versionado en `installer/`** con un lanzador `.cmd` de doble clic. `build.ps1`
   los copia junto al `.exe` y el instalador crea accesos directos en el menú Inicio:
   - `watcher-firewall.ps1` / `Configurar firewall.cmd`;
   - `watcher-enrollment.ps1` / `Datos de enrolamiento.cmd`.
2. Los scripts **no tienen parámetros por estación**: leen la configuración del `.env` instalado y resuelven
   rutas desde su propia carpeta (`$PSScriptRoot`), nunca desde `$env:LOCALAPPDATA`.
3. Firewall: entrada TCP 8767 en **Domain y Private**, nunca Public; salida TCP 443 sólo para `The Watcher.exe`.
   El script se autoeleva, borra y recrea únicamente sus reglas (idempotente) y avisa de red Public y de reglas
   Block sobre 8767. El instalador lo invoca en lugar de `netsh`.
4. Enrolamiento: el script sólo selecciona `device_id` y `public_key_pem` del archivo de identidad y entrega el
   bloque del formulario de Daily (con `station_id` del `.env`) en pantalla y portapapeles. No pide admin.
5. Los scripts se guardan en UTF-8 con BOM.
6. `tests/test_installer_firewall.py` y `tests/test_installer_enrollment.py` fijan estas reglas estáticamente.

## Consecuencias

- El procedimiento de campo se reduce a: instalar, aceptar un UAC, doble clic en "Datos de enrolamiento", pegar en
  Daily. Los mismos accesos directos sirven para reparar después.
- Las estaciones instaladas antes de este cambio no tienen los accesos directos: se copian los cuatro archivos o se
  reinstala.
- El comportamiento real de los scripts es Windows-only; los tests sólo cubren su forma (V-11).
- El `endpoint_name` sigue siendo una decisión de quien construye el instalador; la guía permite la IP cuando el
  DNS no es fiable, a costa de depender de una reserva DHCP.

## Opciones no elegidas

- **Mantener el script en la guía para pegar**: es lo que falló; cada estación terminaba con una variante distinta.
- **Ejecutar todo el instalador elevado**: resolvería el firewall, pero instalaría en el perfil del administrador
  (`PrivilegesRequired=lowest` existe por eso).
- **GPO de firewall por IT**: es lo correcto a escala, pero no depende de este repositorio ni está disponible en el
  piloto. El script no lo impide.
- **Enrolamiento automático contra Daily desde el daemon**: requiere un flujo de aprobación en Daily que aún no
  existe; un registro sin aprobación humana rompería el modelo de confianza de ADR-0021.
