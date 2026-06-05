import QtQuick
import QtQuick.Layouts
import "." as W

// BufferTimeline.qml — Rolling 2-min buffer visualization
//
//   Required properties (bind from outside):
//     recordSec       : int     — current recording duration in seconds
//     eventMarkers    : var     — array of { sec: int, tag: string }
//
//   Internal constants are configurable via properties below.
//
// Place inside the recording column, between the audio row and the
// MARCAR EVENTO control bar.

Rectangle {
    id: root
    color: W.Tokens.bgSurface
    radius: W.Tokens.rMd
    border.color: W.Tokens.borderBase
    border.width: 1

    // ── API ──────────────────────────────────────────────────
    property int recordSec: 0
    property var eventMarkers: []           // [{ sec, tag }, ...]
    property int windowSec: 120              // 2-minute rolling window
    property int segCount: 60                // 2-second segments

    // ── Derived ──────────────────────────────────────────────
    readonly property int filledSec: Math.min(recordSec, windowSec)
    readonly property int segsFilled: Math.floor((filledSec / windowSec) * segCount)
    readonly property real bufferMB: filledSec * 0.85

    implicitHeight: 92

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 8

        // ── Header row ───────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Text {
                text: "ROLLING BUFFER"
                color: W.Tokens.textMuted
                font.family: W.Tokens.sans
                font.pixelSize: 9
                font.weight: Font.DemiBold
                font.letterSpacing: 1.4
            }

            // 2 min pill
            Rectangle {
                Layout.preferredWidth: pillTxt.implicitWidth + 12
                Layout.preferredHeight: 16
                radius: 3
                color: W.Tokens.primaryDim
                Text {
                    id: pillTxt
                    anchors.centerIn: parent
                    text: "2 MIN"
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 8
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.0
                }
            }

            Item { Layout.fillWidth: true }

            // Filled / total
            Text {
                text: Math.floor(filledSec / 60) + ":"
                    + String(filledSec % 60).padStart(2, "0")
                    + "  / 2:00"
                color: W.Tokens.textPrimary
                font.family: W.Tokens.mono
                font.pixelSize: 10
            }

            Rectangle {
                Layout.preferredWidth: 1
                Layout.preferredHeight: 10
                color: W.Tokens.borderBase
            }

            // Segments filled
            Text {
                text: Math.min(segsFilled, segCount) + "/" + segCount + " seg"
                color: W.Tokens.textMuted
                font.family: W.Tokens.mono
                font.pixelSize: 10
            }

            Rectangle {
                Layout.preferredWidth: 1
                Layout.preferredHeight: 10
                color: W.Tokens.borderBase
            }

            // Approx MB
            Text {
                text: "~" + bufferMB.toFixed(0) + " MB"
                color: W.Tokens.textMuted
                font.family: W.Tokens.mono
                font.pixelSize: 10
            }
        }

        // ── Timeline track ───────────────────────────────
        Item {
            id: track
            Layout.fillWidth: true
            Layout.preferredHeight: 28

            // Base + segments
            Rectangle {
                anchors.fill: parent
                color: W.Tokens.bgBase
                radius: 3
                border.color: W.Tokens.borderBase
                border.width: 1
                clip: true

                Row {
                    anchors.fill: parent
                    Repeater {
                        model: root.segCount
                        delegate: Rectangle {
                            width: (track.width - 2) / root.segCount
                            height: parent.height
                            color: index < root.segsFilled
                                   ? W.Tokens.accentPrimary
                                   : "transparent"
                            opacity: index < root.segsFilled
                                     ? (index / root.segCount) * 0.5 + 0.4
                                     : 0
                            Behavior on opacity { NumberAnimation { duration: 240 } }
                            // Divider
                            Rectangle {
                                anchors.right: parent.right
                                width: 1
                                height: parent.height
                                color: W.Tokens.borderBase
                                visible: index < root.segCount - 1
                                opacity: 0.6
                            }
                        }
                    }
                }
            }

            // NOW indicator (right edge)
            Rectangle {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.topMargin: -3
                anchors.bottomMargin: -3
                width: 2
                color: W.Tokens.accentRecord

                // Subtle glow via outer halo rect
                Rectangle {
                    anchors.centerIn: parent
                    width: 8
                    height: parent.height + 6
                    radius: 4
                    color: "transparent"
                    border.color: W.Tokens.accentRecord
                    border.width: 1
                    opacity: 0.35
                }
            }

            Text {
                anchors.right: parent.right
                anchors.bottom: parent.top
                anchors.bottomMargin: 2
                anchors.rightMargin: -4
                text: "NOW"
                color: W.Tokens.accentRecord
                font.family: W.Tokens.mono
                font.pixelSize: 8
                font.weight: Font.Bold
                font.letterSpacing: 0.6
            }

            // Event pins
            Repeater {
                model: root.eventMarkers
                delegate: Item {
                    property real relAge: root.recordSec - modelData.sec
                    visible: relAge >= 0 && relAge < root.windowSec
                    x: track.width * (1 - relAge / root.windowSec) - 3
                    y: -10
                    width: 6
                    height: track.height + 20

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        width: 6
                        height: 6
                        radius: 3
                        color: W.Tokens.accentYellow
                    }
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        anchors.topMargin: 6
                        width: 1
                        height: parent.height - 6
                        color: W.Tokens.accentYellow
                        opacity: 0.6
                    }
                }
            }
        }

        // ── Bottom scale ─────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 0
            Text {
                text: "−2:00"
                color: W.Tokens.textDim
                font.family: W.Tokens.mono
                font.pixelSize: 9
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "−1:30"
                color: W.Tokens.textDim
                font.family: W.Tokens.mono
                font.pixelSize: 9
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "−1:00"
                color: W.Tokens.textDim
                font.family: W.Tokens.mono
                font.pixelSize: 9
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "−0:30"
                color: W.Tokens.textDim
                font.family: W.Tokens.mono
                font.pixelSize: 9
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "NOW"
                color: W.Tokens.accentRecord
                font.family: W.Tokens.mono
                font.pixelSize: 9
                font.weight: Font.DemiBold
            }
        }
    }
}
