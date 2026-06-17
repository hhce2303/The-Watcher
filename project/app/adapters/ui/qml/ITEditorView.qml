import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// ITEditorView.qml — IT Editor dashboard for The Watcher.
//
// Owns the workflow state and wires together:
//   NotificationStrip · NASBrowser · VideoEditor · OutputPanel
//
// State machine:
//   phase === "incoming" → hero notification card visible, workspace blocked
//   phase === "editing"  → compact strip, full 3-column workspace
//
// notification is null when there are no pending/processing requests (idle).
// loadCurrentRequest() is called on startup and on every AppBridge signal.

Item {
    id: root

    property string phase: "editing"             // incoming | editing
    property bool   notifExpanded: false

    readonly property bool hasRequest: notification !== null && notification !== undefined

    property var notification: null   // live — null when no pending/processing request

    Component.onCompleted: root.loadCurrentRequest()

    Connections {
        target: AppBridge
        function onRequestReceived()            { root.loadCurrentRequest() }
        function onRequestStatusChanged(id, st) { root.loadCurrentRequest() }
    }

    function loadCurrentRequest() {
        var all = AppBridge.getInboxRequests()
        for (var i = 0; i < all.length; i++) {
            if (all[i].status === "pending" || all[i].status === "processing") {
                root.notification = all[i]
                root.phase = all[i].status === "pending" ? "incoming" : "editing"
                return
            }
        }
        root.notification = null
        root.phase = "editing"
    }

    function queueCount() {
        var all = AppBridge.getInboxRequests()
        return all.filter(function(r) {
            return r.status === "pending" || r.status === "processing"
        }).length
    }

    // Editor state
    property string selectedPath: ""
    property bool   playing: false
    property real   playhead: 0.0
    property real   inMark:  0.0
    property real   outMark: 1.0

    // OneDrive flow
    property string saveState: "idle"   // idle | uploading | done | linked

    // ── Playhead animation while playing ──────────────────────────────────
    NumberAnimation {
        id: playAnim
        target: root
        property: "playhead"
        from: root.inMark
        to: root.outMark
        duration: Math.max(1000, (root.outMark - root.inMark) * 983 * 1000 / 6)
        loops: Animation.Infinite
        running: false
    }
    onPlayingChanged: {
        if (playing) {
            playAnim.from = root.playhead
            playAnim.to   = root.outMark
            playAnim.duration = Math.max(800,
                (root.outMark - root.playhead) * 983 * 1000 / 6)
            playAnim.restart()
        } else {
            playAnim.stop()
        }
    }

    // ── Keyboard shortcuts ────────────────────────────────────────────────
    Shortcut { sequence: "Space"; onActivated: root.playing = !root.playing }
    Shortcut { sequence: "I";     onActivated: root.inMark  = root.playhead }
    Shortcut { sequence: "O";     onActivated: root.outMark = root.playhead }
    Shortcut {
        sequence: "Return"
        enabled: root.phase === "incoming"
        onActivated: root.phase = "editing"
    }
    Shortcut {
        sequence: "Escape"
        onActivated: { root.notifExpanded = false }
    }

    // ── Background + ambient glow ─────────────────────────────────────────
    Rectangle { anchors.fill: parent; color: W.Tokens.bgBase }

    // Soft glow top-right (primary)
    Canvas {
        anchors.fill: parent
        opacity: 0.45
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var cx = width * 0.60, cy = -120
            var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, 500)
            g.addColorStop(0.0, "rgba(56, 189, 248, 0.18)")
            g.addColorStop(1.0, "rgba(56, 189, 248, 0.00)")
            ctx.fillStyle = g
            ctx.fillRect(0, 0, width, height)
            // Secondary glow (monitor / indigo)
            var cx2 = width * 0.18, cy2 = -100
            var g2 = ctx.createRadialGradient(cx2, cy2, 0, cx2, cy2, 380)
            g2.addColorStop(0.0, "rgba(129, 140, 248, 0.14)")
            g2.addColorStop(1.0, "rgba(129, 140, 248, 0.00)")
            ctx.fillStyle = g2
            ctx.fillRect(0, 0, width, height)
        }
    }

    // ── Layout ────────────────────────────────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Titlebar ──────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            color: Qt.rgba(0.08, 0.12, 0.19, 0.94)
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: W.Tokens.borderBase }

            RowLayout {
                anchors { fill: parent; leftMargin: 20; rightMargin: 12 }
                spacing: 14

                Rectangle { width: 8; height: 8; radius: 4
                            color: W.Tokens.accentRecord
                            Layout.alignment: Qt.AlignVCenter }
                Text { text: "THE WATCHER"
                       color: W.Tokens.textPrimary
                       font.family: W.Tokens.sans
                       font.pixelSize: 14; font.weight: Font.Bold; font.letterSpacing: 2.0 }
                Text { text: "v0.8.2"
                       color: W.Tokens.textDim
                       font.family: W.Tokens.mono
                       font.pixelSize: 11; font.letterSpacing: 1.0 }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18
                            color: W.Tokens.borderBase }

                // Role chip
                Rectangle {
                    Layout.preferredHeight: 20
                    Layout.preferredWidth: roleTxt.implicitWidth + 16
                    radius: W.Tokens.rXs
                    color: W.Tokens.monitorDim
                    border.color: Qt.rgba(W.Tokens.accentMonitor.r,
                                          W.Tokens.accentMonitor.g,
                                          W.Tokens.accentMonitor.b, 0.40)
                    border.width: 1
                    Text { id: roleTxt; anchors.centerIn: parent
                           text: "ROL · IT EDITOR"
                           color: W.Tokens.accentMonitor
                           font.family: W.Tokens.mono
                           font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                }
                Rectangle {
                    Layout.preferredHeight: 20
                    Layout.preferredWidth: actTxt.implicitWidth + 16
                    radius: W.Tokens.rXs
                    color: W.Tokens.bgSurface
                    border.color: W.Tokens.borderBase; border.width: 1
                    Text { id: actTxt; anchors.centerIn: parent
                           text: "EDITAR Y ENTREGAR"
                           color: W.Tokens.textMuted
                           font.family: W.Tokens.mono
                           font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                }

                Item { Layout.fillWidth: true }

                // Health badges
                RowLayout {
                    spacing: 12
                    HealthMini { label: "WS";  value: "LIVE"; dotColor: W.Tokens.accentOk }
                    HealthMini { label: "NAS"; value: "10G";  dotColor: "#22D3EE" }
                    HealthMini { label: "OD";  value: "SYNC"; dotColor: "#60A5FA" }
                }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18
                            color: W.Tokens.borderBase }

                W.OperatorAvatar {
                    size: 28
                    initials: "IT"
                    tone: W.Tokens.accentMonitor
                }
            }
        }

        // ── Notification ──────────────────────────────────────────────
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: root.hasRequest ? notif.implicitHeight : 0
            Layout.leftMargin: 20; Layout.rightMargin: 20
            Layout.topMargin: root.hasRequest ? 14 : 0
            visible: root.hasRequest

            W.NotificationStrip {
                id: notif
                anchors.fill: parent
                mode: root.phase
                notification: root.notification
                expanded: root.notifExpanded
                onAccepted: {
                    if (root.notification)
                        AppBridge.updateRequestStatus(root.notification.id, "processing")
                    root.phase = "editing"
                }
                onDeclined: {
                    if (root.notification)
                        AppBridge.updateRequestStatus(root.notification.id, "declined")
                    root.notification = null
                    root.loadCurrentRequest()
                }
                onToggleExpanded: root.notifExpanded = !root.notifExpanded
                onSimulateIncoming: root.phase = "incoming"
            }
        }

        // ── Body (3-column workspace) ─────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 14
            Layout.leftMargin: 20; Layout.rightMargin: 20
            color: W.Tokens.bgBase
            border.color: W.Tokens.borderBase; border.width: 1
            radius: W.Tokens.rSm + 2
            clip: true

            // No-request idle state — calm "esperando" surface when there is
            // nothing assigned (notification === null in production).
            Item {
                visible: !root.hasRequest
                anchors.fill: parent
                Rectangle { anchors.fill: parent; color: W.Tokens.bgBase }
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 14
                    Layout.maximumWidth: 420
                    Rectangle {
                        width: 60; height: 60; radius: 30
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase; border.width: 1
                        Layout.alignment: Qt.AlignHCenter
                        Text { anchors.centerIn: parent; text: "✓"
                               color: W.Tokens.accentOk; font.pixelSize: 26 }
                    }
                    Text { text: "Sin solicitudes pendientes"
                           color: W.Tokens.textPrimary
                           font.family: W.Tokens.sans
                           font.pixelSize: 16; font.weight: Font.DemiBold
                           Layout.alignment: Qt.AlignHCenter }
                    Text {
                        Layout.maximumWidth: 380
                        Layout.alignment: Qt.AlignHCenter
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "EN ESPERA. LA PRÓXIMA SOLICITUD DEL SUPERVISOR APARECERÁ AQUÍ AUTOMÁTICAMENTE."
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 12; font.letterSpacing: 0.6
                        lineHeight: 1.6
                    }
                }
            }

            // Idle workspace overlay when incoming
            Item {
                visible: root.hasRequest && root.phase === "incoming"
                anchors.fill: parent
                Rectangle { anchors.fill: parent; color: W.Tokens.bgBase }
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 14
                    Layout.maximumWidth: 420
                    Rectangle {
                        width: 60; height: 60; radius: 30
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase; border.width: 1
                        Layout.alignment: Qt.AlignHCenter
                        Text { anchors.centerIn: parent; text: "🔔"
                               color: W.Tokens.accentPrimary; font.pixelSize: 26 }
                    }
                    Text { text: "Nueva solicitud arriba ↑"
                           color: W.Tokens.textPrimary
                           font.family: W.Tokens.sans
                           font.pixelSize: 16; font.weight: Font.DemiBold
                           Layout.alignment: Qt.AlignHCenter }
                    Text {
                        Layout.maximumWidth: 380
                        Layout.alignment: Qt.AlignHCenter
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        text: "REVISA LAS INSTRUCCIONES Y ACEPTA PARA ABRIR EL ARCHIVO EN EL EDITOR. MIENTRAS HAY UNA TAREA EN PROCESO, NO LLEGAN NUEVAS NOTIFICACIONES."
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 12; font.letterSpacing: 0.6
                        lineHeight: 1.6
                    }
                }
            }

            // Active workspace
            RowLayout {
                visible: root.hasRequest && root.phase === "editing"
                anchors.fill: parent
                spacing: 0

                W.NASBrowser {
                    id: nas
                    Layout.preferredWidth: 280
                    Layout.fillHeight: true
                    selectedPath: root.selectedPath
                    onFileSelected: function(path, node) { root.selectedPath = path }
                }

                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true
                            color: W.Tokens.borderBase }

                W.VideoEditor {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    fileName: {
                        var parts = root.selectedPath.split("/")
                        return parts[parts.length - 1]
                    }
                    playing:  root.playing
                    playhead: root.playhead
                    inMark:   root.inMark
                    outMark:  root.outMark
                    onToggled:   root.playing  = !root.playing
                    onScrubbed:  function(f) { root.playhead = f }
                    onMarkedIn:  function(f) { root.inMark  = f }
                    onMarkedOut: function(f) { root.outMark = f }
                }

                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true
                            color: W.Tokens.borderBase }

                W.OutputPanel {
                    Layout.preferredWidth: 340
                    Layout.fillHeight: true
                    saveState: root.saveState
                    onSaveRequested: {
                        if (root.notification)
                            AppBridge.updateRequestStatus(root.notification.id, "done")
                        root.saveState = "uploading"
                        root.notification = null
                        root.loadCurrentRequest()
                    }
                    onLinkRequested: root.saveState = "linked"
                    onLinkCopied: { /* feedback handled locally */ }
                }
            }
        }

        // ── Statusbar ─────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 24
            color: W.Tokens.bgElevated
            Rectangle { anchors.top: parent.top; width: parent.width
                        height: 1; color: W.Tokens.borderBase }
            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                spacing: 14
                RowLayout {
                    spacing: 6
                    Rectangle { width: 4; height: 4; radius: 2
                                color: W.Tokens.accentOk
                                Layout.alignment: Qt.AlignVCenter }
                    Text { text: "CONECTADO"
                           color: W.Tokens.accentOk
                           font.family: W.Tokens.mono
                           font.pixelSize: 12; font.letterSpacing: 0.4 }
                }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12
                            color: W.Tokens.borderBase }
                Text {
                    text: {
                        var n = root.queueCount()
                        return n > 1 ? n + " en cola" : (n === 1 ? "1 tarea activa" : "Sin tareas")
                    }
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.mono; font.pixelSize: 12
                }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12
                            color: W.Tokens.borderBase }
                Text { text: "12 entregas hoy"
                       color: W.Tokens.textMuted
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12
                            color: W.Tokens.borderBase }
                Text { text: "SLA P95 · 14m"
                       color: W.Tokens.textMuted
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Item { Layout.fillWidth: true }
                Text { text: "09 JUN 2026 · 14:28:09"
                       color: W.Tokens.textMuted
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12
                            color: W.Tokens.borderBase }
                Text { text: "build 2026.06.09"
                       color: W.Tokens.textDim
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
            }
        }
    }

    // ── Small helper component ────────────────────────────────────────────
    component HealthMini : RowLayout {
        property string label: ""
        property string value: ""
        property color  dotColor: W.Tokens.accentOk
        spacing: 5
        Rectangle { width: 5; height: 5; radius: 3
                    color: dotColor
                    Layout.alignment: Qt.AlignVCenter }
        Text { text: label; color: W.Tokens.textMuted
               font.family: W.Tokens.mono
               font.pixelSize: 12; font.letterSpacing: 0.8 }
        Text { text: value; color: W.Tokens.textPrimary
               font.family: W.Tokens.mono
               font.pixelSize: 12; font.weight: Font.Bold }
    }
}
