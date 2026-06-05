# Supervisor — implementación QML

Variante B (grilla con estado, grupos y filtros) confirmada por ti,
adaptada al sistema de tokens existente de The Watcher.

## Archivos

| Archivo                       | Qué es                                              |
|-------------------------------|-----------------------------------------------------|
| `SupervisorView.qml`          | Vista principal — toolbar, grilla agrupada, form    |
| `OperatorCard.qml`            | Card reutilizable de operador                       |
| `TextInput.qml`               | Wrapper de `TextField` con estilo del proyecto      |

Todos usan `W.Tokens` (singleton ya registrado) y siguen las convenciones
de `RecordingView`/`MiniMode`/etc.: `Rectangle` + `RowLayout`/`ColumnLayout`,
`HoverHandler`/`TapHandler` para interacciones, `Behavior on color/opacity`
para transiciones suaves.

## Instalación

### 1. Copiar a `project/prototype/qml/`

```
cp qml-supervisor/SupervisorView.qml  project/prototype/qml/
cp qml-supervisor/OperatorCard.qml    project/prototype/qml/
cp qml-supervisor/TextInput.qml       project/prototype/qml/
```

### 2. Registrar en `project/prototype/qml/qmldir`

Añade estas tres líneas (manteniendo el orden alfabético):

```qmldir
OperatorCard      1.0 OperatorCard.qml
SupervisorView    1.0 SupervisorView.qml
TextInput         1.0 TextInput.qml
```

### 3. Añadir el tab "Supervisor" en `project/prototype/Main.qml`

#### 3.1 — Cambiar el `activeTab` para soportar 5 tabs

Hoy:
```qml
property int activeTab: 0   // 0=Grabación 1=Clips 2=Mini-modo 3=Ajustes
```

Reemplaza por:
```qml
property int activeTab: 0   // 0=Grabación 1=Clips 2=Supervisor 3=Mini-modo 4=Ajustes
```

#### 3.2 — Atajos de teclado

Reemplaza el bloque actual:

```qml
Shortcut { sequence: "Ctrl+1"; onActivated: root.activeTab = 0 }
Shortcut { sequence: "Ctrl+2"; onActivated: root.activeTab = 1 }
Shortcut { sequence: "Ctrl+3"; onActivated: root.activeTab = 2 }
Shortcut { sequence: "Ctrl+4"; onActivated: root.activeTab = 3 }
```

Por:

```qml
Shortcut { sequence: "Ctrl+1"; onActivated: root.activeTab = 0 }
Shortcut { sequence: "Ctrl+2"; onActivated: root.activeTab = 1 }
Shortcut { sequence: "Ctrl+3"; onActivated: root.activeTab = 2 }
Shortcut { sequence: "Ctrl+4"; onActivated: root.activeTab = 3 }
Shortcut { sequence: "Ctrl+5"; onActivated: root.activeTab = 4 }
```

#### 3.3 — Añadir "Supervisor" al modelo de tabs

En el `Repeater` de pestañas, reemplaza el `model`:

```qml
model: [
    { label: "Grabación",  key: "⌘1", idx: 0 },
    { label: "Clips",      key: "⌘2", idx: 1 },
    { label: "Mini-modo",  key: "⌘3", idx: 2 },
    { label: "Ajustes",    key: "⌘4", idx: 3 },
]
```

Por:

```qml
model: [
    { label: "Grabación",  key: "⌘1", idx: 0 },
    { label: "Clips",      key: "⌘2", idx: 1 },
    { label: "Supervisor", key: "⌘3", idx: 2 },
    { label: "Mini-modo",  key: "⌘4", idx: 3 },
    { label: "Ajustes",    key: "⌘5", idx: 4 },
]
```

#### 3.4 — Re-numerar los tabs existentes

Como Supervisor entra en posición 2, los tabs siguientes corren un índice:

- `activeTab === 1` (Clips)  → sigue igual
- `activeTab === 2` (Mini-modo)  → pasa a `activeTab === 3`
- `activeTab === 3` (Ajustes)  → pasa a `activeTab === 4`

Busca y reemplaza dentro del bloque de tabs:

| Antes                    | Después                  |
|--------------------------|--------------------------|
| `root.activeTab === 2`   | `root.activeTab === 3`   |  ← Mini-modo
| `root.activeTab === 3`   | `root.activeTab === 4`   |  ← Ajustes

(Hazlo en ese orden para no pisar el primero con el segundo.)

#### 3.5 — Insertar el bloque del nuevo tab

Entre el cierre del tab Clips (`} // Tab 1`) y la apertura del tab
Mini-modo, inserta:

```qml
// ── Tab 2 — Supervisor ────────────────────────────────────────
Item {
    anchors.fill: parent
    opacity: root.activeTab === 2 ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

    W.SupervisorView {
        anchors.fill: parent
    }
} // Tab 2
```

#### 3.6 — `Space` ya no marca evento en el panel Supervisor

El atajo actual es:
```qml
Shortcut { sequence: "Space"; onActivated: if (root.activeTab === 0) preRoll.start() }
```

Ya está correctamente condicionado a `activeTab === 0` (Grabación), así
que el Supervisor recibe `Ctrl+K` (foco en búsqueda) y `Esc` (limpiar)
sin pisar nada.

## Cómo conectar datos reales

`SupervisorView.qml` genera 47 operadores mock con `makeOps()` (ver línea
~26 del archivo). En producción reemplaza la propiedad `operators` con
un binding al modelo expuesto por Python — algo así:

```qml
W.SupervisorView {
    anchors.fill: parent
    operators: backend.operatorList   // array de objetos con los mismos campos
}
```

Campos esperados por card: `n`, `num`, `name`, `status` (`"rec"` |
`"online"` | `"idle"` | `"offline"`), `station`, `eventTag`, `lastEvent`,
`buffer`, `pinned`.

`submitRequest()` actualmente solo añade a la lista local — engánchalo a
una señal hacia el backend Python:

```qml
function submitRequest() {
    if (!root.selectedOp) return
    backend.requestClip(root.selectedOp.num, root.startTime,
                        root.endTime, root.desc)
    // …limpieza local…
}
```

## Atajos

| Tecla    | Acción                       |
|----------|------------------------------|
| `Ctrl+K` | Foco en búsqueda             |
| `Esc`    | Limpiar búsqueda / selección |

## Decisiones de diseño locked-in

- **Densidad:** regular (6 columnas, card 84px alto)
- **Detalle de card:** estándar (número + estación + evento/buffer)
- **Agrupación por defecto:** estado (REC / LIVE / IDLE / OFF)
- **Orden por defecto:** prioridad (estado → con-evento → número)
- **Posición del form:** rail derecho, 360px
- **Favoritos arriba** dentro de cada grupo

Las elecciones de **Orden** y **Grupo** quedan accesibles desde el
toolbar para que el supervisor pueda re-organizar en vivo.
