import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "qml" as W
import "qml/Components" as C

Window {
    id: root
    visibility: Window.FullScreen
    visible: true
    title: "The Watcher"
    flags: Qt.Window

    // ── App state ─────────────────────────────────────────────────────────────
    property int    activeTab:        0   // 0=Grabación 1=Clips 2=IT 3=Mini-modo 4=Ajustes
    property bool   isRecording:      true
    property string recDuration:      "00:42:52"
    property int    recordSecBacking: 2572
    property int    eventCount:       3
    property int    selectedClip:     0

    // Screen state
    property var screens: [
        { name: "SCREEN 1", res: "1920×1080", active: true,  idx: 0 },
        { name: "SCREEN 2", res: "1920×1080", active: true,  idx: 1 },
        { name: "SCREEN 3", res: "2560×1440", active: false, idx: 2 },
    ]
    readonly property int activeScreenCount: {
        var n = 0
        for (var i = 0; i < screens.length; i++) if (screens[i].active) n++
        return n
    }

    // ── Keyboard shortcuts ────────────────────────────────────────────────────
    Shortcut { sequence: "Ctrl+1"; onActivated: root.activeTab = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: root.activeTab = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: root.activeTab = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: root.activeTab = 3 }
    Shortcut { sequence: "Ctrl+5"; onActivated: root.activeTab = 4 }
    Shortcut { sequence: "Space";  enabled: root.activeTab === 0; onActivated: preRoll.start() }

    // ── Mini-mode window ──────────────────────────────────────────────────────
    W.MiniMode {
        id: miniWindow
        visible: false
        recordSec: root.recordSecBacking
        eventCount: root.eventCount
        onMarkEvent: preRoll.start()
        onExpandRequested: { root.visible = true; miniWindow.visible = false }
    }

    // ── Live clock ────────────────────────────────────────────────────────────
    Timer {
        interval: 1000; running: root.isRecording; repeat: true
        onTriggered: {
            root.recordSecBacking += 1
            var t = root.recordSecBacking
            root.recDuration = String(Math.floor(t/3600)).padStart(2,"0") + ":" +
                               String(Math.floor((t%3600)/60)).padStart(2,"0") + ":" +
                               String(t%60).padStart(2,"0")
        }
    }

    // ── Root ─────────────────────────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: W.Tokens.bgBase

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // ── Hero bar ──────────────────────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true
                height: 48
                color: W.Tokens.bgElevated
                z: 10

                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }

                RowLayout {
                    anchors { fill: parent; leftMargin: 16; rightMargin: 12 }
                    spacing: 0

                    // Recording dot
                    Item {
                        width: 12; height: 12
                        Rectangle {
                            anchors.centerIn: parent; width: 8; height: 8; radius: 4
                            color: root.isRecording ? W.Tokens.accentRecord : W.Tokens.textMuted
                            QtObject {
                                id: dotPulse; property real s: 1.0
                                SequentialAnimation on s {
                                    running: root.isRecording; loops: Animation.Infinite
                                    NumberAnimation { to: 1.3; duration: 800; easing.type: Easing.InOutSine }
                                    NumberAnimation { to: 0.8; duration: 800; easing.type: Easing.InOutSine }
                                }
                            }
                            transform: Scale { origin.x: 4; origin.y: 4; xScale: dotPulse.s; yScale: dotPulse.s }
                        }
                    }

                    Item { width: 10 }

                    // App name + version
                    Row {
                        spacing: 6
                        Text {
                            text: "THE WATCHER"
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.sans; font.pixelSize: 13; font.weight: Font.Bold; font.letterSpacing: 2
                        }
                        Text {
                            text: "v0.8.2"
                            color: W.Tokens.textDim
                            font.family: W.Tokens.mono; font.pixelSize: 10
                            anchors.baseline: undefined
                        }
                    }

                    Item { width: 24 }

                    // ── Tabs ─────────────────────────────────────────────────
                    Row {
                        spacing: 2
                        Repeater {
                            model: [
                                { label: "Grabación",  key: "⌘1", idx: 0 },
                                { label: "Clips",      key: "⌘2", idx: 1 },
                                { label: "IT",         key: "⌘3", idx: 2 },
                                { label: "Mini-modo",  key: "⌘4", idx: 3 },
                                { label: "Ajustes",    key: "⌘5", idx: 4 },
                            ]
                            delegate: Rectangle {
                                property bool sel: root.activeTab === modelData.idx
                                width: row.implicitWidth + 20; height: 32
                                radius: W.Tokens.rPill
                                color: sel ? W.Tokens.accentPrimary : "transparent"
                                Behavior on color { ColorAnimation { duration: 160 } }

                                HoverHandler { id: th }
                                Rectangle {
                                    anchors.fill: parent; radius: parent.radius
                                    color: W.Tokens.textPrimary
                                    opacity: th.hovered && !parent.sel ? 0.06 : 0
                                    Behavior on opacity { NumberAnimation { duration: 100 } }
                                }
                                TapHandler { onTapped: root.activeTab = modelData.idx }

                                Row {
                                    id: row
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Text {
                                        text: modelData.label
                                        color: parent.parent.sel ? W.Tokens.bgBase : W.Tokens.textMuted
                                        font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.SemiBold
                                        Behavior on color { ColorAnimation { duration: 160 } }
                                    }
                                    Rectangle {
                                        width: kTxt.implicitWidth + 8; height: 16; radius: 3
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: parent.parent.sel
                                            ? Qt.rgba(0,0,0,0.18)
                                            : W.Tokens.bgBase
                                        Text {
                                            id: kTxt
                                            anchors.centerIn: parent
                                            text: modelData.key
                                            color: parent.parent.parent.sel ? W.Tokens.bgBase : W.Tokens.textDim
                                            font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Item { Layout.fillWidth: true }

                    // ── Health badges ─────────────────────────────────────────
                    Row {
                        spacing: 14
                        Row {
                            spacing: 5
                            Rectangle { width: 5; height: 5; radius: 3; color: W.Tokens.accentOk; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "CPU"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 10 }
                            Text { text: "4.2%"; color: W.Tokens.accentOk; font.family: W.Tokens.mono; font.pixelSize: 10; font.weight: Font.Bold }
                        }
                        Row {
                            spacing: 5
                            Text { text: "⬜"; color: W.Tokens.textMuted; font.pixelSize: 9; anchors.verticalCenter: parent.verticalCenter }
                            Text { text: "DISK"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 10 }
                            Text { text: "42 MB/s"; color: W.Tokens.accentPrimary; font.family: W.Tokens.mono; font.pixelSize: 10; font.weight: Font.Bold }
                        }
                        Row {
                            spacing: 5
                            Text { text: "FPS"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 10 }
                            Text { text: "30.00"; color: W.Tokens.textPrimary; font.family: W.Tokens.mono; font.pixelSize: 10; font.weight: Font.Bold }
                        }
                    }

                    Item { width: 16 }

                    // ── Window controls ───────────────────────────────────────
                    Row {
                        spacing: 2
                        Repeater {
                            model: [
                                { icon: "−", hover: "#3D4555", act: 0 },
                                { icon: "□", hover: "#3D4555", act: 1 },
                                { icon: "✕", hover: "#C42B1C", act: 2 },
                            ]
                            delegate: Rectangle {
                                width: 28; height: 28; radius: W.Tokens.rXs
                                color: wh.hovered ? modelData.hover : "transparent"
                                Behavior on color { ColorAnimation { duration: 80 } }
                                HoverHandler { id: wh }
                                Text { anchors.centerIn: parent; text: modelData.icon; color: wh.hovered ? "#FFF" : W.Tokens.textMuted; font.pixelSize: 11 }
                                TapHandler {
                                    onTapped: {
                                        if (modelData.act === 0) root.showMinimized()
                                        else if (modelData.act === 1) root.visibility === Window.FullScreen ? root.showNormal() : root.showFullScreen()
                                        else root.close()
                                    }
                                }
                            }
                        }
                    }
                }
            } // hero bar

            // ── Tab content ───────────────────────────────────────────────────
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                // ── Tab 0 — Grabación ─────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 0 ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                    RowLayout {
                        anchors.fill: parent
                        spacing: 0

                        // ── Left sidebar: screen selector ─────────────────────
                        Rectangle {
                            Layout.preferredWidth: 230
                            Layout.fillHeight: true
                            color: W.Tokens.bgSurface

                            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: W.Tokens.borderBase }

                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0

                                // Sidebar header
                                Rectangle {
                                    Layout.fillWidth: true; height: 44
                                    color: "transparent"
                                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }
                                    RowLayout {
                                        anchors { fill: parent; leftMargin: 16; rightMargin: 12 }
                                        Text {
                                            text: "PANTALLAS"
                                            color: W.Tokens.textMuted
                                            font.family: W.Tokens.sans; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.4
                                        }
                                        Item { Layout.fillWidth: true }
                                        Rectangle {
                                            width: badge.implicitWidth + 12; height: 18; radius: W.Tokens.rPill
                                            color: W.Tokens.primaryDim
                                            Text {
                                                id: badge; anchors.centerIn: parent
                                                text: root.activeScreenCount + "/" + root.screens.length
                                                color: W.Tokens.accentPrimary
                                                font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                            }
                                        }
                                    }
                                }

                                // Screen list
                                Repeater {
                                    model: root.screens
                                    delegate: Rectangle {
                                        Layout.fillWidth: true
                                        height: 58
                                        color: modelData.active ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.06) : "transparent"
                                        Behavior on color { ColorAnimation { duration: 150 } }

                                        HoverHandler { id: sh }
                                        Rectangle {
                                            anchors.fill: parent; color: W.Tokens.textPrimary
                                            opacity: sh.hovered ? 0.03 : 0
                                            Behavior on opacity { NumberAnimation { duration: 100 } }
                                        }
                                        TapHandler {
                                            onTapped: {
                                                var copy = root.screens.slice()
                                                copy[index] = { name: copy[index].name, res: copy[index].res, active: !copy[index].active, idx: copy[index].idx }
                                                root.screens = copy
                                            }
                                        }

                                        // Left active bar
                                        Rectangle {
                                            width: 3; height: parent.height
                                            color: modelData.active ? W.Tokens.accentPrimary : "transparent"
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }

                                        // Bottom divider
                                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase; opacity: 0.5 }

                                        RowLayout {
                                            anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                                            spacing: 10

                                            // Checkbox
                                            Rectangle {
                                                width: 18; height: 18; radius: 4
                                                color: modelData.active ? W.Tokens.accentPrimary : "transparent"
                                                border.color: modelData.active ? W.Tokens.accentPrimary : W.Tokens.borderSubtle
                                                border.width: 1.5
                                                Behavior on color { ColorAnimation { duration: 150 } }
                                                Text {
                                                    anchors.centerIn: parent; text: "✓"
                                                    color: modelData.active ? W.Tokens.bgBase : "transparent"
                                                    font.pixelSize: 10; font.weight: Font.Bold
                                                }
                                            }

                                            // Name + resolution
                                            Column {
                                                Layout.fillWidth: true
                                                spacing: 3
                                                Text {
                                                    text: modelData.name
                                                    color: modelData.active ? W.Tokens.textPrimary : W.Tokens.textMuted
                                                    font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.Bold
                                                    Behavior on color { ColorAnimation { duration: 150 } }
                                                }
                                                Text {
                                                    text: modelData.res
                                                    color: W.Tokens.textDim
                                                    font.family: W.Tokens.mono; font.pixelSize: 10
                                                }
                                            }

                                            // Index number
                                            Text {
                                                text: String(modelData.idx + 1).padStart(2, "0")
                                                color: modelData.active ? W.Tokens.accentMonitor : W.Tokens.borderSubtle
                                                font.family: W.Tokens.mono; font.pixelSize: 22; font.weight: Font.Bold
                                                Behavior on color { ColorAnimation { duration: 150 } }
                                            }
                                        }
                                    }
                                }

                                Item { Layout.fillHeight: true }

                                // Sidebar footer: encoder info
                                Rectangle {
                                    Layout.fillWidth: true
                                    height: 82
                                    color: "transparent"
                                    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: W.Tokens.borderBase }

                                    ColumnLayout {
                                        anchors { fill: parent; margins: 14 }
                                        spacing: 6
                                        Repeater {
                                            model: [
                                                { label: "ENCODER", value: "H.264 · NVENC" },
                                                { label: "BITRATE", value: "6.4 Mbps" },
                                                { label: "FPS",     value: "30.00" },
                                            ]
                                            delegate: RowLayout {
                                                Layout.fillWidth: true
                                                Text {
                                                    text: modelData.label
                                                    color: W.Tokens.textDim
                                                    font.family: W.Tokens.mono; font.pixelSize: 9; font.letterSpacing: 0.8
                                                }
                                                Item { Layout.fillWidth: true }
                                                Text {
                                                    text: modelData.value
                                                    color: W.Tokens.textMuted
                                                    font.family: W.Tokens.mono; font.pixelSize: 10; font.weight: Font.DemiBold
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        } // sidebar

                        // ── Right content ─────────────────────────────────────
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 0

                            // Preview header bar
                            Rectangle {
                                Layout.fillWidth: true
                                height: 36
                                color: W.Tokens.bgElevated
                                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }

                                RowLayout {
                                    anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                                    spacing: 12

                                    // LIVE badge
                                    Rectangle {
                                        width: liveLbl.implicitWidth + 14; height: 20; radius: W.Tokens.rXs
                                        color: W.Tokens.recordDim
                                        border.color: W.Tokens.accentRecord; border.width: 1
                                        Text {
                                            id: liveLbl; anchors.centerIn: parent
                                            text: "● LIVE · REC"
                                            color: W.Tokens.accentRecord
                                            font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 0.6
                                        }
                                    }

                                    Rectangle { width: 1; height: 14; color: W.Tokens.borderSubtle }

                                    Text {
                                        text: root.recDuration
                                        color: W.Tokens.textPrimary
                                        font.family: W.Tokens.mono; font.pixelSize: 12; font.weight: Font.Bold
                                    }

                                    Item { Layout.fillWidth: true }

                                    Text {
                                        text: "3840×1080"
                                        color: W.Tokens.textMuted
                                        font.family: W.Tokens.mono; font.pixelSize: 10
                                    }
                                    Rectangle { width: 1; height: 14; color: W.Tokens.borderSubtle }
                                    Text {
                                        text: root.activeScreenCount + "×SCREEN"
                                        color: W.Tokens.accentMonitor
                                        font.family: W.Tokens.mono; font.pixelSize: 10; font.weight: Font.Bold
                                    }
                                }
                            }

                            // Preview split area
                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true

                                Row {
                                    anchors.fill: parent
                                    Repeater {
                                        model: root.screens.filter(s => s.active)
                                        delegate: Rectangle {
                                            width: parent.width / root.activeScreenCount
                                            height: parent.height
                                            color: "#050A18"

                                            Rectangle {
                                                anchors.right: parent.right; width: 1; height: parent.height
                                                color: W.Tokens.borderBase
                                                visible: index < root.activeScreenCount - 1
                                            }

                                            // Screen number + name
                                            Row {
                                                anchors { top: parent.top; left: parent.left; margins: 12 }
                                                spacing: 8
                                                Rectangle {
                                                    width: numTxt.implicitWidth + 10; height: 20; radius: W.Tokens.rXs
                                                    color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.18)
                                                    Text {
                                                        id: numTxt; anchors.centerIn: parent
                                                        text: String(modelData.idx + 1).padStart(2, "0")
                                                        color: W.Tokens.accentPrimary
                                                        font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                                    }
                                                }
                                                Text {
                                                    text: modelData.name
                                                    color: W.Tokens.textMuted
                                                    font.family: W.Tokens.sans; font.pixelSize: 11; font.weight: Font.SemiBold
                                                    anchors.verticalCenter: parent.verticalCenter
                                                }
                                            }

                                            // Center monitor icon
                                            Column {
                                                anchors.centerIn: parent
                                                spacing: 8
                                                Text {
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    text: "🖥"
                                                    font.pixelSize: 32
                                                    opacity: 0.18
                                                }
                                            }

                                            // Bottom resolution
                                            Text {
                                                anchors { bottom: parent.bottom; right: parent.right; margins: 10 }
                                                text: modelData.res
                                                color: W.Tokens.textDim
                                                font.family: W.Tokens.mono; font.pixelSize: 9
                                            }
                                        }
                                    }
                                }
                            }

                            // Preview footer bar
                            Rectangle {
                                Layout.fillWidth: true
                                height: 30
                                color: W.Tokens.bgElevated
                                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: W.Tokens.borderBase }

                                RowLayout {
                                    anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                                    spacing: 12
                                    Text { text: "VISTA PREVIA"; color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 9; font.letterSpacing: 1 }
                                    Rectangle { width: 1; height: 10; color: W.Tokens.borderBase }
                                    Text { text: "30 fps"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 9 }
                                    Rectangle { width: 1; height: 10; color: W.Tokens.borderBase }
                                    Text { text: root.activeScreenCount + " src"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 9 }
                                    Item { Layout.fillWidth: true }
                                }
                            }

                            // ── Audio controller ──────────────────────────────
                            Rectangle {
                                Layout.fillWidth: true
                                height: 58
                                color: W.Tokens.bgSurface
                                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: W.Tokens.borderBase }

                                QtObject {
                                    id: vuState
                                    property bool muted: false
                                    property var  bars: [0.7,0.5,0.85,0.4,0.9,0.55,0.3,0.75,0.6,0.45,
                                                         0.8,0.35,0.65,0.5,0.7,0.4,0.9,0.6,0.5,0.3,
                                                         0.55,0.7,0.45,0.8,0.6]
                                    property real peakDb: -12.4
                                }
                                Timer {
                                    interval: 80; running: !vuState.muted && root.isRecording; repeat: true
                                    onTriggered: {
                                        var arr = []
                                        for (var i = 0; i < vuState.bars.length; i++) {
                                            var p = vuState.bars[i]
                                            arr.push(Math.max(0.05, Math.min(1.0, p + (Math.random()-0.48)*0.3)))
                                        }
                                        vuState.bars = arr
                                        vuState.peakDb = -12 + (Math.random()-0.5)*4
                                    }
                                }

                                RowLayout {
                                    anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                                    spacing: 12

                                    // Mic button
                                    Rectangle {
                                        width: 34; height: 34; radius: 8
                                        color: vuState.muted
                                            ? Qt.rgba(W.Tokens.accentRecord.r, W.Tokens.accentRecord.g, W.Tokens.accentRecord.b, 0.18)
                                            : W.Tokens.primaryDim
                                        border.color: vuState.muted ? W.Tokens.accentRecord : W.Tokens.accentPrimary; border.width: 1
                                        Behavior on color { ColorAnimation { duration: 150 } }
                                        HoverHandler { id: mh }
                                        TapHandler { onTapped: vuState.muted = !vuState.muted }
                                        Text { anchors.centerIn: parent; text: vuState.muted ? "🔇" : "🎤"; font.pixelSize: 15 }
                                    }

                                    // Device info
                                    Column {
                                        spacing: 2
                                        Text { text: "ENTRADA DE AUDIO"; color: W.Tokens.textDim; font.family: W.Tokens.sans; font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1 }
                                        Text {
                                            text: vuState.muted ? "Silenciado" : "Microphone (Realtek Audio)"
                                            color: vuState.muted ? W.Tokens.accentRecord : W.Tokens.textPrimary
                                            font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.DemiBold
                                            Behavior on color { ColorAnimation { duration: 150 } }
                                        }
                                    }

                                    Item { width: 4 }

                                    // VU bars
                                    Item {
                                        Layout.fillWidth: true
                                        height: 36
                                        Row {
                                            anchors.verticalCenter: parent.verticalCenter
                                            spacing: 2
                                            Repeater {
                                                model: vuState.bars.length
                                                delegate: Rectangle {
                                                    width: 5; height: 36; color: "transparent"
                                                    Rectangle {
                                                        anchors.bottom: parent.bottom
                                                        width: parent.width
                                                        height: vuState.muted ? 2 : Math.max(2, vuState.bars[index] * 36)
                                                        radius: 2
                                                        color: {
                                                            var l = vuState.bars[index]
                                                            if (vuState.muted) return W.Tokens.borderSubtle
                                                            if (l > 0.85) return W.Tokens.accentRecord
                                                            if (l > 0.65) return W.Tokens.accentYellow
                                                            return W.Tokens.accentPrimary
                                                        }
                                                        opacity: vuState.muted ? 0.25 : 0.9
                                                        Behavior on height  { NumberAnimation { duration: 70; easing.type: Easing.OutCubic } }
                                                        Behavior on color   { ColorAnimation { duration: 70 } }
                                                    }
                                                    Rectangle { anchors.fill: parent; radius: 2; color: W.Tokens.borderBase; z: -1 }
                                                }
                                            }
                                        }
                                    }

                                    // Peak dB
                                    Column {
                                        spacing: 2
                                        Text {
                                            text: vuState.peakDb.toFixed(1) + " dB"
                                            color: W.Tokens.textPrimary
                                            font.family: W.Tokens.mono; font.pixelSize: 11; font.weight: Font.Bold
                                        }
                                    }

                                    Rectangle { width: 1; height: 28; color: W.Tokens.borderBase }

                                    // Gain
                                    Row {
                                        spacing: 8
                                        Text { text: "GAIN"; color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 9; font.letterSpacing: 1; anchors.verticalCenter: parent.verticalCenter }
                                        Item {
                                            width: 90; height: 16; anchors.verticalCenter: parent.verticalCenter
                                            Rectangle {
                                                anchors.verticalCenter: parent.verticalCenter
                                                width: parent.width; height: 4; radius: 2; color: W.Tokens.borderBase
                                                Rectangle { width: parent.width * 0.72; height: 4; radius: 2; color: W.Tokens.accentPrimary }
                                            }
                                            Rectangle {
                                                x: 90 * 0.72 - 5; anchors.verticalCenter: parent.verticalCenter
                                                width: 10; height: 10; radius: 5
                                                color: W.Tokens.accentPrimary; border.color: W.Tokens.bgBase; border.width: 2
                                            }
                                        }
                                        Text { text: "72"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 10; anchors.verticalCenter: parent.verticalCenter }
                                    }
                                }
                            } // audio

                            // ── Buffer timeline ───────────────────────────────
                            W.BufferTimeline {
                                Layout.fillWidth: true
                                recordSec: root.recordSecBacking
                                eventMarkers: []
                            }

                            // ── Control bar ───────────────────────────────────
                            Rectangle {
                                Layout.fillWidth: true
                                height: 64
                                color: W.Tokens.bgSurface
                                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: W.Tokens.borderBase }

                                RowLayout {
                                    anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                                    spacing: 0

                                    // Recording state
                                    Column {
                                        spacing: 4
                                        Row {
                                            spacing: 8
                                            Rectangle { width: 6; height: 6; radius: 3; color: W.Tokens.accentRecord; anchors.verticalCenter: parent.verticalCenter }
                                            Text {
                                                text: root.recDuration
                                                color: W.Tokens.accentRecord
                                                font.family: W.Tokens.mono; font.pixelSize: 18; font.weight: Font.Bold
                                            }
                                            Text {
                                                text: "CONTINUA"
                                                color: W.Tokens.textDim
                                                font.family: W.Tokens.mono; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                        }
                                        Text {
                                            text: "⬜ C:/WatcherData/segments"
                                            color: W.Tokens.textDim
                                            font.family: W.Tokens.mono; font.pixelSize: 9
                                        }
                                    }

                                    Item { Layout.fillWidth: true }

                                    // MARCAR EVENTO
                                    Rectangle {
                                        height: 40
                                        width: evtRow.implicitWidth + 32
                                        radius: W.Tokens.rPill
                                        color: "transparent"
                                        border.color: W.Tokens.accentPrimary; border.width: 1.5

                                        HoverHandler { id: eh }
                                        TapHandler   { id: et; onTapped: preRoll.start() }

                                        scale: et.pressed ? 0.95 : eh.hovered ? 1.03 : 1.0
                                        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
                                        Rectangle {
                                            anchors.fill: parent; radius: parent.radius; color: W.Tokens.accentPrimary
                                            opacity: eh.hovered ? 0.12 : 0
                                            Behavior on opacity { NumberAnimation { duration: 130 } }
                                        }

                                        Row {
                                            id: evtRow
                                            anchors.centerIn: parent
                                            spacing: 10
                                            Text {
                                                text: "✦  MARCAR EVENTO"
                                                color: W.Tokens.accentPrimary
                                                font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.Bold
                                                anchors.verticalCenter: parent.verticalCenter
                                            }
                                            Rectangle {
                                                width: spTxt.implicitWidth + 10; height: 18; radius: W.Tokens.rXs
                                                color: W.Tokens.bgBase
                                                anchors.verticalCenter: parent.verticalCenter
                                                Text {
                                                    id: spTxt; anchors.centerIn: parent
                                                    text: "SPACE"
                                                    color: W.Tokens.textDim
                                                    font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                                }
                                            }
                                        }
                                    }

                                    Item { Layout.fillWidth: true }

                                    // Screen count
                                    Column {
                                        spacing: 2
                                        Text {
                                            anchors.right: parent.right
                                            text: root.activeScreenCount + "/" + root.screens.length
                                            color: W.Tokens.accentMonitor
                                            font.family: W.Tokens.mono; font.pixelSize: 20; font.weight: Font.Bold
                                        }
                                        Text {
                                            anchors.right: parent.right
                                            text: "PANTALLAS ACTIVAS"
                                            color: W.Tokens.textDim
                                            font.family: W.Tokens.mono; font.pixelSize: 9; font.letterSpacing: 0.8
                                        }
                                    }
                                }
                            } // control bar
                        } // right content ColumnLayout
                    } // recording RowLayout

                    // Overlays
                    W.PreRollOverlay {
                        id: preRoll
                        onFinished: annotation.open(root.recDuration)
                        onCancelled: console.log("cancelado")
                    }
                    W.AnnotationModal {
                        id: annotation
                        onSaved: (tag, severity, note) => { root.eventCount += 1 }
                        onSkipped: root.eventCount += 1
                    }
                } // Tab 0

                // ── Tab 1 — Clips ─────────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 1 ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                    RowLayout {
                        anchors.fill: parent; spacing: 0

                        Rectangle {
                            Layout.preferredWidth: 260; Layout.fillHeight: true
                            color: W.Tokens.bgSurface; border.color: W.Tokens.borderBase; border.width: 1

                            ColumnLayout {
                                anchors.fill: parent; spacing: 0
                                Rectangle {
                                    Layout.fillWidth: true; height: 44; color: "transparent"
                                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }
                                    Text {
                                        anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
                                        text: "CLIPS RECIENTES"; color: W.Tokens.textMuted
                                        font.family: W.Tokens.sans; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2
                                    }
                                }
                                ListView {
                                    Layout.fillWidth: true; Layout.fillHeight: true
                                    clip: true; spacing: 1
                                    model: ListModel {
                                        ListElement { clipName: "2026-05-24_09-00-00.mp4";        dur: "1h 00m"; date: "Hoy";    isEvent: false }
                                        ListElement { clipName: "2026-05-23_21-42-17_event.mp4"; dur: "4m 02s"; date: "Ayer";   isEvent: true  }
                                        ListElement { clipName: "2026-05-23_08-00-00.mp4";        dur: "1h 00m"; date: "Ayer";   isEvent: false }
                                        ListElement { clipName: "2026-05-22_14-23-55_event.mp4"; dur: "3m 44s"; date: "22 may"; isEvent: true  }
                                        ListElement { clipName: "2026-05-22_08-00-00.mp4";        dur: "1h 00m"; date: "22 may"; isEvent: false }
                                        ListElement { clipName: "2026-05-21_10-08-03_event.mp4"; dur: "4m 11s"; date: "21 may"; isEvent: true  }
                                    }
                                    delegate: Rectangle {
                                        width: parent.width; height: 62
                                        color: index === root.selectedClip ? Qt.rgba(W.Tokens.accentPrimary.r,W.Tokens.accentPrimary.g,W.Tokens.accentPrimary.b,0.08) : "transparent"
                                        Behavior on color { ColorAnimation { duration: 120 } }
                                        Rectangle {
                                            width: 3; height: parent.height
                                            color: index === root.selectedClip ? W.Tokens.accentPrimary : "transparent"
                                            Behavior on color { ColorAnimation { duration: 120 } }
                                        }
                                        HoverHandler { id: ch }
                                        Rectangle {
                                            anchors.fill: parent; color: W.Tokens.textPrimary
                                            opacity: ch.hovered && index !== root.selectedClip ? 0.04 : 0
                                            Behavior on opacity { NumberAnimation { duration: 100 } }
                                        }
                                        TapHandler { onTapped: root.selectedClip = index }
                                        Column {
                                            anchors.left: parent.left; anchors.leftMargin: 16
                                            anchors.right: parent.right; anchors.rightMargin: 10
                                            anchors.verticalCenter: parent.verticalCenter
                                            spacing: 5
                                            Text {
                                                width: parent.width; text: clipName; elide: Text.ElideMiddle
                                                color: index === root.selectedClip ? W.Tokens.textPrimary : W.Tokens.textMuted
                                                font.family: W.Tokens.mono; font.pixelSize: 10
                                                Behavior on color { ColorAnimation { duration: 120 } }
                                            }
                                            Row {
                                                spacing: 6
                                                Text { text: date; color: W.Tokens.textDim; font.family: W.Tokens.sans; font.pixelSize: 10 }
                                                Text { text: "·"; color: W.Tokens.borderSubtle; font.pixelSize: 10 }
                                                Text { text: dur; color: isEvent ? W.Tokens.accentRecord : W.Tokens.accentPrimary; font.family: W.Tokens.mono; font.pixelSize: 10 }
                                                Text { visible: isEvent; text: "evento"; color: Qt.rgba(W.Tokens.accentRecord.r,W.Tokens.accentRecord.g,W.Tokens.accentRecord.b,0.7); font.family: W.Tokens.sans; font.pixelSize: 9 }
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true; Layout.fillHeight: true; color: W.Tokens.bgBase
                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 16; spacing: 12
                                Rectangle {
                                    Layout.fillWidth: true; Layout.fillHeight: true
                                    color: W.Tokens.bgSurface; radius: W.Tokens.rMd; border.color: W.Tokens.borderBase; border.width: 1; clip: true
                                    Rectangle { anchors.fill: parent; gradient: Gradient { GradientStop { position: 0.0; color: "#050A18" } GradientStop { position: 1.0; color: "#040811" } } }
                                    Text { anchors.centerIn: parent; text: "▶"; color: Qt.rgba(1,1,1,0.08); font.pixelSize: 72 }
                                }
                                Rectangle {
                                    Layout.fillWidth: true; height: 72
                                    color: W.Tokens.bgSurface; radius: W.Tokens.rMd; border.color: W.Tokens.borderBase; border.width: 1
                                    ColumnLayout {
                                        anchors.fill: parent; anchors.margins: 14; spacing: 8
                                        Item {
                                            Layout.fillWidth: true; height: 14
                                            Rectangle {
                                                anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 4; radius: 2; color: W.Tokens.borderBase
                                                Rectangle { width: parent.width * 0.38; height: 4; radius: 2; color: W.Tokens.accentPrimary }
                                                Rectangle { x: parent.width * 0.38 - 5; anchors.verticalCenter: parent.verticalCenter; width: 10; height: 10; radius: 5; color: W.Tokens.accentPrimary; border.color: W.Tokens.bgBase; border.width: 2 }
                                            }
                                        }
                                        RowLayout {
                                            Text { text: "01:34:09"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 11 }
                                            Item { Layout.fillWidth: true }
                                            Repeater {
                                                model: ["⏮","⏪","⏸","⏩","⏭"]
                                                delegate: Rectangle {
                                                    width: 28; height: 28; radius: W.Tokens.rXs
                                                    color: th2.hovered ? Qt.rgba(1,1,1,0.08) : "transparent"
                                                    Behavior on color { ColorAnimation { duration: 100 } }
                                                    HoverHandler { id: th2 }
                                                    Text { anchors.centerIn: parent; text: modelData; color: index===2?W.Tokens.accentPrimary:W.Tokens.textMuted; font.pixelSize: 14 }
                                                }
                                            }
                                            Item { Layout.fillWidth: true }
                                            Text { text: "04:02"; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 11 }
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            Layout.preferredWidth: 220; Layout.fillHeight: true
                            color: W.Tokens.bgSurface; border.color: W.Tokens.borderBase; border.width: 1
                            ColumnLayout {
                                anchors.fill: parent; spacing: 0
                                Rectangle { Layout.fillWidth: true; height: 44; color: "transparent"
                                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }
                                    Text {
                                        anchors.left: parent.left; anchors.leftMargin: 16; anchors.verticalCenter: parent.verticalCenter
                                        text: "INFORMACIÓN"; color: W.Tokens.textMuted; font.family: W.Tokens.sans; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.2
                                    }
                                }
                                Repeater {
                                    model: ListModel {
                                        ListElement { label: "ARCHIVO";    value: "2026-05-24_09-00-00.mp4" }
                                        ListElement { label: "DURACIÓN";   value: "1h 00m 00s" }
                                        ListElement { label: "TAMAÑO";     value: "1.2 GB" }
                                        ListElement { label: "RESOLUCIÓN"; value: "3840×1080" }
                                        ListElement { label: "CODEC";      value: "H.264 · NVENC" }
                                        ListElement { label: "FPS";        value: "30" }
                                    }
                                    delegate: Item {
                                        Layout.fillWidth: true; height: 46
                                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase; opacity: 0.5 }
                                        Column {
                                            anchors.left: parent.left; anchors.leftMargin: 16; anchors.verticalCenter: parent.verticalCenter
                                            spacing: 3
                                            Text { text: label; color: W.Tokens.textDim; font.family: W.Tokens.sans; font.pixelSize: 9; font.letterSpacing: 0.8 }
                                            Text { text: value; color: W.Tokens.textPrimary; font.family: W.Tokens.mono; font.pixelSize: 11; width: 190; elide: Text.ElideRight }
                                        }
                                    }
                                }
                                Item { Layout.fillHeight: true }
                                Item {
                                    Layout.fillWidth: true; height: 64
                                    Rectangle {
                                        anchors.fill: parent; anchors.margins: 14
                                        radius: W.Tokens.rPill; color: "transparent"; border.color: W.Tokens.accentPrimary; border.width: 1
                                        HoverHandler { id: xh }
                                        Rectangle {
                                            anchors.fill: parent; radius: parent.radius; color: W.Tokens.accentPrimary
                                            opacity: xh.hovered ? 0.14 : 0
                                            Behavior on opacity { NumberAnimation { duration: 130 } }
                                        }
                                        Text { anchors.centerIn: parent; text: "EXPORTAR CLIP"; color: W.Tokens.accentPrimary; font.family: W.Tokens.sans; font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8 }
                                    }
                                }
                            }
                        }
                    }
                } // Tab 1

                // ── Tab 2 — IT Editor ─────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 2 ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                    W.ITEditorView { anchors.fill: parent }
                } // Tab 2

                // ── Tab 3 — Mini-modo ─────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 3 ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                    Rectangle {
                        anchors.centerIn: parent; width: 400; height: 300; radius: W.Tokens.rLg
                        color: W.Tokens.bgSurface; border.color: W.Tokens.borderBase; border.width: 1
                        Column {
                            anchors.centerIn: parent; spacing: 16
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "Mini-modo"; color: W.Tokens.textMuted; font.family: W.Tokens.sans; font.pixelSize: 13 }
                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: "Ctrl+4 activa la ventana flotante"
                                color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 11
                            }
                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: lbl.implicitWidth + 28; height: 36; radius: W.Tokens.rPill
                                color: W.Tokens.primaryDim; border.color: W.Tokens.accentPrimary; border.width: 1
                                HoverHandler { id: mmh }
                                TapHandler { onTapped: { miniWindow.visible = true; root.activeTab = 0 } }
                                Rectangle {
                                    anchors.fill: parent; radius: parent.radius; color: W.Tokens.accentPrimary
                                    opacity: mmh.hovered ? 0.14 : 0
                                    Behavior on opacity { NumberAnimation { duration: 130 } }
                                }
                                Text { id: lbl; anchors.centerIn: parent; text: "Abrir ventana mini"; color: W.Tokens.accentPrimary; font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.SemiBold }
                            }
                        }
                    }
                } // Tab 3

                // ── Tab 4 — Ajustes ───────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 4 ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                    W.SettingsView { anchors.fill: parent }
                } // Tab 4

            } // Tab content

            // ── Statusbar ─────────────────────────────────────────────────────
            W.Statusbar {
                Layout.fillWidth: true
                recordSec: root.recordSecBacking
                eventCount: root.eventCount
                storagePath: "C:/WatcherData"
            }

        } // ColumnLayout
    } // root Rectangle
} // Window
