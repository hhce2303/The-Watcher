import QtQuick
import QtQuick.Layouts
import "." as W

// OperatorCard.qml — single operator tile used in the supervisor grid.
//
//   Properties:
//     op       : object  (n, num, name, station, status, eventTag, lastEvent, buffer, pinned)
//     selected : bool    visual selection state
//
//   Signals:
//     clicked()          emitted when the user taps the card

Rectangle {
    id: root

    property var  op
    property bool selected: false

    signal clicked()

    // ── Layout ─────────────────────────────────────────────────────────────
    implicitWidth: 140
    implicitHeight: 84
    radius: W.Tokens.rSm

    // ── Status → color resolver ────────────────────────────────────────────
    function statusColor(s) {
        if (s === "rec")     return W.Tokens.accentRecord
        if (s === "online")  return W.Tokens.accentOk
        if (s === "idle")    return W.Tokens.accentYellow
        return W.Tokens.textDim          // offline
    }
    readonly property color sColor: statusColor(op ? op.status : "offline")
    readonly property bool  dim:    (op && op.status === "offline")

    // ── Visuals ────────────────────────────────────────────────────────────
    color: selected
           ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                     W.Tokens.accentPrimary.b, 0.16)
           : W.Tokens.bgSurface
    border.color: selected ? W.Tokens.accentPrimary : W.Tokens.borderBase
    border.width: 1
    opacity: dim ? 0.65 : 1.0

    Behavior on color  { ColorAnimation { duration: W.Tokens.durFast } }
    Behavior on border.color { ColorAnimation { duration: W.Tokens.durFast } }

    // Soft glow when selected
    Rectangle {
        anchors.fill: parent
        anchors.margins: -3
        radius: parent.radius + 3
        color: "transparent"
        border.width: 3
        border.color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                              W.Tokens.accentPrimary.b, 0.18)
        visible: root.selected
        z: -1
    }

    // ── Status stripe (left) ──────────────────────────────────────────────
    Rectangle {
        anchors {
            left: parent.left
            top: parent.top
            bottom: parent.bottom
            topMargin: 8
            bottomMargin: 8
        }
        width: 2
        radius: 1
        color: root.sColor
        opacity: root.dim ? 0.5 : 1.0
    }

    // ── Hover + tap ────────────────────────────────────────────────────────
    HoverHandler { id: hh }
    TapHandler   { onTapped: root.clicked() }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: W.Tokens.textPrimary
        opacity: hh.hovered && !root.selected ? 0.03 : 0
        Behavior on opacity { NumberAnimation { duration: 100 } }
    }

    // ── Content ────────────────────────────────────────────────────────────
    ColumnLayout {
        anchors {
            fill: parent
            leftMargin: 12
            rightMargin: 10
            topMargin: 10
            bottomMargin: 10
        }
        spacing: 4

        // Top row: number · pin · status dot
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: op ? op.num : "--"
                color: W.Tokens.textPrimary
                font.family: W.Tokens.mono
                font.pixelSize: 14
                font.weight: Font.Bold
                font.letterSpacing: -0.2
            }

            Item { Layout.fillWidth: true }

            Text {
                text: "★"
                visible: op && op.pinned
                color: W.Tokens.accentYellow
                font.pixelSize: 10
            }

            Rectangle {
                Layout.alignment: Qt.AlignVCenter
                width: 6; height: 6; radius: 3
                color: root.sColor

                // pulse for rec
                SequentialAnimation on opacity {
                    running: op && op.status === "rec"
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.4; duration: 700 }
                    NumberAnimation { to: 1.0; duration: 700 }
                }
            }
        }

        // Station
        Text {
            text: op ? op.station : ""
            color: W.Tokens.textMuted
            font.family: W.Tokens.mono
            font.pixelSize: 9
            font.letterSpacing: 0.4
        }

        Item { Layout.fillHeight: true }

        // Bottom: event tag or buffer
        Text {
            Layout.fillWidth: true
            elide: Text.ElideRight
            text: op
                  ? (op.eventTag
                     ? ("● " + op.eventTag + (op.lastEvent ? " · " + op.lastEvent : ""))
                     : (op.buffer || "sin actividad"))
                  : ""
            color: op && op.eventTag
                   ? (op.status === "rec" ? W.Tokens.accentRecord : W.Tokens.accentYellow)
                   : W.Tokens.textDim
            font.family: W.Tokens.mono
            font.pixelSize: 9
            font.letterSpacing: 0.3
        }
    }
}
