# Piloto `file`: construir, instalar, confiar TLS y enrolar en Daily

## Propósito y alcance

Esta guía permite preparar un piloto de una estación Windows con el instalador
`Setup-The Watcher.exe` creado por GitHub Actions. Está dirigida a IT, a la
persona que instala en la estación Operator y a los supervisores que abrirán la
vista LAN.

**Este es el modo piloto `TLS_PROVISIONING_MODE=file` con mkcert.** No es el
flujo futuro `remote` con broker + step-ca de ADR-0024. Cada ejecución del
workflow firma cada estación con **una única CA de piloto persistente** (secreto
de GitHub, ver [ADR-0025](../architecture/adr/ADR-0025-persistent-pilot-ca-in-github-secret.md)),
incluye únicamente la clave privada *leaf* de la estación en su instalador y
entrega la CA **pública** en un artefacto separado. Como la CA es siempre la
misma, **cada supervisor la importa una sola vez**, no una por instalador.
Nunca se debe copiar ni instalar una clave privada en un PC Supervisor.

## Roles

| Rol | Responsabilidad |
| --- | --- |
| IT / Release manager | Ejecuta el workflow, conserva los artefactos y registra la estación en Daily. |
| Operator | Ejecuta el instalador como su usuario normal y permite la regla de firewall si Windows la solicita. No edita `.env` ni maneja certificados. |
| Supervisor | Importa sólo la CA pública en su perfil Windows y abre la vista desde Daily. |
| Administrador Daily | Registra el `device_id` y `public_key_pem` públicos, los liga a la estación y deja el dispositivo activo. |

## Datos que se deben validar antes de construir

Solicitar y comprobar estos datos con el responsable de la estación:

| Campo del workflow | Ejemplo del piloto actual | Regla |
| --- | --- | --- |
| `station_name` | `2-coperator03` | Etiqueta de artefacto; letras, números, punto, `_` o `-`. |
| `station_id` | `29` | ID numérico existente en Daily. |
| `endpoint_name` | `coperator03.sig.com` | **Nombre real del equipo** (FQDN) que ya resuelve en el DNS de los supervisores; no admite espacios. |
| `ip_addresses` | `192.168.101.106` | IP LAN opcional, separada por comas si hay más de una. |

**El `endpoint_name` debe ser el hostname real de la máquina**, no un alias
inventado. Un nombre que no existe en el DNS (por ejemplo `station-2`) produce
`DNS_PROBE_FINISHED_NXDOMAIN` en el supervisor y el iframe de Daily queda en
blanco. Para obtenerlo, en la estación: `hostname` y `(Get-CimInstance
Win32_ComputerSystem).Domain` (nombre + dominio = FQDN).

Antes de publicar el instalador, **desde un PC supervisor** comprobar:

```powershell
Resolve-DnsName coperator03.sig.com    # debe devolver la IP LAN de la estación
```

La URL usada por la vista LAN será `https://<endpoint_name>:8767`. La CA de
piloto sólo firma `sig.com`, `localhost`, `127.0.0.1` e IPs `192.168.0.0/16`;
una estación fuera de esos rangos no puede usarla (requiere rotar la CA).

## 1. Crear el instalador en GitHub Actions

1. Abrir el repositorio `hhce2303/The-Watcher` en GitHub.
2. Cambiar a la rama que contiene
   `.github/workflows/build-pilot-installer.yml` (actualmente
   `feat/extract-daemon-from-monorepo`).
3. Abrir **Actions** → **Build pilot installer (Windows)** → **Run workflow**.
4. Introducir los cuatro valores validados arriba.
5. Esperar que terminen correctamente estas etapas: pruebas, generación del
   perfil, build de campo, verificación de artefactos y uploads. Si falla en
   "Generate pilot profile" con `Secrets WATCHER_PILOT_CA_CERT and
   WATCHER_PILOT_CA_KEY are required`, los secretos del repositorio faltan o
   la CA caduca en menos de 30 días: se rota según ADR-0025. El workflow
   nunca genera una CA de reemplazo por su cuenta.
6. Descargar ambos artefactos antes de su vencimiento (el workflow los retiene
   siete días):
   - `the-watcher-pilot-installer-<station_name>`
   - `the-watcher-pilot-supervisor-trust-<station_name>`

Ejecución piloto de referencia de la estación 2 (`COPERATOR03`):
https://github.com/hhce2303/The-Watcher/actions/runs/37176737491. Fue anterior a la
CA persistente; los runs nuevos usan la CA de ADR-0025.

### Verificar integridad antes de distribuir

En una máquina segura, calcular el hash del instalador descargado y contrastarlo
con el registro del run de Actions (paso "Build field installer"):

```text
Get-FileHash -Algorithm SHA256 "Setup-The Watcher.exe"
```

La CA pública (`watcher-pilot-rootCA.pem`) es **la misma en todos los runs**. El
hash SHA-256 del archivo es `6920c9fa938be16b092bcf5f6c16093f52b39f43c95fb3e0279d4f254bd6563b` y la huella SHA-256 del certificado debe ser:

```text
C0:C6:91:66:1C:41:90:8B:57:B3:A8:48:AB:94:CD:5C:9E:DE:6C:5C:8A:7B:C8:7D:94:7C:B4:01:A2:A7:D9:F3
```

Si un run entrega otra huella, no distribuirla: la CA cambió (rotación) o el
artefacto no es el esperado.

No extraer, versionar ni reenviar el contenido interno del instalador: contiene
la clave privada leaf que sólo corresponde a esa estación.

## 2. Instalar en la estación Operator

1. Entregar exclusivamente `Setup-The Watcher.exe` de la estación correcta.
2. Iniciar sesión con la cuenta Windows que operará el daemon.
3. Ejecutar el instalador con doble clic. No se requieren Python, Rust, mkcert,
   PowerShell ni archivos de configuración manuales.
4. Mantener el destino por usuario propuesto por el instalador:
   `%LOCALAPPDATA%\The Watcher`.
5. Al final Windows pide UAC **sólo para el firewall**: IT introduce su
   credencial y el instalador crea las reglas (ver "Crear o corregir las reglas
   de firewall"). El binario sigue instalado por usuario; no ejecutar todo el
   instalador como administrador.
6. Aceptar iniciar The Watcher al terminar y, si corresponde, el inicio
   automático de Windows.

Reinstalar sobre una instalación existente **sobrescribe `.env` y `certs\`** (B-21
en `docs/backlog/known-recording-issues.md`) y cierra el proceso en ejecución. Instalar
siempre con la sesión Windows del usuario que ejecuta el daemon (no con la cuenta
de IT), o el daemon quedará en otro perfil.

El instalador importa la CA pública incluida a `CurrentUser\Root` del Operator.
No copiar manualmente `live-view-key.pem`, `device_identity.json` ni ningún
archivo `*key*` fuera de la estación.

**Limpieza obligatoria:** el instalador contiene la clave privada *leaf*. Al
terminar, borrar toda copia de `Setup-The Watcher.exe` de las carpetas
intermedias (Descargas, `C:\Users\Public`, el perfil de IT, USB) y del equipo
que lo descargó. Sólo debe quedar la instalación en el perfil del Operator.

### Firewall de Windows: entrada y salida

El tráfico necesario se limita a estos flujos. No crear reglas globales de
"permitir todo" ni abrir el puerto 8767 al perfil Public o a Internet.

| Dirección | Flujo | Regla requerida |
| --- | --- | --- |
| Entrada | Supervisor LAN → estación Operator TCP 8767 | Permitir TCP local 8767 sólo en perfil **Domain** y/o **Private**, nunca **Public**. |
| Salida | Estación Operator → Daily/Supabase HTTPS | Permitir TCP remoto 443 para `The Watcher.exe` si la política corporativa bloquea salida por defecto. |
| Respuesta | Estación Operator → Supervisor LAN | Es tráfico de respuesta de una conexión ya permitida; no requiere una regla de salida independiente para 8767. |
| DNS | Estación Operator → DNS corporativo | Debe estar permitido por la política normal del equipo/red; administrarlo en DNS/gateway corporativo, no con una regla amplia del daemon. |

### Crear o corregir las reglas de firewall (doble clic)

Las reglas las crea siempre el mismo script versionado,
[`installer/watcher-firewall.ps1`](../../installer/watcher-firewall.ps1), que se
instala junto al ejecutable. **No hay nada que editar ni que copiar y pegar.**

- **Durante la instalación** el instalador lo ejecuta y Windows pide UAC una vez.
  IT introduce su credencial de administrador. Si se cancela, el instalador
  avisa y la instalación continúa.
- **En cualquier momento después** (reglas borradas, red cambiada, piloto
  anterior con la regla sólo en Private): **Inicio → "Configurar firewall de The
  Watcher"**, aceptar UAC y leer el resultado. Es la misma acción que hacer doble
  clic en `%LOCALAPPDATA%\The Watcher\Configurar firewall.cmd`.

El script:

1. Se eleva solo; no hace falta abrir PowerShell como administrador.
2. Borra y recrea únicamente sus dos reglas (`The Watcher Live View` y `The
   Watcher outbound Daily HTTPS`), así que repetirlo no duplica nada y corrige
   reglas viejas.
3. Abre la entrada TCP 8767 en **Domain y Private** (las estaciones `sig.com`
   están en dominio). Nunca en Public.
4. Crea la salida TCP 443 sólo para el `The Watcher.exe` de **su propia carpeta**.
   Por eso funciona aunque IT eleve con otra cuenta, cuyo `%LOCALAPPDATA%` es
   otro.
5. Avisa en amarillo si la red está en perfil **Public** o si hay una regla
   **Block** sobre 8767 (ambas impiden la vista LAN aunque la regla exista), e
   indica si el daemon ya escucha.
6. Termina con la línea de prueba para ejecutar desde otro PC.

Resultado esperado: dos líneas `OK` en verde y ningún `AVISO`. Para retirar
las reglas: `"Configurar firewall.cmd" -Remove`.

Estaciones instaladas con un instalador anterior a este script no tienen el
acceso directo: copiar `watcher-firewall.ps1` y `Configurar firewall.cmd` a
`%LOCALAPPDATA%\The Watcher\` del Operator y hacer doble clic en el `.cmd`.

La regla de salida permite al daemon alcanzar los endpoints HTTPS de
Daily/Supabase para los heartbeats. Si la política de red exige una lista de
destinos más estricta, aplicarla en el firewall/gateway corporativo con los
FQDN aprobados; no sustituirla por una regla de salida general. DNS debe estar
permitido por la política normal del equipo, no con una regla del daemon.

**Prueba válida del firewall:** `Test-NetConnection <ip-estación> -Port 8767`
**desde otro PC de la LAN**. Ejecutada en la propia estación siempre da `True`
(el tráfico local no pasa por la regla de entrada) y no prueba nada.

### Comprobación de la estación

Desde una cuenta que ya confíe en la CA del piloto, abrir:

```text
https://coperator03.sig.com:8767/api/v1/health
```

Debe responder JSON con `status: "ok"` y un `device_id`. Probar con la IP
(`https://192.168.101.106:8767/...`) también funciona porque la IP va en los SAN,
pero Daily usa el nombre. Ese endpoint no revela
la clave privada. Si no responde, comprobar antes de continuar:

- The Watcher está ejecutándose bajo la cuenta Operator.
- El `endpoint_name` (`coperator03.sig.com`) resuelve a la IP LAN prevista desde el
  PC que hace la prueba (`Resolve-DnsName`).
- La regla de TCP 8767 existe y su perfil coincide con el de la red de la estación
  (`Get-NetConnectionProfile`); `Test-NetConnection` desde otro PC da `True`.
- El daemon escucha: `netstat -ano | findstr :8767` en la estación.
- La CA de piloto (huella indicada en el apartado de integridad) está confiada en
  el perfil y el navegador que hace la prueba.

La grabación no debe depender de que la vista LAN responda: si TLS falla, la
vista queda cerrada y se debe corregir antes de habilitar supervisión.

## 3. Confiar la CA en cada PC Supervisor

El artefacto `the-watcher-pilot-supervisor-trust-<station_name>` contiene sólo
`watcher-pilot-rootCA.pem`, la CA pública. **No contiene y no debe recibir la
clave leaf de la estación.** Es la misma CA en todos los runs: **se importa una
sola vez por supervisor y navegador**, y cubre todas las estaciones firmadas con
ella (mientras no se rote, ADR-0025).

Cada Supervisor que usará Daily debe hacer esto dentro de su sesión interactiva:

1. Descargar el artefacto de confianza por un canal controlado de IT.
2. Comprobar el hash del archivo recibido; debe ser idéntico en todos los runs:

   ```powershell
   Get-FileHash -Algorithm SHA256 "$HOME\Downloads\watcher-pilot-rootCA.pem"
   ```

   Esperado: `6920c9fa938be16b092bcf5f6c16093f52b39f43c95fb3e0279d4f254bd6563b`
   Si difiere, comprobar la huella del certificado (apartado "Verificar integridad
   antes de distribuir"): es la referencia autoritativa, y el hash del archivo
   puede variar sólo por saltos de línea.
3. Importarla según el sistema:

**Windows** (almacén Root del usuario actual, sin ser administrador):

```powershell
Import-Certificate -FilePath "$HOME\Downloads\watcher-pilot-rootCA.pem" -CertStoreLocation 'Cert:\CurrentUser\Root'
```

Windows muestra un aviso al importar una CA raíz; aceptarlo sólo tras verificar
la huella. Cerrar **todas** las ventanas del navegador y abrirlo de nuevo.

**Linux (Chromium, Brave, Chrome):** estos navegadores usan la base NSS del
usuario, no el almacén del sistema. Importar y marcar como confiable:

```bash
certutil -d sql:$HOME/.pki/nssdb -A -n watcher-pilot-ca -t "C,," -i watcher-pilot-rootCA.pem
certutil -d sql:$HOME/.pki/nssdb -L | grep watcher
```

La línea debe mostrar `C,,`. Si la base está protegida con contraseña, el comando
falla con `SEC_ERROR_TOKEN_NOT_LOGGED_IN` y el certificado queda añadido **sin
confianza** (`,,`): ejecutarlo en una terminal interactiva (`certutil -M -n
watcher-pilot-ca -t "C,,"`) o usar `brave://settings/certificates` → Authorities →
Importar. Firefox tiene su propio almacén (Ajustes → Certificados).

4. Abrir `https://coperator03.sig.com:8767/api/v1/health` y confirmar que no
   aparece una advertencia de certificado.

Para retirar la confianza al terminar el piloto, IT debe identificar la CA por su
huella y eliminar únicamente esa entrada del almacén; no borrar certificados ajenos.

## 4. Enrolar la estación en Daily

El instalador deja configurado `LIVE_VIEW_STATION_ID` (el `station_id` del
workflow), pero eso **no crea** el registro de confianza en Daily. Hay que
registrar el dispositivo una vez por instalación. Reinstalar conserva la
identidad (`browser_local\device_identity.json` no se sobrescribe), así que el
registro sigue valiendo.

### 4.1 En la estación: obtener los datos (doble clic)

Con la sesión del **Operator** (no la de IT) y The Watcher ya iniciado:
**Inicio → "Datos de enrolamiento de The Watcher"**. Es lo mismo que hacer doble
clic en `%LOCALAPPDATA%\The Watcher\Datos de enrolamiento.cmd`. No pide
administrador ni hay nada que editar.

El script
[`installer/watcher-enrollment.ps1`](../../installer/watcher-enrollment.ps1)
muestra y **copia al portapapeles** un bloque con los campos del formulario de
Daily, ya rellenados:

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

Endpoint LAN:   https://coperator08.sig.com:8767
Equipo:         COPERATOR08  (CSOperator)
```

- El `station_id` sale del `.env` instalado, no se escribe a mano. Si no
  coincide con la estación de Daily, el instalador era de otra estación:
  reconstruirlo, no editar el `.env`.
- Sólo lee `device_id` y `public_key_pem`. La clave privada del archivo de
  identidad nunca se muestra ni se copia. No abrir ese archivo en un editor.
- Si dice que la identidad aún no existe: iniciar The Watcher, esperar unos
  segundos y repetir.

Pegar el bloque en el canal de IT. Contiene sólo datos públicos.

Estaciones instaladas con un instalador anterior a este script no tienen el
acceso directo: copiar `watcher-enrollment.ps1` y `Datos de enrolamiento.cmd` a
`%LOCALAPPDATA%\The Watcher\` del Operator y hacer doble clic en el `.cmd`.

### 4.2 En Daily: registrar el dispositivo

1. Iniciar sesión en Daily como Admin o Lead Supervisor con
   `watcher.devices.manage`.
2. Ir a **Administración → Dispositivos Watcher → Crear/actualizar**.
3. Copiar cada campo del bloque tal cual: `device_id`, `station_id`, nombre
   visible, `public_key_pem` completo (con las líneas `BEGIN`/`END`) y estado
   **activo**.
4. Guardar. En 30–90 s la estación debe aparecer en línea en el roster (primer
   heartbeat).

| Comprobación | Si falla |
| --- | --- |
| El `station_id` del bloque es el de la estación en Daily | El instalador es de otra estación: reconstruir con el `station_id` correcto. |
| Daily acepta el PEM | Falta una línea `BEGIN`/`END` o hay espacios añadidos: volver a copiar desde el bloque. |
| La estación aparece en línea | Ver "Daily no recibe heartbeat" en Incidencias. |

Daily persiste esos datos mediante la RPC
`watcher_admin_upsert_device(device_id, station_id, display_name,
public_key_pem, active)`. La autorización comprueba el permiso de gestión, que
el `station_id` exista y que la clave pública tenga formato mínimo; no se debe
hacer un `INSERT` directo desde el navegador ni conceder acceso directo a la
tabla `watcher_devices`.

### Registro de estaciones del piloto

| Estación | Equipo | `station_id` | Endpoint | IP |
| --- | --- | --- | --- | --- |
| 2 | COPERATOR03 | 29 | `coperator03.sig.com` | 192.168.101.106 |
| 48 | COPERATOR08 | 45 | `192.168.101.107` (IP: el registro A de `coperator08.sig.com` apunta a 192.168.100.55, una NIC antigua; volver al nombre cuando IT lo corrija) | 192.168.101.107 |

## 5. Validación de extremo a extremo

1. En Daily, comprobar que la estación aparece en el roster y recibe
   heartbeats. Daily declara offline un equipo cuando no hay señal por más de
   90 segundos.
2. Desde una cuenta Supervisor con `watcher.supervision.view`, abrir la vista
   LAN de la estación 2.
3. Confirmar que el navegador usa `https://coperator03.sig.com:8767` (el `endpoint_name`), sin bypass de
   certificado, HTTP ni excepciones TLS.
4. Confirmar que la vista solicita una assertion Daily válida; debe denegarse
   si el dispositivo está inactivo, el `station_id` no coincide o falta el
   permiso del supervisor.
5. Probar un fallo controlado: desactivar temporalmente el dispositivo en
   Daily. La supervisión debe rechazarse; no debe habilitarse por fallback.
6. Reactivar el dispositivo y comprobar la recuperación mediante nuevos
   heartbeats.

## Incidencias y límites conocidos

| Síntoma | Acción segura |
| --- | --- |
| `DNS_PROBE_FINISHED_NXDOMAIN` en el supervisor | El `endpoint_name` no existe en el DNS de ese PC. Comprobar `Resolve-DnsName <endpoint_name>`; si el nombre fue inventado, construir otro instalador con el hostname real. No es un problema de firewall: el error ocurre antes de abrir la conexión. |
| `ERR_CONNECTION_TIMED_OUT` al abrir el puerto 8767 | Firewall o perfil de red. En la estación: Inicio → "Configurar firewall de The Watcher" y leer los `AVISO`. Si no hay ninguno, comprobar `Get-NetConnectionProfile` (¿Domain, Private o Public?) y que la regla incluya ese perfil. Probar `Test-NetConnection` **desde otro PC**. |
| `ERR_CONNECTION_REFUSED` en la IP | El daemon no escucha en 8767 (`netstat -ano | findstr :8767`). Revisar la URL: debe llevar `https://` y `:8767` (un `/8767` consulta el puerto 80). |
| Advertencia TLS en el Supervisor | Comprobar que importó la CA de piloto (huella del apartado de integridad) en el perfil **y navegador** que usa; en Linux, que la entrada NSS diga `C,,`. No aceptar un bypass. |
| El iframe `embed` de Daily queda en blanco con la vista LAN | F12 → Network → fila `embed` → Request URL, y el error de la consola. Distingue DNS, certificado, firewall o CSP (`LIVE_VIEW_PARENT_ORIGIN`). |
| Daily indica estación no enrolada | Volver a ejecutar "Datos de enrolamiento de The Watcher" en la estación y comparar `device_id`, `station_id` y PEM con lo guardado en Administración → Dispositivos Watcher; estado activo. |
| Daily no recibe heartbeat | Revisar que el daemon esté activo y su URL/origen coincidan con el perfil; no copiar ni sustituir identidades locales. |
| Daily (rol Operador) muestra "Buscando el daemon local… localhost refused to connect" | Esta vista usa `browser_local` en `localhost:8765`. **Este daemon no incluye ese servidor** (ADR-0023; `app/adapters/browser_local/` sólo trae helpers de sesión/identidad), así que ese puerto nunca escucha. No es un fallo de firewall ni del instalador. La vista LAN del supervisor (8767) no depende de él. |
| Un puerto local abierto por otro proceso (p. ej. 8763, 9527) | Identificar el proceso antes de suponer que es el daemon (`Get-Process -Id <PID>`); en el piloto eran de Splashtop (`SRManager`). |

Este artefacto es de piloto: no está firmado con Authenticode y la CA de piloto
([ADR-0025](../architecture/adr/ADR-0025-persistent-pilot-ca-in-github-secret.md))
es una CA persistente cuya clave vive en un secreto de GitHub, con restricción de
nombres (`sig.com`, `localhost`, `127.0.0.1`, `192.168.0.0/16`) y vigencia de 3
años (hasta el 3 de octubre de 2029). Quien pueda leer secretos o ejecutar el
workflow puede firmar certificados dentro de esos nombres. Una opción más fuerte a
corto plazo es que IT firme cada estación con la CA corporativa de SIG; para una
distribución general se debe reemplazar por el servicio remoto con broker + step-ca
de ADR-0024, con una CA operada por IT y un procedimiento de reemisión definido.

Estaciones instaladas con la CA efímera anterior siguen con esa CA hasta
reinstalarlas; sus supervisores deben confiarla hasta entonces.
