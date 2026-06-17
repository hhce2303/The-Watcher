import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import "qml" as W
import "qml/Components" as C

Window {
    id: root
    visibility: Window.FullScreen
    visible: true
    title: "The Watcher"
    flags: Qt.Window

    // ── Role helpers ─────────────────────────────────────────────────────────
    // Tabs visible per role:  operator → [0]   supervisor → [1]   it/""→ all
    function tabVisible(idx) {
        var r = SettingsBridge.role
        if (r === "operator")   return idx === 0
        if (r === "supervisor") return idx === 1
        return true
    }

    // ── Operator: block window close ─────────────────────────────────────────
    // Operator PCs must never stop recording by accident. Pressing Alt+F4 or
    // the OS close button minimises instead of terminating the process.
    onClosing: function(close) {
        if (SettingsBridge.role === "operator") {
            close.accepted = false
            root.hide()   // minimise to tray
        }
    }

    // Force fullscreen + foreground once the window is created. The declarative
    // `visibility: Window.FullScreen` is not reliably honoured on startup in
    // frozen (PyInstaller) builds — the window can come up minimised — so we
    // re-assert it here. Harmless when already fullscreen.
    // Also redirect activeTab to the first allowed tab for this role.
    Component.onCompleted: {
        root.showFullScreen()
        root.raise()
        root.requestActivate()
        var r = SettingsBridge.role
        if (r === "supervisor") root.activeTab = 1
        else root.activeTab = 0
    }

    // Restore the window when the tray icon asks for it (TrayIcon -> AppBridge).
    // Without this the tray "show" action is a no-op and a minimised window
    // cannot be recovered.
    Connections {
        target: AppBridge
        function onRequestShowWindow() {
            root.showFullScreen()
            root.raise()
            root.requestActivate()
        }
    }

    // ── App state (bound to AppBridge) ───────────────────────────────────────
    property int    activeTab:        0   // 0=Grabación 1=Clips 2=Mini-modo 3=Ajustes
    property bool   isRecording:      AppBridge.isRecording
    property int    recordSecBacking: AppBridge.recordSec
    property int    eventCount:       AppBridge.eventCount
    property int    selectedClip:     0

    property string recDuration: {
        var t = root.recordSecBacking
        return String(Math.floor(t/3600)).padStart(2,"0") + ":" +
               String(Math.floor((t%3600)/60)).padStart(2,"0") + ":" +
               String(t%60).padStart(2,"0")
    }

    // Screen state — driven by AppBridge.monitors
    property var screens: AppBridge.monitors
    readonly property int activeScreenCount: {
        var n = 0
        for (var i = 0; i < screens.length; i++) if (screens[i].active) n++
        return n
    }

    // ── Keyboard shortcuts ────────────────────────────────────────────────────
    Shortcut { sequence: "Ctrl+1"; onActivated: { if (root.tabVisible(0)) root.activeTab = 0 } }
    Shortcut { sequence: "Ctrl+2"; onActivated: { if (root.tabVisible(1)) root.activeTab = 1 } }
    Shortcut { sequence: "Ctrl+3"; onActivated: { if (root.tabVisible(2)) root.activeTab = 2 } }
    Shortcut { sequence: "Ctrl+4"; onActivated: { if (root.tabVisible(3)) root.activeTab = 3 } }
    // Disabled for the IT role: the full-screen IT editor owns Space (play/pause)
    // and registering both would make the shortcut ambiguous.
    Shortcut {
        sequence: "Space"
        enabled: root.activeTab === 0 && SettingsBridge.role !== "it"
        onActivated: preRoll.start()
    }

    // IT inbox: toggle the slide-in request inbox panel
    Shortcut {
        sequence: "Ctrl+I"
        enabled: SettingsBridge.role === "it"
        onActivated: {
            var panel = inboxPanelRef
            if (panel) panel.inboxVisible = !panel.inboxVisible
        }
    }

    // IT unlock: any PC, any role — allows an IT admin to temporarily unlock
    // role-change access on Operator/Supervisor machines.
    Shortcut {
        sequence: "Ctrl+Alt+Shift+R"
        onActivated: itPinDialog.open()
    }

    // ── IT PIN dialog ─────────────────────────────────────────────────────────
    Dialog {
        id: itPinDialog
        title: "Acceso IT"
        modal: true
        anchors.centerIn: parent
        width: 320
        padding: 24

        background: Rectangle {
            color: W.Tokens.bgSurface
            border.color: W.Tokens.borderBase
            border.width: 1
            radius: W.Tokens.rMd
        }

        header: Item {
            height: 56
            ColumnLayout {
                anchors { fill: parent; margins: 20; bottomMargin: 0 }
                spacing: 3
                Text {
                    text: "Acceso IT"
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.sans; font.pixelSize: 16; font.weight: Font.DemiBold
                }
                Text {
                    text: "Introduce el PIN para desbloquear el cambio de rol."
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.sans; font.pixelSize: 11
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 12

            TextField {
                id: pinField
                Layout.fillWidth: true
                placeholderText: "PIN"
                echoMode: TextInput.Password
                font.family: W.Tokens.mono
                font.pixelSize: 14
                color: W.Tokens.textPrimary
                background: Rectangle {
                    color: W.Tokens.bgBase
                    border.color: pinField.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
                    border.width: 1; radius: W.Tokens.rSm
                }
                onAccepted: itPinDialog.tryUnlock()
            }

            Text {
                id: pinError
                visible: false
                text: "PIN incorrecto"
                color: "#F87171"
                font.family: W.Tokens.sans; font.pixelSize: 11
            }
        }

        footer: RowLayout {
            spacing: 8
            Item { Layout.fillWidth: true }
            Rectangle {
                width: 80; height: 32; radius: W.Tokens.rSm
                color: W.Tokens.bgBase; border.color: W.Tokens.borderBase; border.width: 1
                HoverHandler { id: cancelHvr }
                TapHandler { onTapped: itPinDialog.close() }
                Text { anchors.centerIn: parent; text: "Cancelar"; color: W.Tokens.textMuted
                    font.family: W.Tokens.sans; font.pixelSize: 12 }
            }
            Rectangle {
                Layout.rightMargin: 8
                width: 80; height: 32; radius: W.Tokens.rSm
                color: W.Tokens.accentPrimary
                HoverHandler { id: okHvr }
                TapHandler { onTapped: itPinDialog.tryUnlock() }
                Text { anchors.centerIn: parent; text: "Entrar"; color: W.Tokens.bgBase
                    font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.DemiBold }
            }
        }

        function tryUnlock() {
            var ok = SettingsBridge.unlockIT(pinField.text)
            if (ok) {
                pinError.visible = false
                pinField.text = ""
                itPinDialog.close()
                // Navigate to settings so the IT can change the role
                root.activeTab = 3
            } else {
                pinError.visible = true
                pinField.selectAll()
            }
        }

        onClosed: { pinField.text = ""; pinError.visible = false }
    }

    // ── Mini-mode window ──────────────────────────────────────────────────────
    W.MiniMode {
        id: miniWindow
        visible: false
        recordSec: root.recordSecBacking
        eventCount: root.eventCount
        onMarkEvent: preRoll.start()
        onExpandRequested: { root.visible = true; miniWindow.visible = false }
    }

    // ── Auto-refresh clips when tab 1 becomes active ─────────────────────────
    onActiveTabChanged: { if (activeTab === 1) AppBridge.refreshClips() }

    // ── Root ─────────────────────────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: W.Tokens.bgBase

        // The standard shell (hero bar + tabs + statusbar) is hidden for the IT
        // role, which gets a dedicated full-screen editor below.
        ColumnLayout {
            anchors.fill: parent
            spacing: 0
            visible: SettingsBridge.role !== "it"

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
                    // IT pending-request count (shown as a badge on the Grabación tab)
                    property int itPendingCount: {
                        if (SettingsBridge.role !== "it") return 0
                        var reqs = AppBridge.getInboxRequests()
                        var n = 0
                        for (var i = 0; i < reqs.length; i++)
                            if (reqs[i].status === "pending") n++
                        return n
                    }
                    Connections {
                        target: AppBridge
                        function onRequestReceived() { parent.itPendingCount = Qt.binding(function() {
                            if (SettingsBridge.role !== "it") return 0
                            var reqs = AppBridge.getInboxRequests()
                            var n = 0
                            for (var i = 0; i < reqs.length; i++)
                                if (reqs[i].status === "pending") n++
                            return n
                        }) }
                    }

                    Row {
                        spacing: 2
                        Repeater {
                            model: [
                                { label: "Grabación",  key: "⌘1", idx: 0 },
                                { label: "Clips",      key: "⌘2", idx: 1 },
                                { label: "Mini-modo",  key: "⌘3", idx: 2 },
                                { label: "Ajustes",    key: "⌘4", idx: 3 },
                            ]
                            delegate: Rectangle {
                                property bool sel: root.activeTab === modelData.idx
                                visible: root.tabVisible(modelData.idx)
                                width: row.implicitWidth + 20 + (modelData.idx === 0 && parent.parent.itPendingCount > 0 ? 22 : 0); height: 32
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
                                        font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.DemiBold
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
                                    // IT inbox pending-request badge on Tab 0
                                    Rectangle {
                                        visible: modelData.idx === 0 && SettingsBridge.role === "it" && parent.parent.parent.parent.parent.itPendingCount > 0
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: bTxt.implicitWidth + 8; height: 16; radius: 8
                                        color: "#FBBF24"
                                        Text {
                                            id: bTxt
                                            anchors.centerIn: parent
                                            text: parent.parent.parent.parent.parent.parent.itPendingCount
                                            color: "#000"
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
                                            onTapped: AppBridge.toggleMonitor(modelData.fingerprint)
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
                                            // Tile width is divided equally among active monitors.
                                            // Tile height uses the full preview area height.
                                            // The inner Image uses PreserveAspectFit so the full
                                            // 1280×720 thumbnail is shown without cropping — identical
                                            // to what the recorded segment actually captures.
                                            width: parent.width / root.activeScreenCount
                                            height: parent.height
                                            color: "#020408"   // near-black for letterbox bars
                                            clip: true

                                            // VideoOutput + QVideoSink: frames are pushed directly
                                            // from Python without any intermediate URL change.
                                            // Qt swaps frames on the render thread — zero flicker,
                                            // no black frame between updates.
                                            VideoOutput {
                                                anchors.fill: parent
                                                fillMode: VideoOutput.PreserveAspectFit
                                                // Register this tile's internal QVideoSink with AppBridge
                                                // so Python can push QVideoFrame objects directly.
                                                Component.onCompleted: {
                                                    AppBridge.registerVideoSink(modelData.idx, videoSink)
                                                }
                                            }

                                            // Overlay: monitor badge + name
                                            Row {
                                                anchors { top: parent.top; left: parent.left; margins: 10 }
                                                spacing: 6
                                                z: 1
                                                Rectangle {
                                                    width: numTxt.implicitWidth + 10; height: 18; radius: W.Tokens.rXs
                                                    color: Qt.rgba(0, 0, 0, 0.55)
                                                    border.color: W.Tokens.accentPrimary; border.width: 1
                                                    Text {
                                                        id: numTxt; anchors.centerIn: parent
                                                        text: String(modelData.idx + 1).padStart(2, "0")
                                                        color: W.Tokens.accentPrimary
                                                        font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                                    }
                                                }
                                                Rectangle {
                                                    height: 18; width: nameTxt.implicitWidth + 12; radius: W.Tokens.rXs
                                                    color: Qt.rgba(0, 0, 0, 0.55)
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    Text {
                                                        id: nameTxt; anchors.centerIn: parent
                                                        text: modelData.name
                                                        color: W.Tokens.textPrimary
                                                        font.family: W.Tokens.sans; font.pixelSize: 10; font.weight: Font.DemiBold
                                                    }
                                                }
                                            }

                                            // Bottom-right: resolution
                                            Rectangle {
                                                anchors { bottom: parent.bottom; right: parent.right; margins: 8 }
                                                height: 16; width: resTxt.implicitWidth + 10; radius: 3
                                                color: Qt.rgba(0, 0, 0, 0.55)
                                                z: 1
                                                Text {
                                                    id: resTxt; anchors.centerIn: parent
                                                    text: modelData.res
                                                    color: W.Tokens.textDim
                                                    font.family: W.Tokens.mono; font.pixelSize: 9
                                                }
                                            }

                                            // Vertical divider between tiles
                                            Rectangle {
                                                anchors.right: parent.right; width: 1; height: parent.height
                                                color: W.Tokens.borderBase
                                                visible: index < root.activeScreenCount - 1
                                                z: 1
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
                        onFinished: {
                            AppBridge.triggerEvent()
                            annotation.open(root.recDuration)
                        }
                        onCancelled: console.log("cancelado")
                    }
                    W.AnnotationModal {
                        id: annotation
                        onSaved: (tag, severity, note) => { root.eventCount += 1 }
                        onSkipped: root.eventCount += 1
                    }

                    // ── IT request inbox (right-side slide-in) ──────────────
                    // Only visible for IT role. Ctrl+I toggles it.
                    Rectangle {
                        id: inboxPanelRef
                        visible: SettingsBridge.role === "it"
                        anchors {
                            right: parent.right
                            top:   parent.top
                            bottom: parent.bottom
                        }
                        width: inboxVisible ? 360 : 0
                        Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                        clip: true
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase
                        border.width: 1

                        property bool inboxVisible: false

                        W.ITInboxPanel {
                            anchors.fill: parent
                            visible: parent.width > 10
                        }
                    }
                } // Tab 0

                // ── Tab 1 — Clips / Supervisor ────────────────────────────────
                // Supervisor role: SupervisorView (storage browse + request form).
                // IT + other roles: full ClipBrowser + player.
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 1 ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

                    // Supervisor gets a dedicated view; IT/others get the standard ClipBrowser.
                    Loader {
                        anchors.fill: parent
                        sourceComponent: SettingsBridge.role === "supervisor"
                            ? supervisorViewComp
                            : clipBrowserComp
                    }

                    Component {
                        id: supervisorViewComp
                        W.SupervisorView { anchors.fill: parent }
                    }

                    Component {
                        id: clipBrowserComp
                        // Standard ClipBrowser + player layout
                        RowLayout {
                            anchors.fill: parent; spacing: 0

                            // ── File browser (fills left, flexible) ──────────────────
                            W.ClipBrowser {
                                id: clipBrowser
                                Layout.fillWidth:  true
                                Layout.fillHeight: true
                                onPlayRequested: function(path) { AppBridge.loadClip(path) }
                            }

                        // ── Player panel (slides in when a clip is loaded) ────────
                        Rectangle {
                            id: clipPlayerPanel
                            Layout.preferredWidth: AppBridge.currentClipPath !== "" ? Math.max(520, parent.width * 0.55) : 0
                            Layout.fillHeight: true
                            clip: true
                            color: W.Tokens.bgSurface
                            border.color: W.Tokens.borderBase; border.width: 1
                            Behavior on Layout.preferredWidth { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

                            function _fmt(ms) {
                                var s = Math.floor((ms||0)/1000), m = Math.floor(s/60), h = Math.floor(m/60)
                                return (h>0?String(h)+":":"") + String(m%60).padStart(2,"0") + ":" + String(s%60).padStart(2,"0")
                            }

                            MediaPlayer {
                                id: clipMedia
                                // AppBridge.mediaUrl() uses QUrl.fromLocalFile — handles UNC paths correctly:
                                // \\server\share\file.mkv → file://server/share/file.mkv  (not file:////…)
                                source: AppBridge.currentClipPath !== "" ? Qt.url(AppBridge.mediaUrl(AppBridge.currentClipPath)) : ""
                                videoOutput: clipVidOut
                                onErrorOccurred: function(error, errorString) {
                                    if (error !== MediaPlayer.NoError)
                                        formatErrorOverlay.visible = true
                                }
                                onMediaStatusChanged: function(status) {
                                    if (status === MediaPlayer.InvalidMedia)
                                        formatErrorOverlay.visible = true
                                }
                            }

                            ColumnLayout {
                                anchors.fill: parent; spacing: 0

                                // Header: filename + close
                                Rectangle {
                                    Layout.fillWidth: true; height: 44; color: "transparent"
                                    border.color: W.Tokens.borderBase; border.width: 1
                                    RowLayout {
                                        anchors { fill: parent; leftMargin: 14; rightMargin: 10 }
                                        Text {
                                            Layout.fillWidth: true; elide: Text.ElideLeft
                                            text: AppBridge.currentClipPath !== "" ? AppBridge.currentClipPath.split(/[\\/]/).pop() : "—"
                                            color: W.Tokens.textPrimary; font.family: W.Tokens.mono; font.pixelSize: 11
                                        }
                                        Rectangle {
                                            width: 24; height: 24; radius: W.Tokens.rXs
                                            color: cpClose.hovered ? Qt.rgba(1,1,1,0.08) : "transparent"
                                            HoverHandler { id: cpClose }
                                            Text { anchors.centerIn: parent; text: "✕"; color: W.Tokens.textMuted; font.pixelSize: 11 }
                                            TapHandler { onTapped: { clipMedia.stop(); AppBridge.loadClip("") } }
                                        }
                                    }
                                }

                                // Video area with zoom+pan
                                Rectangle {
                                    id: cpVidArea
                                    Layout.fillWidth: true; Layout.fillHeight: true
                                    color: "#050A18"; clip: true
                                    property real zoomLevel: 1.0; property real panX: 0; property real panY: 0
                                    function resetZoom() { zoomLevel=1.0; panX=0; panY=0 }
                                    function clampPan() {
                                        var mx=width*(zoomLevel-1)/2; var my=height*(zoomLevel-1)/2
                                        panX=Math.max(-mx,Math.min(mx,panX)); panY=Math.max(-my,Math.min(my,panY))
                                    }
                                    Connections {
                                        target: AppBridge
                                        function onCurrentClipPathChanged() {
                                            cpVidArea.resetZoom()
                                            formatErrorOverlay.visible = false
                                        }
                                    }
                                    VideoOutput {
                                        id: clipVidOut; width: parent.width; height: parent.height
                                        x: cpVidArea.panX; y: cpVidArea.panY
                                        scale: cpVidArea.zoomLevel; transformOrigin: Item.Center
                                    }
                                    MouseArea {
                                        anchors.fill: parent; acceptedButtons: Qt.LeftButton
                                        property real _ox: 0; property real _oy: 0
                                        cursorShape: cpVidArea.zoomLevel>1 ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor) : Qt.ArrowCursor
                                        onWheel: {
                                            var f=wheel.angleDelta.y>0?1.15:(1.0/1.15)
                                            var nz=Math.max(1.0,Math.min(8.0,cpVidArea.zoomLevel*f))
                                            if(nz<=1.0){cpVidArea.resetZoom()}else{
                                                var r=nz/cpVidArea.zoomLevel
                                                cpVidArea.panX=(mouseX-width/2)*(1-r)+cpVidArea.panX*r
                                                cpVidArea.panY=(mouseY-height/2)*(1-r)+cpVidArea.panY*r
                                                cpVidArea.zoomLevel=nz; cpVidArea.clampPan()
                                            }
                                        }
                                        onPressed:         { _ox=cpVidArea.panX-mouseX; _oy=cpVidArea.panY-mouseY }
                                        onPositionChanged: { if(!pressed||cpVidArea.zoomLevel<=1)return; cpVidArea.panX=_ox+mouseX; cpVidArea.panY=_oy+mouseY; cpVidArea.clampPan() }
                                        onDoubleClicked:   cpVidArea.resetZoom()
                                    }
                                    // ── Format-not-supported overlay ────────────────────
                                    Rectangle {
                                        id: formatErrorOverlay
                                        anchors.fill: parent; z: 10
                                        color: Qt.rgba(0,0,0,0.88); visible: false
                                        Column {
                                            anchors.centerIn: parent; spacing: 18
                                            Text {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                text: "⚠"; color: W.Tokens.accentYellow; font.pixelSize: 40
                                            }
                                            Text {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                text: "Formato no compatible\nen el reproductor integrado"
                                                color: W.Tokens.textPrimary
                                                font.family: W.Tokens.sans; font.pixelSize: 13
                                                horizontalAlignment: Text.AlignHCenter; lineHeight: 1.4
                                            }
                                            // Open with system default app
                                            Rectangle {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                width: extLbl.implicitWidth + 28; height: 34; radius: W.Tokens.rPill
                                                color: W.Tokens.accentPrimary
                                                HoverHandler { id: extHov }
                                                Rectangle { anchors.fill: parent; radius: parent.radius; color: Qt.rgba(1,1,1,0.18); opacity: extHov.hovered ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 100 } } }
                                                Text {
                                                    id: extLbl; anchors.centerIn: parent
                                                    text: "↗  Abrir con reproductor externo"
                                                    color: W.Tokens.bgBase
                                                    font.family: W.Tokens.sans; font.pixelSize: 11; font.weight: Font.Bold
                                                }
                                                TapHandler {
                                                    onTapped: {
                                                        var url = "file:///" + AppBridge.currentClipPath.replace(/\\/g, "/")
                                                        Qt.openUrlExternally(Qt.url(url))
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    Text { anchors.centerIn: parent; text:"▶"; color:Qt.rgba(1,1,1,0.06); font.pixelSize:42; visible:AppBridge.currentClipPath==="" }
                                }

                                // Transport controls
                                Rectangle {
                                    Layout.fillWidth: true; height: 62
                                    color: W.Tokens.bgSurface; border.color: W.Tokens.borderBase; border.width: 1
                                    ColumnLayout {
                                        anchors { fill: parent; leftMargin:12; rightMargin:12; topMargin:8; bottomMargin:8 }
                                        spacing: 6
                                        Item {
                                            Layout.fillWidth: true; height: 10
                                            Rectangle {
                                                anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 3; radius: 2; color: W.Tokens.borderBase
                                                Rectangle { width: clipMedia.duration>0?parent.width*(clipMedia.position/clipMedia.duration):0; height:3; radius:2; color:W.Tokens.accentPrimary }
                                                Rectangle { x: clipMedia.duration>0?parent.width*(clipMedia.position/clipMedia.duration)-5:-10; anchors.verticalCenter:parent.verticalCenter; width:10;height:10;radius:5;color:W.Tokens.accentPrimary;border.color:W.Tokens.bgBase;border.width:2 }
                                            }
                                            TapHandler { onTapped: function(e){ if(clipMedia.duration>0) clipMedia.position=Math.round((e.position.x/parent.width)*clipMedia.duration) } }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Text { text: clipPlayerPanel._fmt(clipMedia.position); color:W.Tokens.textDim; font.family:W.Tokens.mono; font.pixelSize:10 }
                                            Item { Layout.fillWidth: true }
                                            Repeater {
                                                model: [{ic:"⏮",a:0},{ic:"⏪",a:1},{ic:clipMedia.playbackState===MediaPlayer.PlayingState?"⏸":"▶",a:2},{ic:"⏩",a:3},{ic:"⏭",a:4}]
                                                delegate: Rectangle {
                                                    width:26;height:26;radius:W.Tokens.rXs;color:tHov2.hovered?Qt.rgba(1,1,1,0.08):"transparent"
                                                    HoverHandler{id:tHov2}
                                                    Text{anchors.centerIn:parent;text:modelData.ic;color:modelData.a===2?W.Tokens.accentPrimary:W.Tokens.textMuted;font.pixelSize:13}
                                                    TapHandler{onTapped:{
                                                        if(modelData.a===0)clipMedia.position=0
                                                        else if(modelData.a===1)clipMedia.position=Math.max(0,clipMedia.position-5000)
                                                        else if(modelData.a===2)clipMedia.playbackState===MediaPlayer.PlayingState?clipMedia.pause():clipMedia.play()
                                                        else if(modelData.a===3)clipMedia.position=Math.min(clipMedia.duration,clipMedia.position+5000)
                                                        else clipMedia.position=clipMedia.duration
                                                    }}
                                                }
                                            }
                                            Item { Layout.fillWidth: true }
                                            Text { text: clipPlayerPanel._fmt(clipMedia.duration); color:W.Tokens.textDim; font.family:W.Tokens.mono; font.pixelSize:10 }
                                        }
                                    }
                                }

                                // Clip metadata
                                Rectangle {
                                    Layout.fillWidth: true; height: 46; color: "transparent"
                                    border.color: W.Tokens.borderBase; border.width: 1
                                    Row {
                                        anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
                                        spacing: 0
                                        Column {
                                            spacing: 3
                                            Text { text: AppBridge.currentClipInfo.resolution||"—"; color:W.Tokens.textMuted; font.family:W.Tokens.mono; font.pixelSize:10 }
                                            Text { text:(AppBridge.currentClipInfo.codec||"—")+" · "+(AppBridge.currentClipInfo.fps||"—")+" fps"; color:W.Tokens.textDim; font.family:W.Tokens.mono; font.pixelSize:10 }
                                        }
                                    }
                                }
                            } // ColumnLayout player
                        } // clipPlayerPanel
                        } // RowLayout (inside clipBrowserComp)
                    } // Component clipBrowserComp
                } // Tab 1

                // ── Tab 2 — Mini-modo ─────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 2 ? 1 : 0
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
                                text: "Ctrl+3 activa la ventana flotante"
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
                                Text { id: lbl; anchors.centerIn: parent; text: "Abrir ventana mini"; color: W.Tokens.accentPrimary; font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.DemiBold }
                            }
                        }
                    }
                } // Tab 2

                // ── Tab 3 — Ajustes ───────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    opacity: root.activeTab === 3 ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                    W.SettingsView { anchors.fill: parent }
                } // Tab 3

            } // Tab content

            // ── Statusbar ─────────────────────────────────────────────────────
            W.Statusbar {
                Layout.fillWidth: true
                recordSec: root.recordSecBacking
                eventCount: root.eventCount
                storagePath: "C:/WatcherData"
            }

        } // ColumnLayout

        // ── IT role: full-screen editor ───────────────────────────────────────
        // ITEditorView is self-contained (own titlebar + statusbar), so it
        // replaces the standard shell instead of sitting inside a tab.
        // Mock data for now; bind to backend per qml-it-editor/README.md later.
        Loader {
            id: itEditorLoader
            anchors.fill: parent
            active: SettingsBridge.role === "it"
            visible: active
            sourceComponent: W.ITEditorView { anchors.fill: parent }
        }

        // ── First-run role wizard overlay ─────────────────────────────────────
        // Covers the entire window until the user selects a role.
        // Loaded lazily — once role is set it becomes permanently invisible.
        Loader {
            id: wizardLoader
            anchors.fill: parent
            // z above everything else so it's never accidentally interactive when hidden
            z: 100
            active: SettingsBridge.role === ""
            visible: active
            sourceComponent: W.RoleSetupWizard {}
        }

    } // root Rectangle
} // Window
