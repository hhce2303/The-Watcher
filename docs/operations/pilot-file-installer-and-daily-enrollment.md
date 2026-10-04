# Piloto `file`: despliegue estándar de una estación

> **Estado: piloto cerrado (2026-10-04).** Procedimiento validado de extremo a
> extremo en COPERATOR02 y COPERATOR08. Siguiente: integrar en `main` y
> reenrutar el CI (el workflow dejará de depender de
> `feat/extract-daemon-from-monorepo`); después, depuración del sistema de
> grabación.

## Propósito y alcance

Procedimiento único para desplegar The Watcher en una estación Windows Operator
del piloto y verla desde Daily. Está dirigida a IT, a quien instala en la
estación y a los supervisores. Cada paso de campo es un **doble clic** sobre un
script versionado; nada se copia y pega ni se edita a mano
([ADR-0026](../architecture/adr/ADR-0026-standard-field-steps-as-installed-scripts.md)).

**Modo piloto `TLS_PROVISIONING_MODE=file` con mkcert.** No es el flujo futuro
`remote` con broker + step-ca de ADR-0024. Todas las estaciones se firman con
**una única CA de piloto persistente**
([ADR-0025](../architecture/adr/ADR-0025-persistent-pilot-ca-in-github-secret.md)):
el instalador lleva sólo la clave *leaf* de su estación y la CA **pública** se
entrega aparte. Cada supervisor la importa **una sola vez**.

## Resumen: el estándar en 7 pasos

| # | Dónde | Quién | Acción | Resultado esperado |
| --- | --- | --- | --- | --- |
| 0 | Estación | IT | Recoger hostname, IP y comprobar DNS (§0) | `station_id`, `endpoint_name`, IP decididos |
| 1 | GitHub | IT | Ejecutar **Build pilot installer** (§1) | Run verde, huella CA `C0:C6:…:D9:F3` |
| 2 | Estación | Operator + IT | Doble clic en `Setup-The Watcher.exe`; IT acepta UAC (§2) | Avisos de firewall: ninguno |
| 3 | Estación | Operator | Inicio → **Datos de enrolamiento de The Watcher** (§3) | Bloque copiado al portapapeles |
| 4 | Daily | Admin Daily | Pegar el bloque en **Dispositivos Watcher** (§4) | Estación EN LÍNEA en 30–90 s |
| 5 | PC Supervisor | Supervisor | Importar la CA del piloto, una vez en la vida (§5) | Sin aviso de certificado |
| 6 | Daily | Supervisor | Abrir la vista LAN de la estación (§6) | Se ven los monitores |

Al terminar: **borrar toda copia del instalador** (lleva la clave *leaf*) y
anotar la estación en el [registro](#registro-de-estaciones-del-piloto).

## Roles

| Rol | Responsabilidad |
| --- | --- |
| IT / Release manager | Recoge los datos, ejecuta el workflow, introduce la credencial de administrador en el UAC del firewall y borra las copias del instalador. |
| Operator | Ejecuta el instalador y el script de enrolamiento con su sesión normal. No edita `.env` ni maneja certificados. |
| Administrador Daily | Registra el dispositivo con el bloque de enrolamiento y lo deja activo. |
| Supervisor | Importa una vez la CA pública y abre la vista desde Daily. |

## 0. Recoger los datos de la estación

En la estación, PowerShell normal:

```powershell
hostname
(Get-CimInstance Win32_ComputerSystem).Domain
Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -like '192.168.*' | Select-Object InterfaceAlias, IPAddress
```

Desde **un PC supervisor**, comprobar el nombre:

```powershell
Resolve-DnsName <hostname>.sig.com     # Linux: resolvectl query <hostname>.sig.com
```

Elegir el `endpoint_name` con esta regla:

| El DNS devuelve… | `endpoint_name` | Notas |
| --- | --- | --- |
| La IP actual de la estación | FQDN, p. ej. `coperator03.sig.com` | Preferido: sobrevive a cambios de IP. |
| Otra IP, o nada | La IP, p. ej. `192.168.101.107` | Pedir a IT una **reserva DHCP** para la MAC de la estación y la corrección del DNS (ver Incidencias). Reconstruir con el FQDN cuando se corrija. |

Nunca usar un alias inventado (`station-2`): da `DNS_PROBE_FINISHED_NXDOMAIN`.
La CA sólo firma `sig.com`, `localhost`, `127.0.0.1` y `192.168.0.0/16`.

| Campo del workflow | Ejemplo | Regla |
| --- | --- | --- |
| `station_name` | `48-coperator08` | `<estación>-<equipo>`; letras, números, `.`, `_`, `-`. Sólo es la etiqueta del artefacto. |
| `station_id` | `34` | ID numérico **de Daily**: el número **después de `#`** en `45 #34`. Nunca el número visible de estación (el 45), que puede ser el `station_id` de otra. |
| `endpoint_name` | `coperator03.sig.com` o `192.168.101.107` | Según la tabla anterior. Daily abrirá `https://<endpoint_name>:8767`. |
| `ip_addresses` | `192.168.101.107` | IP LAN actual. Siempre rellenarla: permite probar por IP aunque falle el DNS. |

## 1. Construir el instalador (GitHub Actions)

1. `hhce2303/The-Watcher` → **Actions** → **Build pilot installer (Windows)** →
   **Run workflow**, rama `feat/extract-daemon-from-monorepo`.
2. Introducir los cuatro valores de §0. Con `gh`:

   ```bash
   gh workflow run build-pilot-installer.yml --ref feat/extract-daemon-from-monorepo \
     -f station_name=48-coperator08 -f station_id=45 \
     -f endpoint_name=192.168.101.107 -f ip_addresses=192.168.101.107
   ```

3. Esperar el run verde (~5 min). Si falla en "Generate pilot profile" con
   `Secrets WATCHER_PILOT_CA_CERT and WATCHER_PILOT_CA_KEY are required`, faltan
   los secretos o la CA caduca en menos de 30 días: rotar según ADR-0025. El
   workflow nunca genera una CA de reemplazo.
4. Descargar los dos artefactos (se retienen siete días):
   - `the-watcher-pilot-installer-<station_name>` → `Setup-The Watcher.exe`
   - `the-watcher-pilot-supervisor-trust-<station_name>` → `watcher-pilot-rootCA.pem`
5. Verificar la **huella** de la CA (es la referencia; el hash del archivo puede
   variar por saltos de línea):

   ```bash
   openssl x509 -in watcher-pilot-rootCA.pem -noout -fingerprint -sha256
   ```

   ```text
   C0:C6:91:66:1C:41:90:8B:57:B3:A8:48:AB:94:CD:5C:9E:DE:6C:5C:8A:7B:C8:7D:94:7C:B4:01:A2:A7:D9:F3
   ```

   Otra huella: no distribuir. La CA se rotó o el artefacto no es el esperado.
6. Anotar el SHA-256 del instalador (`Get-FileHash` / `sha256sum`) y contrastarlo
   con el log del paso "Build field installer".

No extraer, versionar ni reenviar el contenido del instalador.

## 2. Instalar en la estación

1. Iniciar sesión con la **cuenta Windows del Operator** (la que ejecutará el
   daemon), no con la de IT.
2. Doble clic en `Setup-The Watcher.exe`. Destino por usuario:
   `%LOCALAPPDATA%\The Watcher`. No ejecutar el instalador como administrador.
3. Al final Windows pide UAC **una vez, sólo para el firewall**: IT introduce su
   credencial. El instalador ejecuta `watcher-firewall.ps1`:
   - sin mensaje: reglas creadas;
   - mensaje "red Public o regla que bloquea 8767": ejecutar
     **Inicio → Configurar firewall de The Watcher** y leer el `AVISO`;
   - mensaje "no se crearon las reglas" (UAC cancelado): repetir desde ese mismo
     acceso directo.
4. Aceptar iniciar The Watcher.
5. **Limpieza:** borrar el instalador de Descargas, USB, `C:\Users\Public`, el
   perfil de IT y el equipo que lo descargó.

El instalador importa la CA pública en `CurrentUser\Root` del Operator, conserva
la identidad del dispositivo (`browser_local\`) y **sobrescribe `.env` y
`certs\`** (B-21): reinstalar con otro instalador cambia endpoint y certificado.

### Accesos directos que deja el instalador

| Inicio → | Archivo en `%LOCALAPPDATA%\The Watcher\` | Pide admin | Para qué |
| --- | --- | --- | --- |
| Configurar firewall de The Watcher | `Configurar firewall.cmd` → `watcher-firewall.ps1` | Sí (se eleva solo) | Crear o corregir las reglas. Idempotente. |
| Datos de enrolamiento de The Watcher | `Datos de enrolamiento.cmd` → `watcher-enrollment.ps1` | No | Bloque público para registrar en Daily. |

Estaciones con un instalador anterior a estos scripts: copiar los cuatro
archivos de [`installer/`](../../installer/) a `%LOCALAPPDATA%\The Watcher\` y
hacer doble clic en el `.cmd`, o reinstalar con un instalador nuevo.

### Qué hace el script de firewall

| Regla | Dirección | Alcance |
| --- | --- | --- |
| `The Watcher Live View` | Entrada TCP 8767 | Perfiles **Domain y Private**. Nunca Public. |
| `The Watcher outbound Daily HTTPS` | Salida TCP 443 | Sólo `The Watcher.exe`; necesaria si la política bloquea la salida por defecto. |

- Borra y recrea sólo esas dos reglas: repetirlo no duplica y corrige reglas
  antiguas (los primeros instaladores creaban la de entrada sólo en Private, que
  no aplica a estaciones en dominio).
- Localiza el `.exe` junto al script o, si no está, por el proceso que escucha
  en 8767: funciona aunque IT eleve con su propia cuenta.
- Avisa si la red es **Public** o si una regla **Block** cubre 8767 (gana sobre
  la de permitir) e indica si el daemon escucha.
- Salida esperada: dos o tres `OK` en verde, ningún `AVISO`. Para retirar:
  `"Configurar firewall.cmd" -Remove`.

DNS y el tráfico de respuesta no necesitan reglas del daemon. Una lista
estricta de destinos HTTPS se aplica en el firewall corporativo, no con reglas
amplias en la estación.

### Comprobar desde otro PC

```powershell
Test-NetConnection <ip-estación> -Port 8767       # TcpTestSucceeded : True
```

```bash
curl --cacert watcher-pilot-rootCA.pem https://<endpoint_name>:8767/api/v1/health
```

Debe responder `status: "ok"` con un `device_id`. Probarlo en la propia estación
no sirve: el tráfico local no pasa por la regla de entrada.

## 3. Obtener los datos de enrolamiento (estación)

Con la sesión del Operator y The Watcher iniciado: **Inicio → Datos de
enrolamiento de The Watcher**. El script muestra y **copia al portapapeles**:

```text
=== The Watcher - enrolamiento en Daily ===
Daily -> Administración -> Dispositivos Watcher -> Crear/actualizar

device_id:      <UUID>
station_id:     45
Nombre visible: COPERATOR08 - Operator
Estado:         activo
public_key_pem:
-----BEGIN PUBLIC KEY-----
...
-----END PUBLIC KEY-----

Endpoint LAN:   https://192.168.101.107:8767
Equipo:         COPERATOR08  (CSOperator)
```

- `station_id` y `Endpoint LAN` salen del `.env` instalado. Si no son los
  esperados, el instalador era de otra estación: reconstruir, no editar `.env`.
- Sólo lee `device_id` y `public_key_pem`; la clave privada nunca se muestra.
  No abrir `device_identity.json` en un editor.
- "Aún no existe la identidad": iniciar The Watcher, esperar y repetir.

Enviar el bloque al canal de IT: sólo contiene datos públicos.

## 4. Registrar el dispositivo (Daily)

1. Daily como Admin o Lead Supervisor con `watcher.devices.manage` →
   **Administración → Dispositivos Watcher → Crear/actualizar**.
2. Copiar cada campo del bloque: `device_id`, `station_id`, nombre visible,
   `public_key_pem` completo (con `BEGIN`/`END`), estado **activo**.
3. **Comprobar la estación elegida:** Daily la muestra como `<número> #<station_id>`;
   el `#` debe ser el `station_id` del bloque. Si el `device_id` ya existe (la
   identidad sobrevive a reinstalaciones), revisar también su estación: un
   registro viejo con otro `station_id` provoca "Sesión rechazada o vencida".
4. **Un solo dispositivo activo por estación.** Si la estación ya tiene otro
   (pruebas anteriores, reinstalación con identidad nueva), desactivar el que no
   coincide con el `device_id` del bloque.
5. Guardar. En 30–90 s la estación aparece **EN LÍNEA** en el roster.

Reinstalar conserva la identidad: el registro sigue valiendo y basta con
comparar el `device_id`. Daily persiste por la RPC
`watcher_admin_upsert_device(device_id, station_id, display_name,
public_key_pem, active)`; nunca hacer `INSERT` directo en `watcher_devices`.

## 5. Confiar la CA del piloto (cada PC Supervisor, una vez)

El artefacto de confianza contiene sólo la CA **pública** y es el mismo para
todas las estaciones. Antes de importar, verificar la huella (§1.5).

**Windows** (sin administrador):

```powershell
Import-Certificate -FilePath "$HOME\Downloads\watcher-pilot-rootCA.pem" -CertStoreLocation 'Cert:\CurrentUser\Root'
```

**Linux (Brave, Chrome, Chromium)** usan la base NSS del usuario:

```bash
certutil -d sql:$HOME/.pki/nssdb -A -n watcher-pilot-ca -t "C,," -i watcher-pilot-rootCA.pem
certutil -d sql:$HOME/.pki/nssdb -L | grep watcher-pilot-ca     # debe decir C,,
```

Si sale `SEC_ERROR_TOKEN_NOT_LOGGED_IN`, la base tiene contraseña y la CA quedó
**sin confianza** (`,,`). Ejecutar en una terminal propia, que pedirá la contraseña:

```bash
certutil -d sql:$HOME/.pki/nssdb -M -n watcher-pilot-ca -t "C,,"
```

o `brave://settings/certificates` → Authorities → "The Watcher Pilot Root CA" →
Editar → confiar para sitios web. Firefox usa su propio almacén.

Cerrar **todas** las ventanas del navegador y reabrirlo. Las CA antiguas
(`watcher-test-ca`, `watcher-pilot-2-coperator03`, efímeras) **no** sirven para
estaciones nuevas; retirarlas sólo cuando sus estaciones se hayan reinstalado.

## 6. Validación de extremo a extremo

1. El roster de Daily muestra la estación **EN LÍNEA** (offline tras 90 s sin heartbeat).
2. Un Supervisor con `watcher.supervision.view` abre la vista LAN y ve los monitores.
3. F12 → Network → `embed`: `https://<endpoint_name>:8767/embed`, **200**, sin
   bypass de certificado.
4. Desactivar el dispositivo en Daily → la vista se rechaza (sin fallback).
5. Reactivarlo → vuelven los heartbeats y la vista.

## Registro de estaciones del piloto

| Estación | Equipo | `station_id` | `endpoint_name` | IP | Estado |
| --- | --- | --- | --- | --- | --- |
| 45 | COPERATOR02 | 34 | `coperator02.sig.com` | 192.168.101.191 | **Validada de extremo a extremo** con el procedimiento estándar. Run [37188130267](https://github.com/hhce2303/The-Watcher/actions/runs/37188130267). |
| 2 | COPERATOR03 | 29 | `coperator03.sig.com` | 192.168.101.106 | CA efímera previa a ADR-0025; reinstalar con instalador nuevo. |
| 30 | watcher-win | — | `192.168.101.147` | 192.168.101.147 | Vista verificada por IP. CA mkcert local. |
| 48 | COPERATOR08 | 45 | `192.168.101.107` | 192.168.101.107 | Vista verificada por IP. Run [37186570047](https://github.com/hhce2303/The-Watcher/actions/runs/37186570047). DNS `coperator08.sig.com` → 192.168.100.55 (NIC antigua): pendiente IT y reserva DHCP para MAC `FC-34-97-69-D3-E6`. |

## Incidencias

Primero mirar F12 → Network → fila `embed` → Request URL y estado.

| Síntoma | Causa | Acción |
| --- | --- | --- |
| `embed` en **(pending)** o `ERR_CONNECTION_TIMED_OUT` y el nombre resuelve a otra IP | Registro DNS viejo (otra NIC u otro equipo). | `Resolve-DnsName` frente a la IP real. En la estación `ipconfig /registerdns`; si no cambia, el registro pertenece a otro (DHCP): IT lo borra en el DNS de `sig.com` y se repite `/registerdns`. Deshabilitar NICs sin uso. Mientras tanto, usar la IP como `endpoint_name`. |
| `embed` en rojo **sin cabeceras de respuesta** y el iframe muestra el icono de página rota | El navegador no confía en la CA del piloto (en un iframe no aparece el aviso). | §5. En Linux, comprobar `C,,` en NSS. `curl --cacert` desde ese PC distingue certificado de red. |
| Iframe: **"Sesión rechazada o vencida."** (`embed` 200, websocket 101) | TLS funciona; el daemon rechazó la assertion de Daily. | En la estación: `Select-String "$env:LOCALAPPDATA\The Watcher\logs\watcher.log" -Pattern 'session rejected' \| Select -Last 5`. `assertion station mismatch`: el dispositivo está ligado en Daily a otra estación (p. ej. número de estación usado como `station_id`); corregir la estación del dispositivo a `#<station_id del bloque>` (§4.3). `assertion device mismatch`: Daily tiene otro `device_id` para la estación; registrar el del bloque. `assertion rejected`: reloj desfasado (`w32tm /resync`). `assertion key rejected`: Daily rotó su clave; reconstruir el instalador. |
| `DNS_PROBE_FINISHED_NXDOMAIN` | El `endpoint_name` no existe en DNS. | Reconstruir con el FQDN real o la IP. |
| `ERR_CONNECTION_TIMED_OUT` con la IP correcta | Firewall o red Public. | Inicio → Configurar firewall de The Watcher y leer los `AVISO`; `Test-NetConnection` desde otro PC. |
| `ERR_CONNECTION_REFUSED` | El daemon no escucha en 8767. | Iniciar The Watcher; `netstat -ano \| findstr :8767`. La URL lleva `https://` y `:8767`. |
| Acentos rotos en la salida de los scripts (`encontrÃ³`) | Script sin BOM leído por PowerShell 5.1. | Usar los scripts del repositorio (llevan BOM; un test lo exige). |
| AVISO "No se encontró The Watcher.exe" | Script ejecutado fuera de la instalación con el daemon parado. | Iniciar The Watcher o ejecutar desde `%LOCALAPPDATA%\The Watcher\`. |
| La estación aparece dos veces en el roster | Dispositivo antiguo aún activo. | Desactivar el que no coincide con el `device_id` del bloque (§4.4). |
| Daily indica estación no enrolada | Datos distintos o inactivo. | Repetir §3 y comparar con Dispositivos Watcher. |
| Daily no recibe heartbeat | Daemon parado o salida 443 bloqueada. | Iniciar The Watcher; Configurar firewall crea la regla de salida. |
| Rol Operador: "localhost refused to connect" (8765) | Este daemon no incluye `browser_local` (ADR-0023). | No es un fallo; la vista LAN (8767) no depende de él. |
| Puerto local abierto por otro proceso (8763, 9527) | Otro software (Splashtop `SRManager`). | `Get-Process -Id <PID>` antes de suponer que es el daemon. |

## Límites del piloto

El instalador no está firmado con Authenticode. La CA de piloto (ADR-0025) vive
en un secreto de GitHub, restringida a `sig.com`, `localhost`, `127.0.0.1` y
`192.168.0.0/16`, válida hasta el 3 de octubre de 2029: quien pueda ejecutar el
workflow puede firmar dentro de esos nombres. Usar una IP como `endpoint_name`
ata la vista a esa IP. Para distribución general se sustituye por el modo
`remote` (broker + step-ca, ADR-0024).
