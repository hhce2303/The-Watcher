import QtQuick
import QtQuick.Layouts
import "." as W

// MiniMode.qml — Floating always-on-top widget.
//
// Use as a separate Window (not a child of Main.qml) so it can float
// above other apps. Open it from Main.qml:
//
//   MiniMode {
//       id: miniWindow
//       visible: false
//       recordSec: root.recordSecBacking
//       eventCount: 12
//       onMarkEvent: backend.markEvent()
//       onExpandRequested: { mainWindow.show(); visible = false }
//   }
//   // toggle with: miniWindow.visible = !miniWindow.visible

Window {
    id: root
    width: 320
    height: 220
    visible: false
    flags: Qt.Window
        | Qt.FramelessWindowHint
        | Qt.WindowStaysOnTopHint
        | Qt.Tool
    color: "transparent"
    title: "The Watcher · Mini"

    // ── API ──────────────────────────────────────────────────
    property int recordSec: 0
    property int eventCount: 0
    property int bufferWindowSec: 120
    property int barCount: 30

    signal markEvent()
    signal expandRequested()

    readonly property int filledSec: Math.min(recordSec, bufferWindowSec)
    readonly property int barsFilled: Math.floor((filledSec / bufferWindowSec) * barCount)

    function fmtTime(total) {
        var h = Math.floor(total / 3600)
        var m = Math.floor((total % 3600) / 60)
        var s = total % 60
        return String(h).padStart(2,"0") + ":"
             + String(m).padStart(2,"0") + ":"
             + String(s).padStart(2,"0")
    }

    Rectangle {
        anchors.fill: parent
        radius: W.Tokens.rMd
        color: Qt.rgba(W.Tokens.bgSurface.r,
                       W.Tokens.bgSurface.g,
                       W.Tokens.bgSurface.b, 0.94)
        border.color: W.Tokens.borderSubtle
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            // ── Drag handle ──────────────────────────
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 28
                color: W.Tokens.bgBase
                radius: W.Tokens.rMd

                // Square off the bottom corners (since the parent rounds them too)
                Rectangle {
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: W.Tokens.rMd
                    color: W.Tokens.bgBase
                }
                Rectangle {
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 1
                    color: W.Tokens.borderBase
                }

                DragHandler {
                    target: null
                    onActiveChanged: if (active) root.startSystemMove()
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 6

                    Rectangle {
                        Layout.preferredWidth: 5
                        Layout.preferredHeight: 5
                        radius: 3
                        color: W.Tokens.accentRecord
                    }

                    Text {
                        text: "THE WATCHER · MINI"
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.mono
                        font.pixelSize: 9
                        font.weight: Font.Bold
                        font.letterSpacing: 1.6
                        Layout.leftMargin: 6
                    }
                    Item { Layout.fillWidth: true }

                    // Expand
                    Rectangle {
                        Layout.preferredWidth: 18
                        Layout.preferredHeight: 18
                        radius: 3
                        color: expHvr.hovered ? Qt.rgba(1,1,1,0.06) : "transparent"
                        Behavior on color { ColorAnimation { duration: 80 } }

                        HoverHandler { id: expHvr }
                        TapHandler   { onTapped: root.expandRequested() }

                        Text {
                            anchors.centerIn: parent
                            text: "⤢"
                            color: W.Tokens.textMuted
                            font.pixelSize: 12
                        }
                    }

                    // Close mini-mode (hides window)
                    Rectangle {
                        Layout.preferredWidth: 18
                        Layout.preferredHeight: 18
                        radius: 3
                        color: closeHvr.hovered ? "#C42B1C" : "transparent"
                        Behavior on color { ColorAnimation { duration: 80 } }

                        HoverHandler { id: closeHvr }
                        TapHandler   { onTapped: root.visible = false }

                        Text {
                            anchors.centerIn: parent
                            text: "✕"
                            color: closeHvr.hovered ? "#FFFFFF" : W.Tokens.textMuted
                            font.pixelSize: 10
                        }
                    }
                }
            }

            // ── Body ─────────────────────────────────
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.margins: 14
                spacing: 12

                // Live + timer
                RowLayout {
                    Layout.fillWidth: true

                    Rectangle {
                        Layout.preferredWidth: liveTxt.implicitWidth + 18
                        Layout.preferredHeight: 18
                        radius: W.Tokens.rXs
                        color: W.Tokens.recordDim
                        border.color: W.Tokens.accentRecord
                        border.width: 1

                        Text {
                            id: liveTxt
                            anchors.centerIn: parent
                            text: "● LIVE · REC"
                            color: W.Tokens.accentRecord
                            font.family: W.Tokens.mono
                            font.pixelSize: 9
                            font.weight: Font.DemiBold
                            font.letterSpacing: 0.6
                        }
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        text: root.fmtTime(root.recordSec)
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.mono
                        font.pixelSize: 16
                        font.weight: Font.Bold
                        font.letterSpacing: 0.6
                    }
                }

                // Buffer mini-viz
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        Text {
                            text: "BUFFER"
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono
                            font.pixelSize: 8
                            font.letterSpacing: 1.2
                        }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: "2:00"
                            color: W.Tokens.textDim
                            font.family: W.Tokens.mono
                            font.pixelSize: 8
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 14

                        Row {
                            anchors.fill: parent
                            spacing: 1
                            Repeater {
                                model: root.barCount
                                delegate: Rectangle {
                                    width: (parent.width - (root.barCount - 1)) / root.barCount
                                    height: parent.height
                                    radius: 1
                                    color: index < root.barsFilled
                                           ? W.Tokens.accentPrimary
                                           : W.Tokens.borderBase
                                    opacity: index < root.barsFilled
                                             ? (index / root.barCount) * 0.5 + 0.5
                                             : 1
                                    Behavior on opacity { NumberAnimation { duration: 240 } }
                                }
                            }
                        }

                        // Now indicator
                        Rectangle {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.topMargin: -2
                            anchors.bottomMargin: -2
                            width: 2
                            color: W.Tokens.accentRecord
                        }
                    }
                }

                // MARCAR EVENTO button
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 38
                    radius: W.Tokens.rSm
                    color: markHvr.hovered
                           ? Qt.darker(W.Tokens.accentPrimary, 1.05)
                           : W.Tokens.accentPrimary
                    Behavior on color { ColorAnimation { duration: 120 } }

                    HoverHandler { id: markHvr }
                    TapHandler   { onTapped: root.markEvent() }

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: 8

                        Text {
                            text: "📍 MARCAR EVENTO"
                            color: W.Tokens.bgBase
                            font.family: W.Tokens.sans
                            font.pixelSize: 11
                            font.weight: Font.Bold
                            font.letterSpacing: 1.0
                        }
                    }
                }

                // Footer
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: W.Tokens.borderBase
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "EVENTOS HOY"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 9
                        font.letterSpacing: 1.2
                    }
                    Item { Layout.fillWidth: true }
                    Text {
                        text: root.eventCount
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.mono
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
    }
}
