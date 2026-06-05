import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "." as W
import "Components" as C

// SettingsView.qml — Full settings page with left rail + scrollable sections.
//
//   Use inside the tab content area. Bind to a settings model (QObject from
//   Python with NOTIFY signals) or use the inline `settings` property below
//   for prototyping.
//
//   Hotkey to open: Ctrl+4 (wire in Main.qml's Shortcut handlers).

Item {
    id: root

    // For prototyping. Replace with a Python-side QObject in production.
    property QtObject settings: QtObject {
        // Captura
        property string outputRes: "1080p"
        property int fps: 30
        property bool captureCursor: true
        property string composition: "side"
        property bool autoDetect: true
        // Encoder
        property string encoder: "nvenc"
        property string preset: "balance"
        property real bitrate: 6.4
        property string profile: "high"
        property int keyframe: 2
        property int segDur: 2
        property bool reencode: false
        // Eventos
        property int preroll: 120
        property int postroll: 120
        property int cooldown: 30
        property string annoMode: "full"
        property int countdown: 3
        // Storage
        property string segPath: "C:/WatcherData/segments"
        property string clipPath: "C:/WatcherData/clips"
        property string retention: "24h"
        property bool autoCleanup: true
        property real diskUsed: 18.4
        property int diskMax: 50
        // System
        property bool autoStart: true
        property bool autoRecord: true
        property bool minToTray: true
        property bool autoRestart: true
        property int diskWarn: 5
        property string logLevel: "info"
    }

    property string currentSection: "capture"

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── Left rail ────────────────────────────────────
        Rectangle {
            Layout.preferredWidth: 220
            Layout.fillHeight: true
            color: W.Tokens.bgSurface

            Rectangle {                     // right edge
                anchors.right: parent.right
                width: 1
                height: parent.height
                color: W.Tokens.borderBase
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                anchors.topMargin: 24
                spacing: 2

                Text {
                    Layout.leftMargin: 12
                    Layout.bottomMargin: 8
                    text: "AJUSTES"
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.mono
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.6
                }

                Repeater {
                    model: [
                        { id: "capture",  label: "Captura"        },
                        { id: "encoder",  label: "Encoder"        },
                        { id: "events",   label: "Eventos"        },
                        { id: "audio",    label: "Audio"          },
                        { id: "hotkeys",  label: "Atajos"         },
                        { id: "storage",  label: "Almacenamiento" },
                        { id: "system",   label: "Sistema"        }
                    ]
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34

                        property bool active: root.currentSection === modelData.id

                        radius: W.Tokens.rSm
                        color: active ? W.Tokens.primaryDim
                              : (hvr.hovered ? Qt.rgba(1,1,1,0.04) : "transparent")
                        Behavior on color { ColorAnimation { duration: 120 } }

                        HoverHandler { id: hvr }
                        TapHandler   { onTapped: root.currentSection = modelData.id }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.topMargin: 6
                            anchors.bottomMargin: 6
                            width: 2
                            height: parent.height - 12
                            color: active ? W.Tokens.accentPrimary : "transparent"
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: active ? W.Tokens.textPrimary : W.Tokens.textMuted
                            font.family: W.Tokens.sans
                            font.pixelSize: 12
                            font.weight: Font.Medium
                            Behavior on color { ColorAnimation { duration: 120 } }
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // Version footer
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: W.Tokens.borderBase
                }
                ColumnLayout {
                    Layout.margins: 12
                    spacing: 4

                    RowLayout {
                        Text {
                            text: "VERSIÓN"
                            color: W.Tokens.textDim
                            font.family: W.Tokens.mono
                            font.pixelSize: 9
                            font.letterSpacing: 1.0
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: "0.8.2"
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 9
                        }
                    }
                    RowLayout {
                        Text {
                            text: "BUILD"
                            color: W.Tokens.textDim
                            font.family: W.Tokens.mono
                            font.pixelSize: 9
                            font.letterSpacing: 1.0
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: "2026.05.24"
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 9
                        }
                    }
                }
            }
        }

        // ── Section content ──────────────────────────────
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: sectionLoader.implicitHeight + 80
            clip: true

            ColumnLayout {
                id: sectionLoader
                width: Math.min(parent.width - 96, 820)
                x: 48
                y: 32
                spacing: 36

                Loader {
                    Layout.fillWidth: true
                    sourceComponent:
                        root.currentSection === "capture"   ? captureSection
                      : root.currentSection === "encoder"   ? encoderSection
                      : root.currentSection === "events"    ? eventsSection
                      : root.currentSection === "audio"     ? audioSection
                      : root.currentSection === "hotkeys"   ? hotkeysSection
                      : root.currentSection === "storage"   ? storageSection
                      : root.currentSection === "system"    ? systemSection
                      : null
                }
            }
        }
    }

    // ── Section header (helper component) ────────────────
    component SectionHead : ColumnLayout {
        property string title: ""
        property string subtitle: ""
        property string badge: ""

        Layout.fillWidth: true
        spacing: 6

        RowLayout {
            spacing: 10
            Text {
                text: parent.parent.title
                color: W.Tokens.textPrimary
                font.family: W.Tokens.sans
                font.pixelSize: 20
                font.weight: Font.DemiBold
            }
            Rectangle {
                visible: parent.parent.badge !== ""
                Layout.preferredHeight: 20
                Layout.preferredWidth: badgeTxt.implicitWidth + 14
                radius: W.Tokens.rXs
                color: Qt.rgba(W.Tokens.accentYellow.r,
                               W.Tokens.accentYellow.g,
                               W.Tokens.accentYellow.b, 0.10)
                border.color: Qt.rgba(W.Tokens.accentYellow.r,
                                      W.Tokens.accentYellow.g,
                                      W.Tokens.accentYellow.b, 0.30)
                border.width: 1
                Text {
                    id: badgeTxt
                    anchors.centerIn: parent
                    text: parent.parent.parent.badge
                    color: W.Tokens.accentYellow
                    font.family: W.Tokens.mono
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.2
                }
            }
            Item { Layout.fillWidth: true }
        }

        Text {
            visible: parent.subtitle !== ""
            text: parent.subtitle
            color: W.Tokens.textMuted
            font.family: W.Tokens.sans
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: 8
            Layout.preferredHeight: 1
            color: W.Tokens.borderBase
        }
    }

    // ─── Section components ────────────────────────────────

    Component {
        id: captureSection
        ColumnLayout {
            spacing: 0

            SectionHead {
                title: "Captura"
                subtitle: "Configura cómo se captura el video desde las pantallas seleccionadas."
            }

            C.WSettingsRow {
                label: "Resolución de salida"
                helper: "Tamaño del clip final. La fuente se escala manteniendo aspect ratio."
                C.WSeg {
                    model: [
                        { value: "1080p",  label: "1080p" },
                        { value: "1440p",  label: "1440p" },
                        { value: "native", label: "Nativo" }
                    ]
                    currentValue: root.settings.outputRes
                    onSelected: root.settings.outputRes = value
                }
            }

            C.WSettingsRow {
                label: "Frames por segundo"
                helper: "30 fps es suficiente para captura de pantalla y reduce CPU."
                C.WSeg {
                    model: [
                        { value: 24, label: "24" },
                        { value: 30, label: "30" },
                        { value: 60, label: "60" }
                    ]
                    currentValue: root.settings.fps
                    onSelected: root.settings.fps = value
                }
            }

            C.WSettingsRow {
                label: "Mostrar cursor en grabación"
                helper: "Incluye el puntero del mouse en el clip generado."
                C.WToggle {
                    checked: root.settings.captureCursor
                    onToggled: root.settings.captureCursor = checked
                }
            }
        }
    }

    Component {
        id: encoderSection
        ColumnLayout {
            spacing: 0

            SectionHead {
                title: "Encoder"
                subtitle: "FFmpeg orquesta la codificación. Se detecta automáticamente el encoder por hardware disponible."
                badge: "Hardware detectado"
            }

            C.WSettingsRow {
                label: "Encoder"
                helper: "NVENC usa el chip dedicado de la GPU NVIDIA. Recomendado."
                C.WDropdown {
                    boxWidth: 260
                    model: [
                        "H.264 · NVENC (GPU NVIDIA)",
                        "H.264 · QuickSync (Intel)",
                        "H.264 · AMF (AMD)",
                        "H.264 · x264 (CPU)",
                        "H.265 · NVENC HEVC"
                    ]
                    currentIndex: 0
                }
            }

            C.WSettingsRow {
                label: "Preset"
                helper: "Más rápido = menos CPU, archivo más grande."
                C.WSeg {
                    model: ["veloz", "balance", "calidad"]
                    currentValue: root.settings.preset
                    onSelected: root.settings.preset = value
                }
            }

            C.WSettingsRow {
                label: "Bitrate"
                helper: "Calidad del video en megabits por segundo."
                C.WStepper {
                    boxWidth: 120
                    value: root.settings.bitrate
                    min: 1; max: 50; step: 0.5
                    unit: "Mbps"
                    onValueChanged: root.settings.bitrate = value
                }
            }
        }
    }

    Component {
        id: eventsSection
        ColumnLayout {
            spacing: 0

            SectionHead {
                title: "Eventos"
                subtitle: "Ventana de captura alrededor de cada evento marcado."
            }

            C.WSettingsRow {
                label: "Pre-roll"
                helper: "Segundos antes del evento que se incluyen en el clip."
                C.WStepper {
                    value: root.settings.preroll
                    min: 10; max: 600; step: 10; unit: "seg"
                    onValueChanged: root.settings.preroll = value
                }
            }
            C.WSettingsRow {
                label: "Post-roll"
                helper: "Segundos después del evento que se siguen grabando."
                C.WStepper {
                    value: root.settings.postroll
                    min: 10; max: 600; step: 10; unit: "seg"
                    onValueChanged: root.settings.postroll = value
                }
            }
            C.WSettingsRow {
                label: "Cooldown entre eventos"
                helper: "Tiempo mínimo entre dos pulsaciones de MARCAR EVENTO."
                C.WStepper {
                    value: root.settings.cooldown
                    min: 0; max: 120; step: 5; unit: "seg"
                    onValueChanged: root.settings.cooldown = value
                }
            }
            C.WSettingsRow {
                label: "Countdown pre-roll"
                helper: "Segundos de cuenta atrás antes de capturar el evento."
                C.WStepper {
                    value: root.settings.countdown
                    min: 0; max: 10; step: 1; unit: "seg"
                    onValueChanged: root.settings.countdown = value
                }
            }
        }
    }

    Component {
        id: audioSection
        ColumnLayout {
            spacing: 0
            SectionHead { title: "Audio"; subtitle: "Captura de audio del sistema y del micrófono." }

            C.WSettingsRow {
                label: "Dispositivo de entrada"
                C.WDropdown {
                    boxWidth: 280
                    model: [
                        "Microphone (Realtek Audio)",
                        "Headset Mic (USB Audio)",
                        "AirPods Pro 2",
                        "Sin micrófono"
                    ]
                    currentIndex: 0
                }
            }
            C.WSettingsRow {
                label: "Capturar audio del sistema"
                helper: "Incluye el audio del sistema en el clip (output loopback)."
                C.WToggle { checked: true }
            }
        }
    }

    Component {
        id: hotkeysSection
        ColumnLayout {
            spacing: 0
            SectionHead { title: "Atajos de teclado"
                subtitle: "Click sobre cualquier atajo para reasignarlo." }

            Repeater {
                model: [
                    { label: "Marcar evento",  keys: ["Space"] },
                    { label: "Cancelar acción", keys: ["Esc"] },
                    { label: "Ir a Grabación",  keys: ["Ctrl", "1"] },
                    { label: "Ir a Clips",      keys: ["Ctrl", "2"] },
                    { label: "Mini-modo",       keys: ["Ctrl", "3"] },
                    { label: "Ajustes",         keys: ["Ctrl", "4"] }
                ]
                delegate: C.WSettingsRow {
                    label: modelData.label
                    C.WHotkey { keys: modelData.keys }
                }
            }
        }
    }

    Component {
        id: storageSection
        ColumnLayout {
            spacing: 16
            SectionHead { title: "Almacenamiento"
                subtitle: "Dónde se guardan los segmentos del buffer y los clips finales." }

            // Disk usage card
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 110
                radius: W.Tokens.rMd
                color: W.Tokens.bgSurface
                border.color: W.Tokens.borderBase
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 20
                    spacing: 12

                    RowLayout {
                        ColumnLayout {
                            spacing: 4
                            Text {
                                text: "USO DE DISCO"
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.mono
                                font.pixelSize: 9
                                font.letterSpacing: 1.4
                            }
                            RowLayout {
                                spacing: 6
                                Text {
                                    text: root.settings.diskUsed.toFixed(1)
                                    color: W.Tokens.textPrimary
                                    font.family: W.Tokens.sans
                                    font.pixelSize: 22
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: "/ " + root.settings.diskMax + " GB"
                                    color: W.Tokens.textMuted
                                    font.family: W.Tokens.sans
                                    font.pixelSize: 14
                                }
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: Math.round((root.settings.diskUsed / root.settings.diskMax) * 100) + "%"
                            color: W.Tokens.accentPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 20
                            font.weight: Font.Bold
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 6
                        radius: 3
                        color: W.Tokens.bgBase

                        Rectangle {
                            width: parent.width * (root.settings.diskUsed / root.settings.diskMax)
                            height: parent.height
                            radius: 3
                            color: W.Tokens.accentPrimary
                            Behavior on width { NumberAnimation { duration: 240 } }
                        }
                    }
                }
            }

            C.WSettingsRow {
                label: "Segmentos del buffer"
                helper: "Archivos temporales del rolling buffer."
                vertical: true
                C.WPathInput {
                    width: parent.width
                    path: root.settings.segPath
                    onPathChanged: root.settings.segPath = path
                }
            }
            C.WSettingsRow {
                label: "Clips finales"
                vertical: true
                C.WPathInput {
                    width: parent.width
                    path: root.settings.clipPath
                    onPathChanged: root.settings.clipPath = path
                }
            }
        }
    }

    Component {
        id: systemSection
        ColumnLayout {
            spacing: 0
            SectionHead { title: "Sistema"
                subtitle: "Comportamiento al iniciar y en background." }

            C.WSettingsRow {
                label: "Iniciar con Windows"
                helper: "The Watcher arranca minimizado al iniciar sesión."
                C.WToggle {
                    checked: root.settings.autoStart
                    onToggled: root.settings.autoStart = checked
                }
            }
            C.WSettingsRow {
                label: "Iniciar grabación al abrir"
                helper: "Comienza el rolling buffer automáticamente."
                C.WToggle {
                    checked: root.settings.autoRecord
                    onToggled: root.settings.autoRecord = checked
                }
            }
            C.WSettingsRow {
                label: "Minimizar a la bandeja"
                helper: "La app sigue grabando en background."
                C.WToggle {
                    checked: root.settings.minToTray
                    onToggled: root.settings.minToTray = checked
                }
            }
            C.WSettingsRow {
                label: "Reiniciar recorder si crashea"
                C.WToggle {
                    checked: root.settings.autoRestart
                    onToggled: root.settings.autoRestart = checked
                }
            }
            C.WSettingsRow {
                label: "Nivel de log"
                C.WSeg {
                    model: ["error", "warn", "info", "debug"]
                    currentValue: root.settings.logLevel
                    onSelected: root.settings.logLevel = value
                }
            }
        }
    }
}
