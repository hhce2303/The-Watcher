import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "." as W

// ITEditorView.qml — IT dashboard shell for The Watcher.
//
// Shell: header (52) · left nav rail (220) · content stack · status bar (24).
// Views (root.activeView): cola | editor | grabacion | entregas | ajustes.
//
//   cola      → request queue, grouped Pendientes / En proceso / Entregadas.
//               Global empty = "Listo" hero (or connection-error hero) + quick
//               actions + honest system-status card.
//   editor    → 3-column workspace (ClipBrowser · VideoEditor · OutputPanel).
//               ClipBrowser reads the real NAS (AppBridge.listDirectory);
//               "Cargar para editar" loads the pick via AppBridge.loadClip.
//   grabacion → MonitorSelector (shared with the operator view) + capture params.
//   entregas  → delivered (done) requests.
//   ajustes   → embedded SettingsView (encoder/storage/role), PIN-gated entry.
//
// Status is honest: WS reflects AppBridge.itServerActive; NAS/OneDrive/SLA show
// "—" until wired to real data; the clock is live.

Item {
    id: root

    // ── State ─────────────────────────────────────────────────────────────
    property string activeView: "cola"          // cola | editor | entregas | ajustes
    property string phase: "editing"            // incoming | editing
    property bool   notifExpanded: false
    property var    notification: null          // current pending/processing request
    property var    allRequests: []             // full inbox, refreshed from AppBridge
    property string pendingNavView: ""          // view to open after PIN unlock

    readonly property bool hasRequest: notification !== null && notification !== undefined
    readonly property bool wsActive: AppBridge.itServerActive

    // Free edit: IT edits a clip with no supervisor request behind it (a request
    // between IT roles, or external). The editor opens against a NAS selection.
    property bool freeEdit: false
    readonly property bool editorActive: hasRequest || freeEdit

    // Editor state. Playback (playing/playhead) and marks (inMark/outMark) are
    // owned by the VideoEditor's real MediaPlayer — read them via `videoEditor`.
    property string selectedPath: ""
    // OneDrive delivery state now lives in AppBridge (oneDriveState); this just
    // carries the last error message down to the OutputPanel.
    property string oneDriveError: ""

    // Live clock (replaces the old hardcoded timestamp).
    property string nowStr: ""

    Component.onCompleted: root.refresh()

    Connections {
        target: AppBridge
        function onRequestReceived()            { root.refresh() }
        function onRequestStatusChanged(id, st) { root.refresh() }
        function onOneDriveFailed(msg)          { root.oneDriveError = msg }
    }

    Timer {
        interval: 1000; running: true; repeat: true; triggeredOnStart: true
        onTriggered: root.nowStr = Qt.formatDateTime(new Date(), "dd MMM yyyy · HH:mm:ss")
    }

    // ── Data helpers ───────────────────────────────────────────────────────
    function refresh() {
        root.allRequests = AppBridge.getInboxRequests()
        var cur = null
        for (var i = 0; i < root.allRequests.length; i++) {
            var s = root.allRequests[i].status
            if (s === "pending" || s === "processing") { cur = root.allRequests[i]; break }
        }
        root.notification = cur
        if (cur)
            root.phase = cur.status === "pending" ? "incoming" : "editing"
    }

    function byStatus(s) {
        return root.allRequests.filter(function (r) { return r.status === s })
    }
    function queueCount() { return byStatus("pending").length + byStatus("processing").length }
    function deliveredCount() { return byStatus("done").length }

    function statusColor(s) {
        if (s === "pending")    return W.Tokens.accentYellow
        if (s === "processing") return W.Tokens.accentPrimary
        if (s === "done")       return W.Tokens.accentOk
        return W.Tokens.textMuted
    }
    function statusLabel(s) {
        if (s === "pending")    return "PENDIENTE"
        if (s === "processing") return "PROCESANDO"
        if (s === "done")       return "ENTREGADO"
        return ("" + s).toUpperCase()
    }

    function openRequest(req, makeProcessing) {
        if (makeProcessing && req.status === "pending")
            AppBridge.updateRequestStatus(req.id, "processing")
        root.freeEdit = false
        root.notification = req
        root.phase = "editing"
        root.activeView = "editor"
        root.refresh()
    }

    function startFreeEdit() {
        root.freeEdit = true
        root.selectedPath = ""
        root.oneDriveError = ""
        AppBridge.resetOneDrive()
        root.activeView = "editor"
    }

    // Load the NAS-selected clip into the player (ffprobe metadata populates
    // AppBridge.currentClipInfo, which the VideoEditor reflects).
    function loadSelected() {
        if (root.selectedPath === "") return
        // Triggers currentClipPath/currentClipInfo changes; the VideoEditor's
        // `source` binding reloads its MediaPlayer (resets playback by itself).
        AppBridge.loadClip(root.selectedPath)
    }

    function exitEditor() {
        root.freeEdit = false
        root.activeView = "cola"
    }

    function navTo(v) {
        if (v === "ajustes" && !SettingsBridge.isITUnlocked) {
            root.pendingNavView = v
            pinOverlay.visible = true
            pinField.text = ""
            pinError.visible = false
            pinField.forceActiveFocus()
            return
        }
        root.activeView = v
    }

    // ── Keyboard shortcuts ────────────────────────────────────────────────
    // Delegate to the VideoEditor's real transport (it owns the MediaPlayer).
    Shortcut { sequence: "Space"; enabled: root.activeView === "editor"; onActivated: videoEditor.togglePlay() }
    Shortcut { sequence: "I";     enabled: root.activeView === "editor"; onActivated: videoEditor.markIn() }
    Shortcut { sequence: "O";     enabled: root.activeView === "editor"; onActivated: videoEditor.markOut() }
    Shortcut { sequence: "Escape"; onActivated: { if (pinOverlay.visible) pinOverlay.visible = false; else root.notifExpanded = false } }

    // ── Cargar archivos: native multi-select picker → reel/timeline ───────
    // Loads videos from anywhere on disk (works without the NAS). Each picked
    // file is probed + appended to the reel; the first one opens in the editor.
    FileDialog {
        id: filesDialog
        title: "Cargar videos para editar"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["Videos (*.mp4 *.mkv *.mov *.avi *.ts *.m4v *.webm)",
                      "Todos los archivos (*)"]
        onAccepted: {
            var idx = EditorBridge.addFilesFromUrls(selectedFiles)
            if (idx >= 0) videoEditor.openReelClip(idx)
        }
    }

    // ── Background + ambient glow ─────────────────────────────────────────
    Rectangle { anchors.fill: parent; color: W.Tokens.bgBase }
    Canvas {
        anchors.fill: parent; opacity: 0.45
        onPaint: {
            var ctx = getContext("2d"); ctx.clearRect(0, 0, width, height)
            var cx = width * 0.60, cy = -120
            var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, 500)
            g.addColorStop(0.0, "rgba(56, 189, 248, 0.18)")
            g.addColorStop(1.0, "rgba(56, 189, 248, 0.00)")
            ctx.fillStyle = g; ctx.fillRect(0, 0, width, height)
            var cx2 = width * 0.18, cy2 = -100
            var g2 = ctx.createRadialGradient(cx2, cy2, 0, cx2, cy2, 380)
            g2.addColorStop(0.0, "rgba(129, 140, 248, 0.14)")
            g2.addColorStop(1.0, "rgba(129, 140, 248, 0.00)")
            ctx.fillStyle = g2; ctx.fillRect(0, 0, width, height)
        }
    }

    // ── Layout ────────────────────────────────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Header ────────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            color: Qt.rgba(0.08, 0.12, 0.19, 0.94)
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }

            RowLayout {
                anchors { fill: parent; leftMargin: 20; rightMargin: 12 }
                spacing: 14

                Rectangle { width: 8; height: 8; radius: 4; color: W.Tokens.accentRecord; Layout.alignment: Qt.AlignVCenter }
                Text { text: "THE WATCHER"; color: W.Tokens.textPrimary; font.family: W.Tokens.sans
                       font.pixelSize: 14; font.weight: Font.Bold; font.letterSpacing: 2.0 }
                Text { text: "v0.8.2"; color: W.Tokens.textDim; font.family: W.Tokens.mono
                       font.pixelSize: 11; font.letterSpacing: 1.0 }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18; color: W.Tokens.borderBase }

                Rectangle {
                    Layout.preferredHeight: 20
                    Layout.preferredWidth: roleTxt.implicitWidth + 16
                    radius: W.Tokens.rXs
                    color: W.Tokens.monitorDim
                    border.color: Qt.rgba(W.Tokens.accentMonitor.r, W.Tokens.accentMonitor.g, W.Tokens.accentMonitor.b, 0.40)
                    border.width: 1
                    Text { id: roleTxt; anchors.centerIn: parent; text: "ROL · IT"
                           color: W.Tokens.accentMonitor; font.family: W.Tokens.mono
                           font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                }

                Item { Layout.fillWidth: true }

                // Honest health: WS reflects real server state; NAS/OD "—" until wired.
                RowLayout {
                    spacing: 12
                    RowLayout {
                        spacing: 5
                        Rectangle { width: 5; height: 5; radius: 3
                                    color: root.wsActive ? W.Tokens.accentOk : W.Tokens.accentRecord
                                    Layout.alignment: Qt.AlignVCenter }
                        Text { text: "WS"; color: W.Tokens.textMuted; font.family: W.Tokens.mono
                               font.pixelSize: 12; font.letterSpacing: 0.8 }
                        Text { text: root.wsActive ? (":" + AppBridge.itServerPort) : "OFFLINE"
                               color: root.wsActive ? W.Tokens.textPrimary : W.Tokens.accentRecord
                               font.family: W.Tokens.mono; font.pixelSize: 12; font.weight: Font.Bold }
                    }
                    HealthMini { label: "NAS"; value: "—"; tone: W.Tokens.textDim }
                    HealthMini { label: "OD";  value: "—"; tone: W.Tokens.textDim }
                }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18; color: W.Tokens.borderBase }
                W.OperatorAvatar { size: 28; initials: "IT"; tone: W.Tokens.accentMonitor }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18; color: W.Tokens.borderBase }
                W.WindowControls { role: SettingsBridge.role; Layout.alignment: Qt.AlignVCenter }
            }
        }

        // ── Body: nav rail + content ──────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Left nav rail (the IA fix — every capability is now visible).
            Rectangle {
                Layout.preferredWidth: 220
                Layout.fillHeight: true
                color: W.Tokens.bgSurface
                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: W.Tokens.borderBase }

                ColumnLayout {
                    anchors { fill: parent; topMargin: 12; leftMargin: 10; rightMargin: 10 }
                    spacing: 2

                    Text { text: "TRABAJO"; color: W.Tokens.textDim; font.family: W.Tokens.mono
                           font.pixelSize: 10; font.letterSpacing: 1.2; Layout.leftMargin: 10
                           Layout.topMargin: 4; Layout.bottomMargin: 4 }
                    NavItem { icon: "▣"; label: "Cola";      targetView: "cola";     badge: root.queueCount() }
                    NavItem { icon: "▶"; label: "Editor";    targetView: "editor" }
                    NavItem { icon: "⦿"; label: "Grabación"; targetView: "grabacion" }
                    NavItem { icon: "☁"; label: "Entregas";  targetView: "entregas"; badge: root.deliveredCount() }

                    Text { text: "SISTEMA"; color: W.Tokens.textDim; font.family: W.Tokens.mono
                           font.pixelSize: 10; font.letterSpacing: 1.2; Layout.leftMargin: 10
                           Layout.topMargin: 12; Layout.bottomMargin: 4 }
                    NavItem { icon: "⚙"; label: "Ajustes";     targetView: "ajustes" }
                    NavItem { icon: "⇄"; label: "Cambiar rol"; targetView: "ajustes" }

                    Item { Layout.fillHeight: true }
                }
            }

            // Content area
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                // ── COLA ────────────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    visible: root.activeView === "cola"

                    // Incoming hero banner (pending request awaiting accept).
                    ColumnLayout {
                        anchors { fill: parent; margins: 20 }
                        spacing: 14

                        W.NotificationStrip {
                            id: notif
                            Layout.fillWidth: true
                            visible: root.hasRequest && root.phase === "incoming"
                            mode: root.phase
                            notification: root.notification
                            expanded: root.notifExpanded
                            onAccepted: { if (root.notification) root.openRequest(root.notification, true) }
                            onDeclined: {
                                if (root.notification) AppBridge.updateRequestStatus(root.notification.id, "declined")
                                root.notification = null; root.refresh()
                            }
                            onToggleExpanded: root.notifExpanded = !root.notifExpanded
                            onSimulateIncoming: root.phase = "incoming"
                        }

                        // Sectioned queue OR empty/error hero.
                        Flickable {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            contentWidth: width
                            contentHeight: queueCol.implicitHeight
                            clip: true
                            visible: root.allRequests.length > 0

                            ColumnLayout {
                                id: queueCol
                                width: parent.width
                                spacing: 18

                                QueueSection { title: "Pendientes";  pip: W.Tokens.accentYellow;  items: root.byStatus("pending");    mode: "pending" }
                                QueueSection { title: "En proceso";  pip: W.Tokens.accentPrimary; items: root.byStatus("processing"); mode: "processing" }
                                QueueSection { title: "Entregadas";  pip: W.Tokens.accentOk;      items: root.byStatus("done");       mode: "done" }
                                Item { Layout.preferredHeight: 12 }
                            }
                        }

                        // Global empty: error hero if WS is down, else ready hero.
                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            visible: root.allRequests.length === 0

                            // Connection error
                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 14
                                visible: !root.wsActive
                                Rectangle {
                                    width: 64; height: 64; radius: 32
                                    color: Qt.rgba(W.Tokens.accentRecord.r, W.Tokens.accentRecord.g, W.Tokens.accentRecord.b, 0.12)
                                    border.color: Qt.rgba(W.Tokens.accentRecord.r, W.Tokens.accentRecord.g, W.Tokens.accentRecord.b, 0.40)
                                    border.width: 1; Layout.alignment: Qt.AlignHCenter
                                    Text { anchors.centerIn: parent; text: "!"; color: W.Tokens.accentRecord; font.pixelSize: 28; font.weight: Font.Bold }
                                }
                                Text { text: "Sin conexión con el servidor de solicitudes"
                                       color: W.Tokens.textPrimary; font.family: W.Tokens.sans
                                       font.pixelSize: 17; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                                Text {
                                    Layout.maximumWidth: 460; Layout.alignment: Qt.AlignHCenter
                                    horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                                    text: "El servidor no está escuchando. Los supervisores no pueden enviar solicitudes hasta restablecerlo. Revisa el firewall o reinicia el servicio."
                                    color: W.Tokens.textMuted; font.family: W.Tokens.mono
                                    font.pixelSize: 12; font.letterSpacing: 0.4; lineHeight: 1.6
                                }
                                RowLayout {
                                    Layout.alignment: Qt.AlignHCenter; spacing: 10
                                    ActionButton { text: "Reintentar"; primary: true; onClicked: root.refresh() }
                                    ActionButton { text: "Abrir Ajustes"; onClicked: root.navTo("ajustes") }
                                }
                            }

                            // Ready / waiting
                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 14
                                visible: root.wsActive
                                Rectangle {
                                    width: 64; height: 64; radius: 32
                                    color: Qt.rgba(W.Tokens.accentOk.r, W.Tokens.accentOk.g, W.Tokens.accentOk.b, 0.12)
                                    border.color: Qt.rgba(W.Tokens.accentOk.r, W.Tokens.accentOk.g, W.Tokens.accentOk.b, 0.40)
                                    border.width: 1; Layout.alignment: Qt.AlignHCenter
                                    Text { anchors.centerIn: parent; text: "✓"; color: W.Tokens.accentOk; font.pixelSize: 28 }
                                }
                                Text { text: "Listo — esperando solicitudes"
                                       color: W.Tokens.textPrimary; font.family: W.Tokens.sans
                                       font.pixelSize: 17; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                                Text {
                                    Layout.maximumWidth: 440; Layout.alignment: Qt.AlignHCenter
                                    horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                                    text: "El servidor está escuchando en el puerto " + AppBridge.itServerPort + ". La próxima solicitud del supervisor aparecerá aquí automáticamente."
                                    color: W.Tokens.textMuted; font.family: W.Tokens.mono
                                    font.pixelSize: 12; font.letterSpacing: 0.4; lineHeight: 1.6
                                }
                                RowLayout {
                                    Layout.alignment: Qt.AlignHCenter; spacing: 10
                                    ActionButton { text: "Nueva edición libre"; primary: true; onClicked: root.startFreeEdit() }
                                    ActionButton { text: "Probar conexión"; onClicked: root.refresh() }
                                    ActionButton { text: "Abrir Ajustes"; onClicked: root.navTo("ajustes") }
                                    ActionButton { text: "Ver entregas"; ghost: true; onClicked: root.activeView = "entregas" }
                                }
                                // Honest system-status card
                                Rectangle {
                                    Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 6
                                    implicitWidth: sysRow.implicitWidth + 36; implicitHeight: sysRow.implicitHeight + 28
                                    radius: W.Tokens.rMd; color: W.Tokens.bgSurface
                                    border.color: W.Tokens.borderBase; border.width: 1
                                    RowLayout {
                                        id: sysRow; anchors.centerIn: parent; spacing: 26
                                        SysStat { k: "WS server"; v: "escuchando :" + AppBridge.itServerPort; tone: W.Tokens.accentOk }
                                        SysStat { k: "En cola";   v: "" + root.queueCount() }
                                        SysStat { k: "NAS";       v: "—"; tone: W.Tokens.textDim }
                                        SysStat {
                                            k: "OneDrive"
                                            v: AppBridge.oneDriveState === "linked"  ? "enlace listo"
                                             : AppBridge.oneDriveState === "working"  ? "procesando"
                                             : AppBridge.oneDriveState === "error"    ? "error"
                                                                                      : "—"
                                            tone: AppBridge.oneDriveState === "linked" ? W.Tokens.accentOk
                                                : AppBridge.oneDriveState === "error"  ? W.Tokens.accentRecord
                                                                                       : W.Tokens.textDim
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // ── EDITOR (request-driven OR free edit) ────────────────
                Item {
                    anchors.fill: parent
                    anchors.margins: 20
                    visible: root.activeView === "editor"

                    // No active edit → accept from Cola, or start a free edit.
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 12
                        visible: !root.editorActive
                        Text { text: "▶"; color: W.Tokens.textDim; font.pixelSize: 30; Layout.alignment: Qt.AlignHCenter }
                        Text { text: "Sin edición activa"; color: W.Tokens.textPrimary
                               font.family: W.Tokens.sans; font.pixelSize: 16; font.weight: Font.DemiBold
                               Layout.alignment: Qt.AlignHCenter }
                        Text { text: "Carga videos desde tu equipo, acepta una solicitud desde la Cola, o empieza una edición libre y elige el archivo en el NAS."
                               color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 12
                               horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                               Layout.maximumWidth: 420; Layout.alignment: Qt.AlignHCenter }
                        RowLayout {
                            Layout.alignment: Qt.AlignHCenter; spacing: 10
                            ActionButton { text: "Cargar archivos"; primary: true
                                           onClicked: { root.startFreeEdit(); filesDialog.open() } }
                            ActionButton { text: "Nueva edición libre"; onClicked: root.startFreeEdit() }
                            ActionButton { text: "Ir a la Cola"; onClicked: root.activeView = "cola" }
                        }
                    }

                    // Active edit: context bar + 3-column workspace.
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 10
                        visible: root.editorActive

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Rectangle {
                                implicitWidth: ctxTxt.implicitWidth + 16; height: 20; radius: 4
                                color: root.freeEdit ? W.Tokens.monitorDim : W.Tokens.primaryDim
                                border.width: 1
                                border.color: root.freeEdit
                                    ? Qt.rgba(W.Tokens.accentMonitor.r, W.Tokens.accentMonitor.g, W.Tokens.accentMonitor.b, 0.4)
                                    : Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.4)
                                Text { id: ctxTxt; anchors.centerIn: parent
                                       text: root.freeEdit ? "EDICIÓN LIBRE" : "SOLICITUD"
                                       color: root.freeEdit ? W.Tokens.accentMonitor : W.Tokens.accentPrimary
                                       font.family: W.Tokens.mono; font.pixelSize: 10
                                       font.weight: Font.Bold; font.letterSpacing: 1.0 }
                            }
                            Text {
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                                text: root.freeEdit
                                      ? (root.selectedPath !== "" ? root.selectedPath : "Selecciona un archivo en el NAS →")
                                      : (root.notification ? (root.notification.operator + " · " + (root.notification.supervisor_host || "")) : "")
                                color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 12
                            }
                            ActionButton {
                                text: "Cargar archivos"
                                onClicked: filesDialog.open()
                            }
                            ActionButton {
                                visible: root.selectedPath !== ""
                                text: "Cargar para editar"; primary: true
                                onClicked: root.loadSelected()
                            }
                            ActionButton { text: "Salir"; ghost: true; onClicked: root.exitEditor() }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            color: W.Tokens.bgBase
                            border.color: W.Tokens.borderBase; border.width: 1
                            radius: W.Tokens.rSm + 2
                            clip: true

                            RowLayout {
                                anchors.fill: parent
                                spacing: 0

                                W.ClipBrowser {
                                    id: clipBrowser
                                    Layout.preferredWidth: 430; Layout.fillHeight: true
                                    // Single-click selection → track the path (no play).
                                    onFileSelected: function(path) { root.selectedPath = path }
                                    // Double-click / REPRODUCIR → select AND load for editing.
                                    onPlayRequested: function(path) {
                                        root.selectedPath = path
                                        root.loadSelected()
                                    }
                                }
                                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: W.Tokens.borderBase }
                                W.VideoEditor {
                                    id: videoEditor
                                    Layout.fillWidth: true; Layout.fillHeight: true
                                    // Filename from the loaded clip; normalize BOTH separators
                                    // (real paths are UNC backslashes, not "/").
                                    fileName: {
                                        var p = AppBridge.currentClipPath
                                        if (!p || p === "") return root.selectedPath !== "" ? "Pulsa «Cargar para editar»" : "(sin archivo)"
                                        var parts = p.split(/[\\/]/)
                                        return parts[parts.length - 1]
                                    }
                                    clipInfo: AppBridge.currentClipInfo
                                    // Real media source — UNC/local path → file URL. The editor
                                    // owns playback (playing/playhead) and the in/out marks.
                                    source: AppBridge.currentClipPath !== ""
                                            ? AppBridge.mediaUrl(AppBridge.currentClipPath)
                                            : ""
                                }
                                Rectangle { Layout.preferredWidth: 1; Layout.fillHeight: true; color: W.Tokens.borderBase }
                                W.OutputPanel {
                                    Layout.preferredWidth: 340; Layout.fillHeight: true
                                    saveState:  AppBridge.oneDriveState
                                    destFolder: AppBridge.oneDriveFolder
                                    shareLink:  AppBridge.oneDriveLink
                                    errorText:  root.oneDriveError
                                    onSaveRequested: {
                                        root.oneDriveError = ""
                                        // Compute the folder while the request is still
                                        // pending/processing (it carries the operator),
                                        // THEN mark it delivered.
                                        AppBridge.ensureFolderLink("")
                                        if (root.notification) AppBridge.updateRequestStatus(root.notification.id, "done")
                                        root.notification = null
                                        root.refresh()
                                    }
                                    onLinkCopied: AppBridge.copyToClipboard(AppBridge.oneDriveLink)
                                }
                            }
                        }
                    }
                }

                // ── ENTREGAS ────────────────────────────────────────────
                Item {
                    anchors.fill: parent
                    anchors.margins: 20
                    visible: root.activeView === "entregas"

                    Flickable {
                        anchors.fill: parent
                        contentWidth: width; contentHeight: entCol.implicitHeight; clip: true
                        visible: root.byStatus("done").length > 0
                        ColumnLayout {
                            id: entCol; width: parent.width; spacing: 18
                            QueueSection { title: "Entregadas"; pip: W.Tokens.accentOk; items: root.byStatus("done"); mode: "done" }
                            Item { Layout.preferredHeight: 12 }
                        }
                    }
                    ColumnLayout {
                        anchors.centerIn: parent; spacing: 8
                        visible: root.byStatus("done").length === 0
                        Text { text: "☁"; color: W.Tokens.textDim; font.pixelSize: 30; Layout.alignment: Qt.AlignHCenter }
                        Text { text: "Aún no hay entregas"; color: W.Tokens.textMuted
                               font.family: W.Tokens.sans; font.pixelSize: 14; Layout.alignment: Qt.AlignHCenter }
                    }
                }

                // ── GRABACIÓN (monitor selection) ───────────────────────
                Item {
                    anchors.fill: parent
                    anchors.margins: 20
                    visible: root.activeView === "grabacion"

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: 14

                        // Header + capture params (read-only, from .env via SettingsBridge).
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            ColumnLayout {
                                spacing: 2
                                Text { text: "Grabación"; color: W.Tokens.textPrimary
                                       font.family: W.Tokens.sans; font.pixelSize: 18; font.weight: Font.DemiBold }
                                Text { text: "Selecciona las pantallas a incluir. Los parámetros de captura se configuran en .env."
                                       color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 12 }
                            }
                            Item { Layout.fillWidth: true }
                            Rectangle {
                                Layout.preferredHeight: 26
                                implicitWidth: capTxt.implicitWidth + 20; radius: W.Tokens.rXs
                                color: W.Tokens.bgSurface
                                border.color: W.Tokens.borderBase; border.width: 1
                                Text {
                                    id: capTxt; anchors.centerIn: parent
                                    text: SettingsBridge.outputWidth + "×" + SettingsBridge.outputHeight
                                          + " · " + SettingsBridge.captureFramerate + " FPS"
                                    color: W.Tokens.textMuted; font.family: W.Tokens.mono
                                    font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 0.6
                                }
                            }
                        }

                        // The shared monitor selector and preview area
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            spacing: 14

                            // Left side: Selector + Record Button
                            ColumnLayout {
                                Layout.preferredWidth: 320
                                Layout.fillHeight: true
                                spacing: 14

                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    color: W.Tokens.bgBase
                                    border.color: W.Tokens.borderBase; border.width: 1
                                    radius: W.Tokens.rSm + 2
                                    clip: true
                                    W.MonitorSelector {
                                        anchors.fill: parent
                                        anchors.margins: 1
                                    }
                                }

                                ActionButton {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 38
                                    primary: !AppBridge.isRecording
                                    text: AppBridge.isRecording ? "⏹ Detener Grabación" : "⏺ Arrancar Grabación"
                                    onClicked: {
                                        if (AppBridge.isRecording) {
                                            AppBridge.stopRecording()
                                        } else {
                                            AppBridge.startRecording()
                                        }
                                    }
                                }
                            }

                            // Right side: Preview area
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                color: "#020408"
                                border.color: W.Tokens.borderBase; border.width: 1
                                radius: W.Tokens.rSm + 2
                                clip: true

                                property var screens: AppBridge.monitors
                                property int activeScreenCount: {
                                    var n = 0
                                    for (var i = 0; i < screens.length; i++) {
                                        if (screens[i].active) n++
                                    }
                                    return Math.max(1, n)
                                }

                                Row {
                                    anchors.fill: parent
                                    Repeater {
                                        model: parent.screens.filter(s => s.active)
                                        delegate: Rectangle {
                                            width: parent.parent.width / parent.parent.activeScreenCount
                                            height: parent.height
                                            color: "transparent"
                                            clip: true

                                            VideoOutput {
                                                anchors.fill: parent
                                                fillMode: VideoOutput.PreserveAspectFit
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
                                                visible: index < parent.parent.activeScreenCount - 1
                                                z: 1
                                            }
                                        }
                                    }
                                }
                                
                                // Empty hint
                                Text {
                                    anchors.centerIn: parent
                                    visible: parent.activeScreenCount === 0 || parent.screens.filter(s => s.active).length === 0
                                    text: "Sin pantallas seleccionadas"
                                    color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 12
                                }
                            }
                        }
                    }
                }

                // ── AJUSTES (embedded, PIN-gated entry) ─────────────────
                Loader {
                    anchors.fill: parent
                    active: root.activeView === "ajustes" && SettingsBridge.isITUnlocked
                    visible: active
                    sourceComponent: W.SettingsView { }
                }
            }
        }

        // ── Status bar ────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 24
            color: W.Tokens.bgElevated
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: W.Tokens.borderBase }
            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                spacing: 14
                RowLayout {
                    spacing: 6
                    Rectangle { width: 4; height: 4; radius: 2
                                color: root.wsActive ? W.Tokens.accentOk : W.Tokens.accentRecord
                                Layout.alignment: Qt.AlignVCenter }
                    Text { text: root.wsActive ? "CONECTADO" : "SIN CONEXIÓN"
                           color: root.wsActive ? W.Tokens.accentOk : W.Tokens.accentRecord
                           font.family: W.Tokens.mono; font.pixelSize: 12; font.letterSpacing: 0.4 }
                }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12; color: W.Tokens.borderBase }
                Text {
                    text: { var n = root.queueCount(); return n > 1 ? n + " en cola" : (n === 1 ? "1 tarea activa" : "Sin tareas") }
                    color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 12
                }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12; color: W.Tokens.borderBase }
                Text { text: root.deliveredCount() + " entregadas"; color: W.Tokens.textMuted
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Item { Layout.fillWidth: true }
                Text { text: root.nowStr; color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 12 }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 12; color: W.Tokens.borderBase }
                Text { text: "build 2026.06.09"; color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 12 }
            }
        }
    }

    // ── PIN overlay (gates entry to Ajustes / Cambiar rol) ──────────────────
    Rectangle {
        id: pinOverlay
        anchors.fill: parent
        visible: false
        color: Qt.rgba(0, 0, 0, 0.6)
        z: 200
        MouseArea { anchors.fill: parent; onClicked: {} }   // swallow clicks

        Rectangle {
            anchors.centerIn: parent
            width: 360; implicitHeight: pinCol.implicitHeight + 40
            radius: W.Tokens.rMd
            color: W.Tokens.bgSurface
            border.color: W.Tokens.borderBase; border.width: 1

            ColumnLayout {
                id: pinCol
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
                spacing: 12
                Text { text: "Acceso IT"; color: W.Tokens.textPrimary; font.family: W.Tokens.sans
                       font.pixelSize: 16; font.weight: Font.DemiBold }
                Text { text: "Introduce el PIN para abrir Ajustes y cambio de rol."
                       color: W.Tokens.textMuted; font.family: W.Tokens.sans; font.pixelSize: 13
                       wrapMode: Text.WordWrap; Layout.fillWidth: true }
                TextField {
                    id: pinField
                    Layout.fillWidth: true
                    echoMode: TextInput.Password
                    placeholderText: "PIN"
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.mono; font.pixelSize: 15
                    background: Rectangle { radius: W.Tokens.rSm; color: W.Tokens.bgBase
                                            border.color: pinField.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
                                            border.width: 1 }
                    onAccepted: pinUnlock.tryUnlock()
                }
                Text { id: pinError; visible: false; text: "PIN incorrecto"
                       color: W.Tokens.accentRecord; font.family: W.Tokens.mono; font.pixelSize: 12 }
                RowLayout {
                    Layout.fillWidth: true; spacing: 10
                    Item { Layout.fillWidth: true }
                    ActionButton { text: "Cancelar"; ghost: true; onClicked: pinOverlay.visible = false }
                    ActionButton { id: pinUnlock; text: "Desbloquear"; primary: true
                        function tryUnlock() {
                            if (SettingsBridge.unlockIT(pinField.text)) {
                                pinOverlay.visible = false
                                root.activeView = root.pendingNavView || "ajustes"
                            } else { pinError.visible = true }
                        }
                        onClicked: tryUnlock()
                    }
                }
            }
        }
    }

    // ── Inline components ───────────────────────────────────────────────────

    component HealthMini : RowLayout {
        property string label: ""
        property string value: ""
        property color  tone: W.Tokens.textPrimary
        spacing: 5
        Text { text: parent.label; color: W.Tokens.textMuted; font.family: W.Tokens.mono
               font.pixelSize: 12; font.letterSpacing: 0.8 }
        Text { text: parent.value; color: parent.tone; font.family: W.Tokens.mono
               font.pixelSize: 12; font.weight: Font.Bold }
    }

    component SysStat : ColumnLayout {
        property string k: ""
        property string v: ""
        property color  tone: W.Tokens.textPrimary
        spacing: 3
        Text { text: parent.k; color: W.Tokens.textDim; font.family: W.Tokens.mono
               font.pixelSize: 10; font.letterSpacing: 0.6 }
        Text { text: parent.v; color: parent.tone; font.family: W.Tokens.mono; font.pixelSize: 12 }
    }

    component ActionButton : Rectangle {
        property string text: ""
        property bool primary: false
        property bool ghost: false
        signal clicked()
        implicitWidth: abTxt.implicitWidth + 24
        implicitHeight: 32
        radius: W.Tokens.rSm
        color: ghost ? "transparent"
               : (primary ? (abHover.hovered ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.85)
                                              : W.Tokens.accentPrimary)
                          : (abHover.hovered ? Qt.rgba(1,1,1,0.06) : W.Tokens.bgElevated))
        border.color: primary ? W.Tokens.accentPrimary : W.Tokens.borderBase
        border.width: 1
        HoverHandler { id: abHover }
        TapHandler { onTapped: parent.clicked() }
        Text { id: abTxt; anchors.centerIn: parent; text: parent.text
               color: primary ? W.Tokens.bgBase : (ghost ? W.Tokens.textMuted : W.Tokens.textPrimary)
               font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.DemiBold }
    }

    component NavItem : Rectangle {
        id: navRoot
        property string icon: ""
        property string label: ""
        property string targetView: ""
        property int    badge: -1
        readonly property bool current: root.activeView === targetView
        Layout.fillWidth: true
        Layout.preferredHeight: 38
        radius: W.Tokens.rSm
        color: current ? W.Tokens.primaryDim : (niHover.hovered ? Qt.rgba(1,1,1,0.04) : "transparent")
        activeFocusOnTab: true
        // Focus ring.
        border.width: activeFocus ? 1 : 0
        border.color: W.Tokens.accentPrimary

        // Left accent bar for the active item.
        Rectangle { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                    width: 2; height: navRoot.height - 12; radius: 1
                    color: navRoot.current ? W.Tokens.accentPrimary : "transparent" }

        RowLayout {
            anchors { fill: parent; leftMargin: 12; rightMargin: 10 }
            spacing: 10
            Text { text: navRoot.icon
                   color: navRoot.current ? W.Tokens.accentPrimary : W.Tokens.textMuted
                   font.pixelSize: 14; Layout.preferredWidth: 16; horizontalAlignment: Text.AlignHCenter }
            Text { text: navRoot.label
                   color: navRoot.current ? W.Tokens.textPrimary : W.Tokens.textMuted
                   font.family: W.Tokens.sans; font.pixelSize: 13; font.weight: Font.Medium
                   Layout.fillWidth: true }
            Rectangle {
                visible: navRoot.badge > 0
                implicitWidth: Math.max(18, niBadge.implicitWidth + 12); height: 18; radius: 9
                color: W.Tokens.bgElevated
                Text { id: niBadge; anchors.centerIn: parent; text: navRoot.badge
                       color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 11 }
            }
        }
        HoverHandler { id: niHover }
        TapHandler { onTapped: root.navTo(navRoot.targetView) }
        Keys.onReturnPressed: root.navTo(navRoot.targetView)
        Keys.onSpacePressed:  root.navTo(navRoot.targetView)
    }

    component QueueSection : ColumnLayout {
        id: secRoot
        property string title: ""
        property color  pip: W.Tokens.textMuted
        property var    items: []
        property string mode: ""          // pending | processing | done
        Layout.fillWidth: true
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Rectangle { width: 6; height: 6; radius: 3; color: secRoot.pip; Layout.alignment: Qt.AlignVCenter }
            Text { text: secRoot.title; color: W.Tokens.textMuted; font.family: W.Tokens.sans
                   font.pixelSize: 12; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Text { text: "" + secRoot.items.length; color: W.Tokens.textDim
                   font.family: W.Tokens.mono; font.pixelSize: 12 }
        }

        Repeater {
            model: secRoot.items
            delegate: Rectangle {
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: cc.implicitHeight + 24
                radius: W.Tokens.rSm
                color: W.Tokens.bgSurface
                border.color: modelData.status === "pending"
                              ? Qt.rgba(W.Tokens.accentYellow.r, W.Tokens.accentYellow.g, W.Tokens.accentYellow.b, 0.30)
                              : W.Tokens.borderBase
                border.width: 1

                ColumnLayout {
                    id: cc
                    anchors { fill: parent; margins: 14 }
                    spacing: 8
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        Rectangle {
                            implicitWidth: stLbl.implicitWidth + 12; height: 18; radius: 4
                            color: Qt.rgba(0, 0, 0, 0.30)
                            Text { id: stLbl; anchors.centerIn: parent; text: root.statusLabel(modelData.status)
                                   color: root.statusColor(modelData.status); font.family: W.Tokens.mono
                                   font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8 }
                        }
                        Text { Layout.fillWidth: true
                               text: (modelData.operator || "") + "  ·  " + (modelData.storage || "")
                               color: W.Tokens.textPrimary; font.family: W.Tokens.sans
                               font.pixelSize: 15; font.weight: Font.DemiBold; elide: Text.ElideRight }
                        Text { text: (modelData.supervisor_host || ""); color: W.Tokens.textDim
                               font.family: W.Tokens.mono; font.pixelSize: 12 }
                    }
                    Text { text: (modelData.start_time || "") + "  →  " + (modelData.end_time || "")
                           color: W.Tokens.accentPrimary; font.family: W.Tokens.mono; font.pixelSize: 14 }
                    Text { Layout.fillWidth: true; visible: (modelData.description || "") !== ""
                           text: modelData.description || ""; color: W.Tokens.textMuted
                           font.family: W.Tokens.sans; font.pixelSize: 14; wrapMode: Text.WordWrap
                           maximumLineCount: 3; elide: Text.ElideRight }
                    ActionButton {
                        visible: modelData.status === "pending" || modelData.status === "processing"
                        primary: modelData.status === "pending"
                        text: modelData.status === "pending" ? "Aceptar y editar" : "Continuar edición"
                        onClicked: root.openRequest(modelData, modelData.status === "pending")
                    }
                }
            }
        }

        // Per-section empty hint.
        Text {
            Layout.fillWidth: true
            visible: secRoot.items.length === 0
            horizontalAlignment: Text.AlignHCenter
            text: "—"
            color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 12
            topPadding: 6; bottomPadding: 6
        }
    }
}
