# Piloto `file`: construir, instalar, confiar TLS y enrolar en Daily

## Propósito y alcance

Esta guía permite preparar un piloto de una estación Windows con el instalador
`Setup-The Watcher.exe` creado por GitHub Actions. Está dirigida a IT, a la
persona que instala en la estación Operator y a los supervisores que abrirán la
vista LAN.

**Este es el modo piloto `TLS_PROVISIONING_MODE=file` con mkcert.** No es el
flujo futuro `remote` con broker + step-ca de ADR-0024. Cada ejecución del
workflow genera una CA de piloto efímera en el runner, incluye únicamente la
clave privada *leaf* de la estación en su instalador y entrega su CA **pública**
en un artefacto separado. Nunca se debe copiar ni instalar una clave privada en
un PC Supervisor.

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
| `station_name` | `2` | Etiqueta de artefacto; letras, números, punto, `_` o `-`. |
| `station_id` | `29` | ID numérico existente en Daily. |
| `endpoint_name` | `station-2` | Hostname/DNS LAN resolvible por los supervisores; no admite espacios. |
| `ip_addresses` | `192.168.101.106` | IP LAN opcional, separada por comas si hay más de una. |

Antes de publicar el instalador, confirmar que `station-2` resuelve a
`192.168.101.106` desde la red de los supervisores. La URL usada por la vista
LAN será `https://station-2:8767`.

## 1. Crear el instalador en GitHub Actions

1. Abrir el repositorio `hhce2303/The-Watcher` en GitHub.
2. Cambiar a la rama que contiene
   `.github/workflows/build-pilot-installer.yml` (actualmente
   `feat/extract-daemon-from-monorepo`).
3. Abrir **Actions** → **Build pilot installer (Windows)** → **Run workflow**.
4. Introducir los cuatro valores validados arriba.
5. Esperar que terminen correctamente estas etapas: pruebas, generación del
   perfil, build de campo, verificación de artefactos y uploads.
6. Descargar ambos artefactos antes de su vencimiento (el workflow los retiene
   siete días):
   - `the-watcher-pilot-installer-<station_name>`
   - `the-watcher-pilot-supervisor-trust-<station_name>`

La ejecución piloto de la estación 2 quedó verificada en
https://github.com/hhce2303/The-Watcher/actions/runs/37119732022.

### Verificar integridad antes de distribuir

En una máquina segura, calcular el hash del archivo descargado y contrastarlo
con el registro del run de Actions. Para el piloto actual:

```text
Setup-The Watcher.exe
SHA-256: 58d6776420b2340f676fef4700636c75e77817e4a41751e3504f9a9601f23243
```

No extraer, versionar ni reenviar el contenido interno del instalador: contiene
la clave privada leaf que sólo corresponde a esa estación.

## 2. Instalar en la estación Operator

1. Entregar exclusivamente `Setup-The Watcher.exe` de la estación correcta.
2. Iniciar sesión con la cuenta Windows que operará el daemon.
3. Ejecutar el instalador con doble clic. No se requieren Python, Rust, mkcert,
   PowerShell ni archivos de configuración manuales.
4. Mantener el destino por usuario propuesto por el instalador:
   `%LOCALAPPDATA%\The Watcher`.
5. Si Windows solicita elevación exclusivamente para abrir el firewall, IT debe
   permitir TCP **8767** en el perfil de red **Private**. El binario sigue
   instalado por usuario; no ejecutar todo el instalador como administrador.
6. Aceptar iniciar The Watcher al terminar y, si corresponde, el inicio
   automático de Windows.

El instalador importa la CA pública incluida a `CurrentUser\Root` del Operator.
No copiar manualmente `live-view-key.pem`, `device_identity.json` ni ningún
archivo `*key*` fuera de la estación.

### Firewall de Windows: entrada y salida

El tráfico necesario se limita a estos flujos. No crear reglas globales de
"permitir todo" ni abrir el puerto 8767 al perfil Public o a Internet.

| Dirección | Flujo | Regla requerida |
| --- | --- | --- |
| Entrada | Supervisor LAN → estación Operator TCP 8767 | Permitir TCP local 8767 sólo en perfil **Private**. |
| Salida | Estación Operator → Daily/Supabase HTTPS | Permitir TCP remoto 443 para `The Watcher.exe` si la política corporativa bloquea salida por defecto. |
| Respuesta | Estación Operator → Supervisor LAN | Es tráfico de respuesta de una conexión ya permitida; no requiere una regla de salida independiente para 8767. |
| DNS | Estación Operator → DNS corporativo | Debe estar permitido por la política normal del equipo/red; administrarlo en DNS/gateway corporativo, no con una regla amplia del daemon. |

### Plantilla editable para IT

Usar este bloque como mock/copia base. Para una estación nueva, modificar sólo
los valores entre comillas del primer bloque; el resto de comandos consume esas
variables y no necesita cambios. Mantener `Private`, `8767` y `443` salvo que
exista una decisión técnica aprobada para modificarlos.

```powershell
# === Cambiar sólo estos valores para la estación ===
$WatcherFirewall = @{
  RulePrefix   = 'The Watcher'                       # Ej.: 'The Watcher Station 2'
  WatcherExe   = "$env:LOCALAPPDATA\The Watcher\The Watcher.exe"
  NetworkScope = 'Private'                           # Nunca 'Public' para la vista LAN
  LiveViewPort = 8767
  DailyPort    = 443
}

# === No hace falta cambiar el resto ===
$InboundRuleName  = "$($WatcherFirewall.RulePrefix) Live View"
$OutboundRuleName = "$($WatcherFirewall.RulePrefix) outbound Daily HTTPS"
```

> **Este bloque sólo define variables y no crea ninguna regla.** Al pegarlo,
> PowerShell vuelve al prompt sin mostrar nada; es normal. Para crear las
> reglas en una sola ejecución, usar el [script completo](#script-completo-crear-las-reglas-en-una-estación-externa)
> más abajo.

El instalador intenta crear la regla de **entrada** mediante UAC. IT debe
verificarla desde PowerShell elevado en la estación:

```powershell
Get-NetFirewallRule -DisplayName $InboundRuleName |
  Get-NetFirewallPortFilter |
  Format-Table Protocol, LocalPort
```

Si la regla no existe o el instalador no obtuvo elevación, crearla de forma
idempotente, limitada a la LAN privada:

```powershell
if (-not (Get-NetFirewallRule -DisplayName $InboundRuleName -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule `
    -DisplayName $InboundRuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $WatcherFirewall.LiveViewPort `
    -Profile $WatcherFirewall.NetworkScope
}
```

Windows permite salida por defecto en la mayoría de instalaciones; en ese caso
no se agrega una regla adicional. Si la organización aplica una política de
salida por defecto-denegada, IT debe permitir HTTPS de forma acotada al ejecutable
instalado, sin abrir puertos para todos los programas:

```powershell
if (-not (Test-Path -LiteralPath $WatcherFirewall.WatcherExe -PathType Leaf)) {
  throw "The Watcher executable was not found: $($WatcherFirewall.WatcherExe)"
}
if (-not (Get-NetFirewallRule -DisplayName $OutboundRuleName -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule `
    -DisplayName $OutboundRuleName `
    -Direction Outbound `
    -Action Allow `
    -Program $WatcherFirewall.WatcherExe `
    -Protocol TCP `
    -RemotePort $WatcherFirewall.DailyPort `
    -Profile Any
}
```

La regla de salida anterior permite al daemon alcanzar los endpoints HTTPS de
Daily/Supabase necesarios para heartbeats. Si la política de red exige una lista
de destinos más estricta, aplicarla en el firewall/gateway corporativo con los
FQDN aprobados; no sustituirla por una regla de salida general.

### Script completo: crear las reglas en una estación externa

Pegar todo el bloque en **PowerShell como administrador** en la estación (o
guardarlo como `watcher-firewall.ps1` y ejecutarlo con
`powershell -ExecutionPolicy Bypass -File .\watcher-firewall.ps1`). Es
idempotente: si una regla ya existe, la informa y no la duplica. A diferencia de
los fragmentos anteriores, siempre imprime el resultado, de modo que no queda
en silencio ante un fallo.

```powershell
$ErrorActionPreference = 'Stop'

# === Cambiar sólo estos valores para la estación ===
$WatcherFirewall = @{
  RulePrefix   = 'The Watcher'                       # Ej.: 'The Watcher Station 2'
  WatcherExe   = "$env:LOCALAPPDATA\The Watcher\The Watcher.exe"
  NetworkScope = 'Private'                           # Nunca 'Public' para la vista LAN
  LiveViewPort = 8767
  DailyPort    = 443
}

# === No hace falta cambiar el resto ===
$InboundRuleName  = "$($WatcherFirewall.RulePrefix) Live View"
$OutboundRuleName = "$($WatcherFirewall.RulePrefix) outbound Daily HTTPS"

# New-NetFirewallRule exige elevación; sin ella falla con "Access denied".
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Abrir PowerShell con "Ejecutar como administrador" y repetir.'
}
if ($WatcherFirewall.NetworkScope -eq 'Public') {
  throw "NetworkScope no puede ser 'Public' para la vista LAN."
}

# Entrada: supervisores LAN -> TCP 8767 (sólo perfil Private)
if (Get-NetFirewallRule -DisplayName $InboundRuleName -ErrorAction SilentlyContinue) {
  Write-Host "Ya existe: $InboundRuleName"
} else {
  New-NetFirewallRule `
    -DisplayName $InboundRuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $WatcherFirewall.LiveViewPort `
    -Profile $WatcherFirewall.NetworkScope | Out-Null
  Write-Host "Creada: $InboundRuleName"
}

# Salida: The Watcher.exe -> HTTPS 443 (necesaria sólo si la salida está denegada por defecto)
if (-not (Test-Path -LiteralPath $WatcherFirewall.WatcherExe -PathType Leaf)) {
  throw "The Watcher executable was not found: $($WatcherFirewall.WatcherExe)"
}
if (Get-NetFirewallRule -DisplayName $OutboundRuleName -ErrorAction SilentlyContinue) {
  Write-Host "Ya existe: $OutboundRuleName"
} else {
  New-NetFirewallRule `
    -DisplayName $OutboundRuleName `
    -Direction Outbound `
    -Action Allow `
    -Program $WatcherFirewall.WatcherExe `
    -Protocol TCP `
    -RemotePort $WatcherFirewall.DailyPort `
    -Profile Any | Out-Null
  Write-Host "Creada: $OutboundRuleName"
}

# Verificación
Get-NetFirewallRule -DisplayName "$($WatcherFirewall.RulePrefix)*" | ForEach-Object {
  $port = $_ | Get-NetFirewallPortFilter
  [pscustomobject]@{
    Regla     = $_.DisplayName
    Direccion = $_.Direction
    Accion    = $_.Action
    Perfil    = $_.Profile
    Protocolo = $port.Protocol
    PuertoLoc = $port.LocalPort
    PuertoRem = $port.RemotePort
    Habilitada = $_.Enabled
  }
} | Format-Table -AutoSize
```

Si el instalador ya creó la regla de entrada mediante UAC, el script lo indica
con "Ya existe" y sólo añade la de salida. Si el script termina con un error en
rojo, ese mensaje es la causa; no hay fallos silenciosos.

### Comprobación de la estación

Desde una cuenta que ya confíe en la CA del piloto, abrir:

```text
https://station-2:8767/api/v1/health
```

Debe responder JSON con `status: "ok"` y un `device_id`. Ese endpoint no revela
la clave privada. Si no responde, comprobar antes de continuar:

- The Watcher está ejecutándose bajo la cuenta Operator.
- El nombre `station-2` resuelve a la IP LAN prevista.
- La red Windows está marcada como Private y la regla de TCP 8767 existe.
- El certificado público de la CA del piloto está confiado en el perfil que
  hace la prueba.

La grabación no debe depender de que la vista LAN responda: si TLS falla, la
vista queda cerrada y se debe corregir antes de habilitar supervisión.

## 3. Confiar la CA en cada PC Supervisor

El artefacto `the-watcher-pilot-supervisor-trust-<station_name>` contiene sólo
`watcher-pilot-rootCA.pem`, la CA pública. **No contiene y no debe recibir la
clave leaf de la estación.**

Cada Supervisor que usará Daily debe hacer esto dentro de su sesión Windows
interactiva:

1. Descargar el artefacto de confianza por un canal controlado de IT.
2. Comprobar su hash/fingerprint contra el run de Actions.
3. Importar la CA pública en el almacén Root del usuario actual:

```powershell
Import-Certificate `
  -FilePath "$HOME\Downloads\watcher-pilot-rootCA.pem" `
  -CertStoreLocation 'Cert:\CurrentUser\Root'
```

4. Cerrar y abrir el navegador gestionado.
5. Abrir `https://station-2:8767/api/v1/health` y confirmar que no aparece una
   advertencia de certificado.

La instalación es por perfil Windows. Repetirla para cada supervisor/perfil que
vaya a abrir la estación. Para retirar confianza al terminar el piloto, IT debe
identificar la CA por su fingerprint y eliminar únicamente esa entrada del
almacén `CurrentUser\Root`; no borrar certificados ajenos.

## 4. Enrolar la estación en Daily

El instalador `file` configura `LIVE_VIEW_STATION_ID=29`, pero esto **no crea**
por sí solo el registro de confianza en Daily. Un administrador Daily con el
permiso `watcher.devices.manage` debe realizar el enrolamiento.

### 4.1 Obtener sólo los datos públicos de identidad

No abrir ni copiar el archivo de identidad completo: contiene la clave privada
Ed25519. IT puede generar una salida pública acotada desde la estación, sin
mostrar ni guardar `private_key_pem`:

```powershell
$identityPath = Join-Path $env:LOCALAPPDATA 'The Watcher\browser_local\device_identity.json'
$identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
[pscustomobject]@{
  device_id = $identity.device_id
  public_key_pem = $identity.public_key_pem
} | ConvertTo-Json -Depth 3
Remove-Variable identity
```

Copiar únicamente `device_id` y `public_key_pem` al canal controlado de IT. No
redirigir esa salida junto con el archivo original, no abrirlo en un editor y no
transferir la clave privada.

Si el archivo aún no existe, iniciar The Watcher una vez y volver a comprobar.
La identidad se crea por instalación cuando se inicia la superficie que usa el
daemon; el log del daemon registra el `device_id`, pero no debe usarse para
extraer claves.

### 4.2 Registrar en la interfaz Daily

1. Iniciar sesión en Daily como Admin o Lead Supervisor con
   `watcher.devices.manage`.
2. Ir a **Administración → Dispositivos Watcher**.
3. Crear/actualizar el dispositivo con:
   - `device_id`: UUID público obtenido arriba.
   - `station_id`: `29` (estación 2 del piloto).
   - Nombre visible: por ejemplo `Station 2 — Operator`.
   - `public_key_pem`: clave pública Ed25519 completa, incluido PEM.
   - Estado: **activo**.
4. Guardar y confirmar que la estación existe en Daily y que el registro queda
   activo.

Daily persiste esos datos mediante la RPC
`watcher_admin_upsert_device(device_id, station_id, display_name,
public_key_pem, active)`. La autorización comprueba el permiso de gestión, que
el `station_id` exista y que la clave pública tenga formato mínimo; no se debe
hacer un `INSERT` directo desde el navegador ni conceder acceso directo a la
tabla `watcher_devices`.

## 5. Validación de extremo a extremo

1. En Daily, comprobar que la estación aparece en el roster y recibe
   heartbeats. Daily declara offline un equipo cuando no hay señal por más de
   90 segundos.
2. Desde una cuenta Supervisor con `watcher.supervision.view`, abrir la vista
   LAN de la estación 2.
3. Confirmar que el navegador usa `https://station-2:8767`, sin bypass de
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
| Advertencia TLS en el Supervisor | Comprobar que importó la CA del **mismo run** y perfil Windows; no aceptar un bypass del navegador. |
| `station-2` no abre o no resuelve | Corregir DNS/host y red LAN; no cambiar el certificado a un nombre distinto sin construir otro instalador. |
| Puerto 8767 cerrado | IT debe habilitar TCP 8767 sólo para perfil Private/LAN; no abrirlo a Internet. |
| Daily indica estación no enrolada | Revisar `device_id`, PEM público, `station_id=29` y estado activo en Administración → Dispositivos Watcher. |
| Daily no recibe heartbeat | Revisar que el daemon esté activo y su URL/origen coincidan con el perfil; no copiar ni sustituir identidades locales. |

Este artefacto es de piloto: no está firmado con Authenticode y la CA mkcert es
propia de una ejecución. Para una distribución general se debe reemplazar por
el servicio remoto con broker + step-ca de ADR-0024, con una CA operada por IT
y un procedimiento de reemisión definido.
