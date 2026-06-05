import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "." as W
import "Components" as C

// SupervisorView.qml
//
// Full-screen view for the Supervisor role. Replaces the standard ClipBrowser
// in Tab Clips for this role.
//
// Left panel  (35 %) — Flat operator list (all storages merged, name + storage tag).
// Right panel (65 %) — Request form + outbox history.
//
// Security: operator folder names are shown but are NOT navigable.
// AppBridge.listAllOperators() never returns a path the QML can forward to
// listDirectory() or loadClip() — the data contract is name-only.
// The storage name is retained in each item so the full context travels in the request.

Item {
    id: root

    // ── State ─────────────────────────────────────────────────────────
    property var    operators:        []          // [{name, storage}]
    property string selectedOperator: ""

    property var    myRequests:       []          // [{id, operator, start_time, end_time, description, status, created_at}]

    // Form fields
    property string formOperator:    ""
    property string formStorage:     ""
    property string formStart:       ""
    property string formEnd:         ""
    property string formDescription: ""

    property bool   sending:         false
    property string sendFeedback:    ""           // "" | "ok" | "error" | "no_host"

    // ── Lifecycle ──────────────────────────────────────────────────────
    Component.onCompleted: {
        root.loadOperators()
        root.loadMyRequests()
    }

    Connections {
        target: AppBridge
        function onRequestStatusChanged(id, status) {
            root.loadMyRequests()
        }
    }

    // ── Functions ─────────────────────────────────────────────────────
    function loadOperators() {
        // Static station roster — Operator-01 through Operator-47.
        // Distributed evenly across 3 storages so the storage badge is
        // meaningful in the request payload without requiring a live NAS.
        // IT role owns the actual path mapping; this view is display-only.
        var ops = []
        for (var i = 1; i <= 47; i++) {
            var num     = i < 10 ? "0" + i : "" + i
            var storage = i <= 16 ? "Storage1" : (i <= 32 ? "Storage2" : "Storage3")
            ops.push({ name: "Operator-" + num, storage: storage })
        }
        root.operators = ops
    }

    function selectOperator(name, storage) {
        root.selectedOperator = name
        root.formOperator     = name
        root.formStorage      = storage
    }

    function loadMyRequests() {
        root.myRequests = AppBridge.getMyRequests()
    }

    function sendRequest() {
        if (!root.formOperator || !root.formStart || !root.formEnd) return
        root.sending = true
        root.sendFeedback = ""

        var payload = JSON.stringify({
            operator:    root.formOperator,
            storage:     root.formStorage,
            start_time:  root.formStart,
            end_time:    root.formEnd,
            description: root.formDescription
        })
        AppBridge.sendClipRequest(payload)

        // Brief success feedback then reset form
        root.sendFeedback = "ok"
        root.sending = false
        root.loadMyRequests()
        resetFormTimer.restart()
    }

    Timer {
        id: resetFormTimer
        interval: 2500
        onTriggered: {
            root.sendFeedback = ""
            root.formStart = ""
            root.formEnd = ""
            root.formDescription = ""
        }
    }

    // ── Status badge helper ───────────────────────────────────────────
    function statusColor(s) {
        if (s === "pending")    return "#FBBF24"
        if (s === "processing") return W.Tokens.accentPrimary
        if (s === "done")       return "#4ADE80"
        return W.Tokens.textMuted
    }
    function statusLabel(s) {
        if (s === "pending")    return "PENDIENTE"
        if (s === "processing") return "PROCESANDO"
        if (s === "done")       return "LISTO"
        return s.toUpperCase()
    }

    // ── Layout ────────────────────────────────────────────────────────
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── Left panel: Flat operator list ────────────────────────────
        Rectangle {
            Layout.preferredWidth: parent.width * 0.52
            Layout.fillHeight: true
            color: W.Tokens.bgSurface
            border.color: W.Tokens.borderBase
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // Header
                Rectangle {
                    Layout.fillWidth: true
                    height: 44
                    color: "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }

                    RowLayout {
                        anchors { fill: parent; leftMargin: 16; rightMargin: 12 }
                        spacing: 8

                        Text {
                            text: "OPERADORES"
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono
                            font.pixelSize: 9
                            font.letterSpacing: 1.4
                        }
                        Rectangle {
                            visible: root.operators.length > 0
                            width: cntLbl.implicitWidth + 8; height: 16; radius: 8
                            color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.15)
                            Text {
                                id: cntLbl
                                anchors.centerIn: parent
                                text: root.operators.length
                                color: W.Tokens.accentPrimary
                                font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            width: 26; height: 26; radius: W.Tokens.rXs
                            color: refreshHvr.hovered ? Qt.rgba(1,1,1,0.06) : "transparent"
                            HoverHandler { id: refreshHvr }
                            TapHandler { onTapped: root.loadOperators() }
                            Text { anchors.centerIn: parent; text: "↺"; color: W.Tokens.textMuted; font.pixelSize: 13 }
                        }
                    }
                }

                // Search filter
                Rectangle {
                    Layout.fillWidth: true
                    height: 40
                    color: "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }
                    TextField {
                        id: searchField
                        anchors { fill: parent; margins: 8 }
                        placeholderText: "Buscar operador…"
                        font.family: W.Tokens.sans; font.pixelSize: 12
                        color: W.Tokens.textPrimary
                        background: Rectangle {
                            color: W.Tokens.bgBase
                            border.color: parent.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
                            border.width: 1; radius: W.Tokens.rXs
                        }
                    }
                }

                // Operator grid — 4 columns, truly square cards
                GridView {
                    id: opGrid
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    // 4 columns: compute square cell size from actual panel width
                    readonly property int cols:    4
                    readonly property int gridPad: 10   // outer margin each side
                    readonly property int gap:     8    // gap between cells (gap × (cols-1))
                    cellWidth:  Math.floor((width - gridPad * 2 - gap * (cols - 1)) / cols)
                    cellHeight: cellWidth               // perfectly square

                    topMargin:    gridPad
                    bottomMargin: gridPad
                    leftMargin:   gridPad
                    rightMargin:  gridPad

                    model: root.operators.filter(function(op) {
                        return searchField.text === "" ||
                               op.name.toLowerCase().indexOf(searchField.text.toLowerCase()) >= 0
                    })

                    delegate: Item {
                        // Each cell is cellWidth × cellHeight; card gets a 4px inset for visual gap
                        width:  opGrid.cellWidth  + opGrid.gap * (index % opGrid.cols !== opGrid.cols - 1 ? 1 : 0) / 2
                        height: opGrid.cellHeight + opGrid.gap / 2

                        property bool   sel:  root.selectedOperator === modelData.name
                        property string opId: {
                            var m = modelData.name.match(/[-_ ](\w+)$/)
                            return m ? m[1] : modelData.name.substring(0, 2).toUpperCase()
                        }

                        // Card (inset 4px on every side → creates 8px gutter between neighbours)
                        Rectangle {
                            anchors { fill: parent; margins: 4 }
                            radius: W.Tokens.rMd

                            color: sel
                                   ? W.Tokens.primaryDim
                                   : (ch.hovered ? Qt.rgba(1,1,1,0.045) : W.Tokens.bgSurface)
                            border.color: sel
                                          ? W.Tokens.accentPrimary
                                          : (ch.hovered ? W.Tokens.borderSubtle : W.Tokens.borderBase)
                            border.width: sel ? 1.5 : 1

                            Behavior on color        { ColorAnimation { duration: W.Tokens.durFast } }
                            Behavior on border.color { ColorAnimation { duration: W.Tokens.durFast } }

                            HoverHandler { id: ch }
                            TapHandler   { onTapped: root.selectOperator(modelData.name, modelData.storage) }

                            // Content: vertically centred in the square
                            Column {
                                anchors.centerIn: parent
                                spacing: 7

                                // Icon box — centred
                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 38; height: 38
                                    radius: W.Tokens.rSm
                                    color: sel
                                           ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.22)
                                           : Qt.rgba(W.Tokens.accentMonitor.r,  W.Tokens.accentMonitor.g,  W.Tokens.accentMonitor.b,  0.10)
                                    Behavior on color { ColorAnimation { duration: W.Tokens.durFast } }

                                    Text {
                                        anchors.centerIn: parent
                                        // climb 3 levels: Column → Rectangle(card) → Item(delegate)
                                        text: parent.parent.parent.parent.opId
                                        color: sel ? W.Tokens.accentPrimary : W.Tokens.accentMonitor
                                        font.family: W.Tokens.mono
                                        font.pixelSize: 13
                                        font.weight: Font.Bold
                                        Behavior on color { ColorAnimation { duration: W.Tokens.durFast } }
                                    }
                                }

                                // Operator name
                                Text {
                                    width: opGrid.cellWidth - 20   // stay inside card
                                    horizontalAlignment: Text.AlignHCenter
                                    text: modelData.name
                                    color: sel ? W.Tokens.textPrimary : W.Tokens.textMuted
                                    font.family: W.Tokens.sans
                                    font.pixelSize: 10
                                    font.weight: sel ? Font.DemiBold : Font.Normal
                                    elide: Text.ElideRight
                                    Behavior on color { ColorAnimation { duration: W.Tokens.durFast } }
                                }

                                // Storage badge
                                Rectangle {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: storTxt.implicitWidth + 8; height: 14
                                    radius: 3
                                    color: Qt.rgba(1,1,1,0.05)
                                    border.color: W.Tokens.borderSubtle; border.width: 1
                                    Text {
                                        id: storTxt
                                        anchors.centerIn: parent
                                        text: modelData.storage
                                        color: W.Tokens.textDim
                                        font.family: W.Tokens.mono
                                        font.pixelSize: 8
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: 0.3
                                    }
                                }
                            }

                            // Selected tick — top-right corner
                            Rectangle {
                                visible: sel
                                anchors { top: parent.top; right: parent.right; margins: 6 }
                                width: 16; height: 16; radius: 8
                                color: W.Tokens.accentPrimary
                                Text {
                                    anchors.centerIn: parent
                                    text: "✓"
                                    color: W.Tokens.bgBase
                                    font.pixelSize: 9; font.weight: Font.Bold
                                }
                            }
                        }
                    }
                }

            }
        }

        // ── Right panel: Request form + history ────────────────────────
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Scrollable content
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: rightCol.implicitHeight + 40
                clip: true

                ColumnLayout {
                    id: rightCol
                    width: Math.min(parent.width - 64, 700)
                    x: 32
                    y: 28
                    spacing: 32

                    // ── Form ──────────────────────────────────────────
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 16

                        // Header
                        ColumnLayout {
                            spacing: 4
                            Text {
                                text: "Solicitar clip"
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.sans
                                font.pixelSize: 20
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: "Selecciona un operador en el panel izquierdo y define el rango de tiempo del incidente."
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.sans
                                font.pixelSize: 13
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                            Rectangle { Layout.fillWidth: true; height: 1; color: W.Tokens.borderBase; Layout.topMargin: 6 }
                        }

                        // Operador (filled from left panel click, also editable)
                        C.WSettingsRow {
                            label: "Operador"
                            helper: "Haz click en un operador del panel izquierdo."
                            TextField {
                                width: 240
                                height: 32
                                text: root.formOperator
                                placeholderText: "Operator-28"
                                onTextChanged: root.formOperator = text
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 12
                                background: Rectangle {
                                    color: W.Tokens.bgBase
                                    border.color: parent.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
                                    border.width: 1; radius: W.Tokens.rSm
                                }
                            }
                        }

                        // Time range
                        C.WSettingsRow {
                            label: "Inicio del incidente"
                            helper: "Fecha y hora local, formato: YYYY-MM-DD HH:MM"
                            TextField {
                                width: 200
                                height: 32
                                text: root.formStart
                                placeholderText: "2026-06-04 14:00"
                                onTextChanged: root.formStart = text
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 12
                                background: Rectangle {
                                    color: W.Tokens.bgBase
                                    border.color: parent.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
                                    border.width: 1; radius: W.Tokens.rSm
                                }
                            }
                        }

                        C.WSettingsRow {
                            label: "Fin del incidente"
                            helper: "Incluir margen post-incidente (ej. +30 min)"
                            TextField {
                                width: 200
                                height: 32
                                text: root.formEnd
                                placeholderText: "2026-06-04 14:30"
                                onTextChanged: root.formEnd = text
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 12
                                background: Rectangle {
                                    color: W.Tokens.bgBase
                                    border.color: parent.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
                                    border.width: 1; radius: W.Tokens.rSm
                                }
                            }
                        }

                        // Description
                        C.WSettingsRow {
                            label: "Descripción del incidente"
                            helper: "Contexto para IT: tipo de incidente, hora exacta, observaciones."
                            vertical: true
                            TextArea {
                                width: parent.width
                                height: 80
                                text: root.formDescription
                                placeholderText: "Incidente reportado a las 14:15 — revisar operador..."
                                onTextChanged: root.formDescription = text
                                wrapMode: TextArea.Wrap
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.sans
                                font.pixelSize: 12
                                background: Rectangle {
                                    color: W.Tokens.bgBase
                                    border.color: parent.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
                                    border.width: 1; radius: W.Tokens.rSm
                                }
                            }
                        }

                        // Submit
                        RowLayout {
                            spacing: 12

                            Rectangle {
                                width: 160; height: 38; radius: W.Tokens.rSm
                                property bool canSend: root.formOperator !== "" && root.formStart !== "" && root.formEnd !== "" && !root.sending
                                color: canSend
                                       ? (sendHvr.hovered
                                          ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.85)
                                          : W.Tokens.accentPrimary)
                                       : Qt.rgba(1,1,1,0.07)
                                Behavior on color { ColorAnimation { duration: 120 } }

                                HoverHandler { id: sendHvr }
                                TapHandler {
                                    enabled: parent.canSend
                                    onTapped: root.sendRequest()
                                }

                                Text {
                                    anchors.centerIn: parent
                                    text: root.sending ? "Enviando…" : "Enviar a IT"
                                    color: parent.canSend ? W.Tokens.bgBase : W.Tokens.textDim
                                    font.family: W.Tokens.sans
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }
                            }

                            Text {
                                visible: root.sendFeedback !== ""
                                text: root.sendFeedback === "ok"
                                      ? "✓ Solicitud enviada"
                                      : "✗ Error al enviar"
                                color: root.sendFeedback === "ok" ? "#4ADE80" : "#F87171"
                                font.family: W.Tokens.sans
                                font.pixelSize: 12
                            }
                        }
                    }

                    // ── Outbox history ────────────────────────────────
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: "MIS SOLICITUDES"
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.mono
                                font.pixelSize: 9
                                font.letterSpacing: 1.4
                            }
                            Item { Layout.fillWidth: true }
                            Rectangle {
                                visible: root.myRequests.length > 0
                                width: cntTxt.implicitWidth + 10; height: 18; radius: 9
                                color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.15)
                                Text {
                                    id: cntTxt
                                    anchors.centerIn: parent
                                    text: root.myRequests.length
                                    color: W.Tokens.accentPrimary
                                    font.family: W.Tokens.mono
                                    font.pixelSize: 9
                                    font.weight: Font.Bold
                                }
                            }
                        }

                        Rectangle { Layout.fillWidth: true; height: 1; color: W.Tokens.borderBase }

                        Repeater {
                            model: root.myRequests
                            delegate: Rectangle {
                                Layout.fillWidth: true
                                height: reqContent.implicitHeight + 24
                                radius: W.Tokens.rSm
                                color: W.Tokens.bgSurface
                                border.color: W.Tokens.borderBase
                                border.width: 1

                                ColumnLayout {
                                    id: reqContent
                                    anchors { fill: parent; margins: 14 }
                                    spacing: 6

                                    RowLayout {
                                        spacing: 8
                                        Rectangle {
                                            width: statusTxt.implicitWidth + 10; height: 18; radius: 4
                                            color: Qt.rgba(0,0,0,0.25)
                                            Text {
                                                id: statusTxt
                                                anchors.centerIn: parent
                                                text: root.statusLabel(modelData.status)
                                                color: root.statusColor(modelData.status)
                                                font.family: W.Tokens.mono
                                                font.pixelSize: 9
                                                font.weight: Font.Bold
                                                font.letterSpacing: 0.8
                                            }
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: modelData.operator + " — " + modelData.storage
                                            color: W.Tokens.textPrimary
                                            font.family: W.Tokens.sans
                                            font.pixelSize: 13
                                            font.weight: Font.DemiBold
                                            elide: Text.ElideRight
                                        }
                                        Text {
                                            text: (modelData.created_at || "").substring(0, 16).replace("T", " ")
                                            color: W.Tokens.textDim
                                            font.family: W.Tokens.mono
                                            font.pixelSize: 10
                                        }
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData.start_time + " → " + modelData.end_time
                                        color: W.Tokens.textMuted
                                        font.family: W.Tokens.mono
                                        font.pixelSize: 11
                                    }

                                    Text {
                                        Layout.fillWidth: true
                                        visible: (modelData.description || "") !== ""
                                        text: modelData.description
                                        color: W.Tokens.textDim
                                        font.family: W.Tokens.sans
                                        font.pixelSize: 11
                                        wrapMode: Text.WordWrap
                                        maximumLineCount: 2
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }

                        Text {
                            visible: root.myRequests.length === 0
                            text: "No hay solicitudes enviadas todavía."
                            color: W.Tokens.textDim
                            font.family: W.Tokens.sans
                            font.pixelSize: 12
                            topPadding: 8
                        }
                    }

                    Item { height: 24 }
                }
            }
        }
    }
}
