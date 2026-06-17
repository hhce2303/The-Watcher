# IT Editor — implementación QML

Rol IT del flujo del Supervisor → IT del The Watcher. Recibe una solicitud
por websocket (1 a la vez, sin cola visible), abre el archivo en NAS, lo
edita en una timeline, lo sube a OneDrive y genera enlace compartido.

## Archivos

| Archivo                       | Qué es                                              |
|-------------------------------|-----------------------------------------------------|
| `ITEditorView.qml`            | Vista raíz · estado · titlebar · statusbar          |
| `NotificationStrip.qml`       | Hero card (incoming) + strip pinneada (editing)     |
| `NASBrowser.qml`              | Árbol de SIG-SLC-Storage con archivo solicitado     |
| `VideoEditor.qml`             | Preview + transport + timeline con waveform/eventos |
| `OutputPanel.qml`             | Subida a OneDrive + enlace + actividad reciente     |
| `OperatorAvatar.qml`          | Monograma reutilizable (supervisor + IT user)       |

Todos usan `W.Tokens` (singleton ya registrado) y siguen las mismas
convenciones que `RecordingView` / `MiniMode` / `SupervisorView`.

## Instalación

### 1. Copiar a `project/prototype/qml/`

```
cp qml-it-editor/ITEditorView.qml      project/prototype/qml/
cp qml-it-editor/NotificationStrip.qml project/prototype/qml/
cp qml-it-editor/NASBrowser.qml        project/prototype/qml/
cp qml-it-editor/VideoEditor.qml       project/prototype/qml/
cp qml-it-editor/OutputPanel.qml       project/prototype/qml/
cp qml-it-editor/OperatorAvatar.qml    project/prototype/qml/
```

### 2. Registrar en `project/prototype/qml/qmldir`

Añade estas seis líneas (manteniendo orden alfabético):

```qmldir
ITEditorView       1.0 ITEditorView.qml
NASBrowser         1.0 NASBrowser.qml
NotificationStrip  1.0 NotificationStrip.qml
OperatorAvatar     1.0 OperatorAvatar.qml
OutputPanel        1.0 OutputPanel.qml
VideoEditor        1.0 VideoEditor.qml
```

> ⚠️ El nombre `VideoEditor` colisiona con la convención del editor para
> IT mencionada en el README del proyecto. Si ya existe ese componente,
> renómbralo a `ITVideoEditor` aquí y en el import dentro de
> `ITEditorView.qml`.

### 3. Añadir el rol IT como un tab en `Main.qml`

#### 3.1 — Ampliar `activeTab` a 6 tabs

Asumiendo que ya integraste el Supervisor (tab 2), el orden de tabs queda:

```
0=Grabación · 1=Clips · 2=Supervisor · 3=IT · 4=Mini-modo · 5=Ajustes
```

#### 3.2 — Atajos

```qml
Shortcut { sequence: "Ctrl+1"; onActivated: root.activeTab = 0 }
Shortcut { sequence: "Ctrl+2"; onActivated: root.activeTab = 1 }
Shortcut { sequence: "Ctrl+3"; onActivated: root.activeTab = 2 }
Shortcut { sequence: "Ctrl+4"; onActivated: root.activeTab = 3 }
Shortcut { sequence: "Ctrl+5"; onActivated: root.activeTab = 4 }
Shortcut { sequence: "Ctrl+6"; onActivated: root.activeTab = 5 }
```

#### 3.3 — Añadir IT al modelo de tabs

```qml
model: [
    { label: "Grabación",  key: "⌘1", idx: 0 },
    { label: "Clips",      key: "⌘2", idx: 1 },
    { label: "Supervisor", key: "⌘3", idx: 2 },
    { label: "IT",         key: "⌘4", idx: 3 },
    { label: "Mini-modo",  key: "⌘5", idx: 4 },
    { label: "Ajustes",    key: "⌘6", idx: 5 },
]
```

#### 3.4 — Re-numerar tabs siguientes

Mini-modo: `activeTab === 3` → `activeTab === 4`
Ajustes:   `activeTab === 4` → `activeTab === 5`

(Si no integraste Supervisor antes, ajusta los índices: IT = 2, Mini = 3,
Ajustes = 4.)

#### 3.5 — Insertar el bloque del tab IT

Entre el tab Supervisor y Mini-modo:

```qml
// ── Tab 3 — IT Editor ─────────────────────────────────────────
Item {
    anchors.fill: parent
    opacity: root.activeTab === 3 ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

    W.ITEditorView {
        anchors.fill: parent
    }
} // Tab 3
```

## Conectar a backend Python

`ITEditorView` está actualmente con datos mock. Para producción:

```qml
W.ITEditorView {
    anchors.fill: parent
    notification: backend.currentRequest        // null cuando no hay solicitudes
    saveState:    backend.uploadState

    // las acciones se manejan emitiendo señales hacia Python:
    Connections {
        target: backend
        function onNewRequest()    { /* el binding ya actualiza notification */ }
    }
}
```

El componente expone estos eventos a través de los signals de sus hijos
(`NotificationStrip.accepted`, `OutputPanel.saveRequested`, etc.). El
patrón recomendado es escuchar esos signals dentro del bloque
`W.NotificationStrip { … }` / `W.OutputPanel { … }` en `ITEditorView` y
llamar a métodos expuestos por Python via QML registration:

```qml
W.NotificationStrip {
    ...
    onAccepted: backend.acceptRequest(notification.id)
    onDeclined: backend.postponeRequest(notification.id, 5 /* min */)
}
W.OutputPanel {
    ...
    onSaveRequested: backend.uploadToOneDrive()
    onLinkRequested: backend.generateShareLink()
    onLinkCopied:    backend.copyToClipboard(shareLink)
}
```

## Schema de la notificación (websocket payload)

```json
{
  "id": "REQ-2026-0612-014",
  "ts": "14:27:42",
  "arrived": "hace 1 min",
  "supervisor": {
    "name":     "Ana Ramírez",
    "role":     "Supervisor · NOC-A",
    "initials": "AR"
  },
  "payload": {
    "operator":    "Operator-28",
    "start":       "2026-06-09 14:02:11",
    "end":         "2026-06-09 14:18:34",
    "description": "…"
  },
  "filePath": "/SIG-SLC-Storage/raw/2026-06-09/operator-28/14-02-11_event.mp4"
}
```

Sin video adjunto — solo metadata e instrucción de texto, como pide el brief.

## Atajos

| Tecla     | Acción                                    |
|-----------|-------------------------------------------|
| `Space`   | Play / pause del preview                  |
| `I` / `O` | Marcar IN / OUT en el playhead actual     |
| `Enter`   | Aceptar notificación entrante             |
| `Esc`     | Cerrar panel expandido de instrucciones   |

## Decisiones de diseño

- **Una solicitud a la vez** — sin lista, sin cola visible. Cuando hay una
  tarea activa, la barra superior es un strip compacto; cuando llega una
  nueva (solo posible si no hay activa), se convierte en hero card.
- **Archivo pre-resuelto** — el árbol del NAS se expande hasta la ruta
  exacta y resalta el archivo solicitado con chip `SOLICITADO`.
- **Tres áreas paralelas** — NAS / Editor / OneDrive en columnas porque
  el flujo no es lineal: el IT puede volver a inspeccionar otros archivos
  mientras edita o ya está subiendo.
- **Acentos por servicio** — teal (#22D3EE) para NAS local, azul cloud
  (#60A5FA) para OneDrive, indigo (`accentMonitor`) para el editor.
  Mantiene la paleta de Tokens y añade dos brand tints específicas.
- **Sin generación de SVG complejos** — el preview es un patrón Canvas
  de rayas + vignette, no un dibujo a mano.
