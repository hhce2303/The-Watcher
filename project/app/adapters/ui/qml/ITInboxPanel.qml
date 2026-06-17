import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "." as W

// ITInboxPanel.qml
//
// Bandeja de requests de clip recibidos por el IT desde Supervisores.
// Mostrado en el Tab Grabación para el rol IT (debajo del estado de grabación).
//
// Cada request muestra: operador, rango de tiempo, descripción, estado.
// IT puede marcar "Procesando" o "Listo" para notificar al Supervisor vía WS.

Item {
    id: root

    property var requests: []

    Component.onCompleted: root.loadRequests()

    Connections {
        target: AppBridge
        function onRequestReceived() { root.loadRequests() }
    }

    function loadRequests() {
        root.requests = AppBridge.getInboxRequests()
    }

    function statusColor(s) {
        if (s === "pending")    return "#FBBF24"
        if (s === "processing") return "#38BDF8"
        if (s === "done")       return "#4ADE80"
        return "#64748B"
    }

    function statusLabel(s) {
        if (s === "pending")    return "PENDIENTE"
        if (s === "processing") return "PROCESANDO"
        if (s === "done")       return "LISTO"
        return s.toUpperCase()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Header ────────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            height: 44
            color: W.Tokens.bgElevated
            border.color: W.Tokens.borderBase
            border.width: 1

            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                spacing: 10

                Text {
                    text: "BANDEJA IT"
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.mono
                    font.pixelSize: 11
                    font.letterSpacing: 1.4
                }

                // Pending count badge
                Rectangle {
                    property int pendingCount: {
                        var n = 0
                        for (var i = 0; i < root.requests.length; i++)
                            if (root.requests[i].status === "pending") n++
                        return n
                    }
                    visible: pendingCount > 0
                    width: badgeTxt.implicitWidth + 10; height: 18; radius: 9
                    color: Qt.rgba(1,0.75,0.15,0.2)
                    Text {
                        id: badgeTxt
                        anchors.centerIn: parent
                        text: parent.pendingCount
                        color: "#FBBF24"
                        font.family: W.Tokens.mono
                        font.pixelSize: 11
                        font.weight: Font.Bold
                    }
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    width: 80; height: 26; radius: W.Tokens.rSm
                    color: refreshHvr.hovered ? Qt.rgba(1,1,1,0.06) : "transparent"
                    border.color: W.Tokens.borderBase; border.width: 1
                    HoverHandler { id: refreshHvr }
                    TapHandler { onTapped: root.loadRequests() }
                    Text {
                        anchors.centerIn: parent
                        text: "↺ Refrescar"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.sans; font.pixelSize: 13
                    }
                }
            }
        }

        // ── Request list ──────────────────────────────────────────────
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: listCol.implicitHeight + 20
            clip: true

            ColumnLayout {
                id: listCol
                width: parent.width - 32
                x: 16
                y: 12
                spacing: 10

                Repeater {
                    model: root.requests
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        height: cardContent.implicitHeight + 24
                        radius: W.Tokens.rSm
                        color: W.Tokens.bgSurface
                        border.color: modelData.status === "pending"
                                      ? Qt.rgba(1,0.75,0.15,0.3)
                                      : W.Tokens.borderBase
                        border.width: 1

                        ColumnLayout {
                            id: cardContent
                            anchors { fill: parent; margins: 16 }
                            spacing: 8

                            // Top row: badge + operator + timestamp
                            RowLayout {
                                spacing: 8
                                Rectangle {
                                    width: stLbl.implicitWidth + 10; height: 18; radius: 4
                                    color: Qt.rgba(0,0,0,0.3)
                                    Text {
                                        id: stLbl
                                        anchors.centerIn: parent
                                        text: root.statusLabel(modelData.status)
                                        color: root.statusColor(modelData.status)
                                        font.family: W.Tokens.mono; font.pixelSize: 11
                                        font.weight: Font.Bold; font.letterSpacing: 0.8
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.operator + "  ·  " + modelData.storage
                                    color: W.Tokens.textPrimary
                                    font.family: W.Tokens.sans
                                    font.pixelSize: 15
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: (modelData.supervisor_host || "")
                                    color: W.Tokens.textDim
                                    font.family: W.Tokens.mono; font.pixelSize: 12
                                }
                            }

                            // Time range
                            Text {
                                text: modelData.start_time + "  →  " + modelData.end_time
                                color: W.Tokens.accentPrimary
                                font.family: W.Tokens.mono; font.pixelSize: 14
                            }

                            // Description
                            Text {
                                Layout.fillWidth: true
                                visible: (modelData.description || "") !== ""
                                text: modelData.description
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.sans; font.pixelSize: 14
                                wrapMode: Text.WordWrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }

                            // Action buttons
                            RowLayout {
                                visible: modelData.status !== "done"
                                spacing: 8

                                Rectangle {
                                    visible: modelData.status === "pending"
                                    width: procTxt.implicitWidth + 20; height: 30
                                    radius: W.Tokens.rSm
                                    color: procHvr.hovered
                                           ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.2)
                                           : Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.10)
                                    border.color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.4)
                                    border.width: 1
                                    HoverHandler { id: procHvr }
                                    TapHandler {
                                        onTapped: {
                                            AppBridge.updateRequestStatus(modelData.id, "processing")
                                            root.loadRequests()
                                        }
                                    }
                                    Text {
                                        id: procTxt
                                        anchors.centerIn: parent
                                        text: "Marcar procesando"
                                        color: W.Tokens.accentPrimary
                                        font.family: W.Tokens.sans; font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }
                                }

                                Rectangle {
                                    width: doneTxt.implicitWidth + 20; height: 30
                                    radius: W.Tokens.rSm
                                    color: doneHvr.hovered ? Qt.rgba(0.29,0.87,0.5,0.2) : Qt.rgba(0.29,0.87,0.5,0.10)
                                    border.color: Qt.rgba(0.29,0.87,0.5,0.4); border.width: 1
                                    HoverHandler { id: doneHvr }
                                    TapHandler {
                                        onTapped: {
                                            AppBridge.updateRequestStatus(modelData.id, "done")
                                            root.loadRequests()
                                        }
                                    }
                                    Text {
                                        id: doneTxt
                                        anchors.centerIn: parent
                                        text: "Marcar listo"
                                        color: "#4ADE80"
                                        font.family: W.Tokens.sans; font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                    }
                                }
                            }
                        }
                    }
                }

                // Empty state
                Item {
                    Layout.fillWidth: true
                    height: 120
                    visible: root.requests.length === 0
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 6
                        Text {
                            Layout.alignment: Qt.AlignHCenter
                            text: "📥"
                            font.pixelSize: 30
                        }
                        Text {
                            text: "Sin requests pendientes"
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.sans; font.pixelSize: 14
                        }
                    }
                }

                Item { height: 12 }
            }
        }
    }
}
