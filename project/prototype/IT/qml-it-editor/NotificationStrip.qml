import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// NotificationStrip.qml — current-task notification.
// One notification at a time, no visible queue. Two visual modes:
//
//   mode === "incoming"  : full hero card (just arrived)
//   mode === "editing"   : compact strip pinned to top while user works
//
//   Properties:
//     mode           : string  "incoming" | "editing"
//     notification   : var     { id, ts, arrived, supervisor:{name,role,initials},
//                                payload:{operator,start,end,description},
//                                filePath }
//     expanded       : bool    only relevant for "editing" mode
//
//   Signals:
//     accepted()             user pressed "Aceptar y abrir"
//     declined()             user pressed "Posponer"
//     toggleExpanded()
//     simulateIncoming()     demo button

Item {
    id: root

    property string mode: "editing"
    property var    notification
    property bool   expanded: false

    signal accepted()
    signal declined()
    signal toggleExpanded()
    signal simulateIncoming()

    implicitHeight: mode === "incoming" ? heroCard.implicitHeight
                                        : stripCard.implicitHeight

    // ── HERO (incoming) ────────────────────────────────────────────────────
    Rectangle {
        id: heroCard
        visible: root.mode === "incoming"
        anchors.fill: parent
        radius: W.Tokens.rSm + 2

        // gradient background
        gradient: Gradient {
            GradientStop { position: 0.0; color: W.Tokens.bgElevated }
            GradientStop { position: 1.0; color: W.Tokens.bgSurface }
        }

        border.color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                              W.Tokens.accentPrimary.b, 0.4)
        border.width: 1

        // left accent bar
        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 3
            color: W.Tokens.accentPrimary
            radius: 1
        }

        implicitHeight: heroCol.implicitHeight + 32

        ColumnLayout {
            id: heroCol
            anchors { fill: parent; topMargin: 16; bottomMargin: 16
                      leftMargin: 20; rightMargin: 20 }
            spacing: 14

            // ── Header row: NUEVA SOLICITUD · ID · time · WS chip ──────
            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Rectangle {
                    width: 8; height: 8; radius: 4
                    color: W.Tokens.accentPrimary
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.35; duration: 800 }
                        NumberAnimation { to: 1.0;  duration: 800 }
                    }
                }
                Text {
                    text: "NUEVA SOLICITUD"
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 1.8
                }
                Rectangle {
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: idTxt.implicitWidth + 12
                    color: W.Tokens.bgBase
                    border.color: W.Tokens.borderBase; border.width: 1
                    radius: 3
                    Text {
                        id: idTxt
                        anchors.centerIn: parent
                        text: notification ? notification.id : ""
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }
                Text {
                    text: notification
                          ? "· recibida " + notification.arrived + " · " + notification.ts
                          : ""
                    color: W.Tokens.textDim
                    font.family: W.Tokens.mono
                    font.pixelSize: 12
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: wsTxt.implicitWidth + 14
                    radius: 3
                    color: Qt.rgba(0.38, 0.65, 0.98, 0.10)
                    border.color: Qt.rgba(0.38, 0.65, 0.98, 0.45); border.width: 1
                    Text {
                        id: wsTxt
                        anchors.centerIn: parent
                        text: "WS · WEBSOCKET LIVE"
                        color: "#60A5FA"
                        font.family: W.Tokens.mono
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }
            }

            // ── Body grid: avatar · file · window ──────────────────────
            RowLayout {
                Layout.fillWidth: true
                spacing: 24

                // Supervisor
                RowLayout {
                    spacing: 10
                    W.OperatorAvatar {
                        size: 38
                        initials: notification ? notification.supervisor.initials : "··"
                    }
                    ColumnLayout {
                        spacing: 2
                        Text {
                            text: notification ? notification.supervisor.name : ""
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.sans
                            font.pixelSize: 15; font.weight: Font.DemiBold
                        }
                        Text {
                            text: notification ? notification.supervisor.role : ""
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono
                            font.pixelSize: 11; font.letterSpacing: 0.8
                        }
                    }
                }

                // File path
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text {
                        text: "▤  ARCHIVO EN NAS"
                        color: "#22D3EE"
                        font.family: W.Tokens.mono
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 30
                        radius: W.Tokens.rXs
                        color: Qt.rgba(0.13, 0.83, 0.93, 0.06)
                        border.color: Qt.rgba(0.13, 0.83, 0.93, 0.30); border.width: 1
                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                            spacing: 8
                            Text {
                                Layout.fillWidth: true
                                elide: Text.ElideMiddle
                                text: notification ? notification.filePath : ""
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 13
                            }
                            Text { text: "→"; color: "#22D3EE"
                                   font.pixelSize: 14; font.weight: Font.Bold }
                        }
                    }
                }

                // Window
                ColumnLayout {
                    spacing: 4
                    Text {
                        text: "VENTANA · " + (notification ? notification.payload.operator : "")
                        color: W.Tokens.accentYellow
                        font.family: W.Tokens.mono
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6
                    }
                    RowLayout {
                        spacing: 8
                        Text {
                            text: notification
                                  ? notification.payload.start.replace(" ", " · ")
                                  : ""
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 13
                        }
                        Text { text: "→"; color: W.Tokens.textMuted
                               font.pixelSize: 14; font.weight: Font.Bold }
                        Text {
                            text: notification
                                  ? notification.payload.end.replace(" ", " · ")
                                  : ""
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 13
                        }
                    }
                }
            }

            // ── Description block ──────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: descCol.implicitHeight + 24
                color: W.Tokens.bgBase
                border.color: W.Tokens.borderBase; border.width: 1
                radius: W.Tokens.rXs + 1

                ColumnLayout {
                    id: descCol
                    anchors { fill: parent; margins: 12 }
                    spacing: 6
                    Text {
                        text: "INSTRUCCIONES DEL SUPERVISOR"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: notification ? notification.payload.description : ""
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.sans
                        font.pixelSize: 15
                        lineHeight: 1.5
                    }
                }
            }

            // ── Actions ────────────────────────────────────────────────
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                // Accept (primary)
                Rectangle {
                    Layout.preferredHeight: 36
                    Layout.preferredWidth: acceptRow.implicitWidth + 24
                    radius: W.Tokens.rSm
                    color: ah.hovered ? Qt.lighter(W.Tokens.accentPrimary, 1.08)
                                      : W.Tokens.accentPrimary
                    Behavior on color { ColorAnimation { duration: 100 } }
                    HoverHandler { id: ah }
                    TapHandler   { onTapped: root.accepted() }
                    RowLayout {
                        id: acceptRow
                        anchors.centerIn: parent
                        spacing: 8
                        Text { text: "▶";  color: W.Tokens.bgBase
                               font.pixelSize: 13 }
                        Text { text: "Aceptar y abrir archivo"
                               color: W.Tokens.bgBase
                               font.family: W.Tokens.sans
                               font.pixelSize: 14; font.weight: Font.Bold }
                        Rectangle {
                            Layout.preferredHeight: 16; Layout.preferredWidth: 20
                            radius: 3
                            color: Qt.rgba(0,0,0,0.18)
                            Text { anchors.centerIn: parent; text: "↵"
                                   color: W.Tokens.bgBase; font.family: W.Tokens.mono
                                   font.pixelSize: 11; font.weight: Font.Bold }
                        }
                    }
                }

                // Clarify
                Rectangle {
                    Layout.preferredHeight: 36
                    Layout.preferredWidth: clarTxt.implicitWidth + 28
                    radius: W.Tokens.rSm
                    color: "transparent"
                    border.color: W.Tokens.borderBase; border.width: 1
                    HoverHandler { id: ch }
                    Rectangle {
                        anchors.fill: parent; radius: parent.radius
                        color: W.Tokens.textPrimary
                        opacity: ch.hovered ? 0.04 : 0
                    }
                    Text {
                        id: clarTxt; anchors.centerIn: parent
                        text: "Pedir aclaración"
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.sans
                        font.pixelSize: 14; font.weight: Font.Medium
                    }
                }

                Item { Layout.fillWidth: true }

                // Postpone
                Rectangle {
                    Layout.preferredHeight: 36
                    Layout.preferredWidth: postRow.implicitWidth + 24
                    radius: W.Tokens.rSm
                    color: "transparent"
                    border.color: W.Tokens.borderBase; border.width: 1
                    HoverHandler { id: ph }
                    TapHandler   { onTapped: root.declined() }
                    Rectangle {
                        anchors.fill: parent; radius: parent.radius
                        color: W.Tokens.textPrimary
                        opacity: ph.hovered ? 0.04 : 0
                    }
                    RowLayout {
                        id: postRow; anchors.centerIn: parent; spacing: 6
                        Text { text: "✕"; color: W.Tokens.textMuted; font.pixelSize: 13 }
                        Text { text: "Posponer 5 min"
                               color: W.Tokens.textMuted
                               font.family: W.Tokens.sans; font.pixelSize: 13 }
                    }
                }
            }
        }
    }

    // ── STRIP (editing) ────────────────────────────────────────────────────
    Rectangle {
        id: stripCard
        visible: root.mode === "editing"
        anchors.fill: parent
        color: W.Tokens.bgElevated
        border.color: W.Tokens.borderBase
        border.width: 1
        radius: W.Tokens.rSm

        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 3
            color: W.Tokens.accentPrimary
            radius: 1
        }

        implicitHeight: 56 + (root.expanded ? expDetail.implicitHeight + 12 : 0)

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // Top row (always visible)
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 56
                spacing: 14
                anchors.leftMargin: 16
                anchors.rightMargin: 16

                Item { Layout.preferredWidth: 0 }

                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    Layout.leftMargin: 4
                    width: 6; height: 6; radius: 3
                    color: W.Tokens.accentPrimary
                    border.color: Qt.rgba(W.Tokens.accentPrimary.r,
                                          W.Tokens.accentPrimary.g,
                                          W.Tokens.accentPrimary.b, 0.30)
                    border.width: 2
                }

                Text {
                    text: "TAREA ACTIVA"
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6
                }

                Rectangle {
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: idTxt2.implicitWidth + 12
                    color: W.Tokens.bgBase
                    border.color: W.Tokens.borderBase; border.width: 1
                    radius: 3
                    Text {
                        id: idTxt2; anchors.centerIn: parent
                        text: notification ? notification.id : ""
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono; font.pixelSize: 11
                        font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18
                            color: W.Tokens.borderBase }

                W.OperatorAvatar {
                    size: 26
                    initials: notification ? notification.supervisor.initials : "··"
                }
                Text {
                    text: notification ? notification.supervisor.name : ""
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.sans; font.pixelSize: 14
                    font.weight: Font.Medium
                }

                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18
                            color: W.Tokens.borderBase }

                Text {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 380
                    elide: Text.ElideMiddle
                    text: notification ? notification.filePath : ""
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.mono; font.pixelSize: 13
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    Layout.preferredHeight: 20
                    Layout.preferredWidth: opTxt.implicitWidth + 14
                    radius: 3
                    color: Qt.rgba(W.Tokens.accentYellow.r, W.Tokens.accentYellow.g,
                                   W.Tokens.accentYellow.b, 0.14)
                    border.color: Qt.rgba(W.Tokens.accentYellow.r, W.Tokens.accentYellow.g,
                                          W.Tokens.accentYellow.b, 0.40)
                    border.width: 1
                    Text {
                        id: opTxt; anchors.centerIn: parent
                        text: notification
                              ? notification.payload.operator + " · 16:23"
                              : ""
                        color: W.Tokens.accentYellow
                        font.family: W.Tokens.mono; font.pixelSize: 11
                        font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }

                Rectangle {
                    Layout.preferredHeight: 28
                    Layout.preferredWidth: insRow.implicitWidth + 16
                    radius: W.Tokens.rXs
                    color: "transparent"
                    border.color: W.Tokens.borderBase; border.width: 1
                    HoverHandler { id: ih }
                    TapHandler   { onTapped: root.toggleExpanded() }
                    Rectangle {
                        anchors.fill: parent; radius: parent.radius
                        color: W.Tokens.textPrimary; opacity: ih.hovered ? 0.04 : 0
                    }
                    RowLayout {
                        id: insRow; anchors.centerIn: parent; spacing: 6
                        Text {
                            text: root.expanded ? "OCULTAR" : "INSTRUCCIONES"
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono
                            font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 1.0
                        }
                        Text { text: root.expanded ? "▴" : "▾"
                               color: W.Tokens.textMuted; font.pixelSize: 11 }
                    }
                }

                Rectangle {
                    Layout.preferredHeight: 28; Layout.preferredWidth: 28
                    radius: W.Tokens.rXs
                    color: "transparent"
                    border.color: W.Tokens.borderBase; border.width: 1
                    HoverHandler { id: rh }
                    TapHandler   { onTapped: root.simulateIncoming() }
                    ToolTip.visible: rh.hovered
                    ToolTip.text: "Simular nueva notificación"
                    Rectangle {
                        anchors.fill: parent; radius: parent.radius
                        color: W.Tokens.textPrimary; opacity: rh.hovered ? 0.04 : 0
                    }
                    Text { anchors.centerIn: parent; text: "⟳"
                           color: W.Tokens.textMuted; font.pixelSize: 15 }
                }

                Item { Layout.preferredWidth: 0 }
            }

            // Expanded detail
            Rectangle {
                visible: root.expanded
                Layout.fillWidth: true
                Layout.preferredHeight: expDetail.implicitHeight + 24
                color: W.Tokens.bgSurface
                Rectangle { anchors.top: parent.top; width: parent.width
                            height: 1; color: W.Tokens.borderBase }

                ColumnLayout {
                    id: expDetail
                    anchors { fill: parent; topMargin: 12; bottomMargin: 12
                              leftMargin: 36; rightMargin: 16 }
                    spacing: 6
                    Text {
                        text: "INSTRUCCIONES DEL SUPERVISOR"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6
                    }
                    Text {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: notification ? notification.payload.description : ""
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.sans
                        font.pixelSize: 14
                        lineHeight: 1.55
                    }
                    RowLayout {
                        spacing: 14
                        Text {
                            text: notification
                                  ? "INICIO " + notification.payload.start
                                  : ""
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono; font.pixelSize: 12
                        }
                        Text { text: "→"; color: W.Tokens.textDim }
                        Text {
                            text: notification
                                  ? "FIN " + notification.payload.end
                                  : ""
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono; font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
}
