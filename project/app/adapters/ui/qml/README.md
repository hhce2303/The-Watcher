# The Watcher — QML Integration Package

Componentes QML/Qt Quick listos para integrar en tu proyecto PySide6.
Este paquete contiene **únicamente las piezas nuevas** del diseño actualizado
(las que aún no existen en tu `Main.qml`). El sidebar de pantallas y la vista
de Clips ya están en tu archivo actual — puedes mejorarlos progresivamente.

---

## Estructura

```
prototype/qml/
├── qmldir                     # Registro del módulo Watcher
├── Tokens.qml                 # Singleton con design tokens
├── BufferTimeline.qml         # Visualización del rolling buffer de 2 min
├── PreRollOverlay.qml         # Countdown 3-2-1 al marcar evento
├── AnnotationModal.qml        # Modal de etiquetado de eventos
├── MiniMode.qml               # Ventana flotante always-on-top
├── Statusbar.qml              # Barra inferior con estado de grabación
├── HealthBadge.qml            # Lectura CPU / DISK / FPS para el titlebar
├── SettingsView.qml           # Pantalla completa de ajustes (7 secciones)
└── Components/
    ├── qmldir
    ├── WToggle.qml            # Switch on/off
    ├── WStepper.qml           # Input numérico con − / +
    ├── WDropdown.qml          # ComboBox estilizado
    ├── WSeg.qml               # Segmented radio
    ├── WPathInput.qml         # Path + botón EXAMINAR
    ├── WHotkey.qml            # Visualización de atajos (kbd)
    └── WSettingsRow.qml       # Fila de formulario label + helper + control
```

---

## Tokens compartidos

`Tokens.qml` es un **singleton**. Todos los demás componentes lo consumen.
Si ya tienes un `QtObject { id: kw }` inline en `Main.qml`, puedes:

- **Opción A** — Mantener tu `kw` y reemplazar internamente `W.Tokens.bgBase`
  por `kw.bgBase` (find & replace en los archivos del paquete).
- **Opción B (recomendada)** — Borrar el `kw` inline y dejar que todo
  consuma el singleton. Más mantenible.

Los valores son **idénticos** a los de tu `kw` actual.

---

## Cómo integrar en `Main.qml`

### 1. Agregar el import del módulo

En la cabecera de `Main.qml`:

```qml
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "qml" as W
import "qml/Components" as C
```

(Si registras el módulo en el `QML_IMPORT_PATH` o vía `engine.addImportPath()`,
puedes usar `import Watcher` y `import Watcher.Components` en su lugar.)

### 2. Registrar la ruta del módulo en Python

En tu bootstrap (`main.py`):

```python
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from pathlib import Path

engine = QQmlApplicationEngine()
qml_dir = Path(__file__).parent / "prototype" / "qml"
engine.addImportPath(str(qml_dir.parent))
engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "prototype" / "Main.qml")))
```

### 3. Sustituir piezas dentro de la pestaña GRABACIÓN

#### BufferTimeline — entre el audio row y el control bar

```qml
W.BufferTimeline {
    Layout.fillWidth: true
    recordSec: root.recordSecBacking
    eventMarkers: backend.eventMarkers  // [{ sec: 2495, tag: "lag spike" }, ...]
}
```

#### PreRollOverlay + AnnotationModal — overlay del Item del tab

Dentro del `Item` que contiene la pestaña de grabación, agregar al final:

```qml
W.PreRollOverlay {
    id: preRoll
    onFinished: annotation.open(root.recDuration)
    onCancelled: console.log("evento cancelado")
}

W.AnnotationModal {
    id: annotation
    onSaved: (tag, severity, note) => {
        backend.saveEvent(tag, severity, note)
    }
    onSkipped: backend.saveEvent("sin etiqueta", "low", "")
}
```

Y en el botón **MARCAR EVENTO** (existente), cambiar el `TapHandler.onTapped`:

```qml
TapHandler {
    onTapped: preRoll.start()
}
```

### 4. Reemplazar la statusbar inferior

```qml
W.Statusbar {
    Layout.fillWidth: true
    recordSec: root.recordSecBacking
    eventCount: backend.eventCount
    storagePath: "C:/WatcherData"
}
```

### 5. Agregar Health badges al hero bar

Dentro del `RowLayout` del hero bar, antes de los window controls:

```qml
W.HealthBadge { label: "CPU";  value: backend.cpuUsage;  valueColor: W.Tokens.accentOk }
W.HealthBadge { label: "DISK"; value: backend.diskRate;  valueColor: W.Tokens.accentPrimary }
W.HealthBadge { label: "FPS";  value: backend.fps }
```

### 6. Mini-mode — ventana separada

Mini-mode es un `Window` (no un `Item`) porque debe ser always-on-top.
Declarar al lado del `Window` principal:

```qml
W.MiniMode {
    id: miniWindow
    visible: false
    recordSec: root.recordSecBacking
    eventCount: backend.eventCount
    onMarkEvent: preRoll.start()
    onExpandRequested: {
        root.visible = true
        visible = false
    }
}
```

Y agregar un atajo `Ctrl+3` o un botón en el titlebar para hacer
`miniWindow.visible = !miniWindow.visible`.

### 7. Agregar la pestaña AJUSTES

En el `Repeater` de las tabs del hero bar:

```qml
model: ["GRABACIÓN", "CLIPS", "AJUSTES"]
```

Y agregar un tercer `Item` debajo de `// Tab 1 - Clips`:

```qml
Item {
    anchors.fill: parent
    opacity: root.activeTab === 2 ? 1.0 : 0.0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

    W.SettingsView {
        anchors.fill: parent
        // settings: pythonSettingsObject   ← bind a QObject de Python en producción
    }
}
```

---

## Conectar al backend Python

Los componentes están preparados para recibir datos via property binding.
Crea un `QObject` en Python expuesto al contexto QML:

```python
from PySide6.QtCore import QObject, Property, Signal

class WatcherBackend(QObject):
    recordSecChanged = Signal()
    eventCountChanged = Signal()
    eventMarkersChanged = Signal()

    @Property(int, notify=recordSecChanged)
    def recordSec(self): return self._record_sec

    @Property(int, notify=eventCountChanged)
    def eventCount(self): return len(self._events)

    @Property("QVariantList", notify=eventMarkersChanged)
    def eventMarkers(self):
        return [{"sec": e.sec, "tag": e.tag} for e in self._events]

    @Slot()
    def markEvent(self):
        # llamar al RecorderService
        ...

engine.rootContext().setContextProperty("backend", WatcherBackend())
```

Luego en QML:

```qml
W.BufferTimeline {
    recordSec: backend.recordSec
    eventMarkers: backend.eventMarkers
}
```

---

## Fuentes

Los componentes usan `Inter` y `JetBrains Mono`. Si no las tienes
registradas, hay dos opciones:

**A) Editar `Tokens.qml`** y cambiar `sans` / `mono` a `"Segoe UI"` / `"Consolas"`.

**B) Registrar las fuentes en Python** antes de cargar QML:

```python
from PySide6.QtGui import QFontDatabase

QFontDatabase.addApplicationFont("assets/fonts/Inter-Variable.ttf")
QFontDatabase.addApplicationFont("assets/fonts/JetBrainsMono-Variable.ttf")
```

---

## Vista previa

Para probar visualmente sin tu backend, abre los archivos directamente con
`qml prototype/qml/Main.qml` (ajustando el archivo principal). Los componentes
tienen valores de prueba inline en sus `property` declaraciones.

Cualquier duda sobre un componente específico, su API está documentada en el
comentario de cabecera del archivo `.qml`.
