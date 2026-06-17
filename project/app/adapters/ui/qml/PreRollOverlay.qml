import QtQuick
import QtQuick.Layouts
import "." as W

// PreRollOverlay.qml — Modal countdown shown immediately after MARCAR EVENTO.
//
//   Properties:
//     active : bool   — controls visibility and starts the countdown
//     count  : int    — initial countdown value (seconds), defaults to 3
//
//   Signals:
//     finished()      — countdown reached 0
//     cancelled()     — user pressed Esc or clicked cancel
//
// Drop into the recording tab as an absolutely-positioned overlay:
//
//   PreRollOverlay {
//       id: preRoll
//       anchors.fill: parent
//       onFinished: annotationModal.open()
//       onCancelled: { /* ... */ }
//   }
//   // trigger with: preRoll.start()

Rectangle {
    id: root
    anchors.fill: parent
    color: Qt.rgba(W.Tokens.bgBase.r, W.Tokens.bgBase.g, W.Tokens.bgBase.b, 0.88)
    visible: active
    opacity: active ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: W.Tokens.durMed } }
    z: 40

    property bool active: false
    property int initialCount: 3
    property int count: initialCount

    signal finished()
    signal cancelled()

    function start() {
        count = initialCount
        active = true
    }
    function cancel() {
        active = false
        cancelled()
    }

    Keys.onEscapePressed: cancel()
    focus: active

    Timer {
        interval: 1000
        running: root.active
        repeat: true
        onTriggered: {
            root.count -= 1
            if (root.count <= 0) {
                root.active = false
                root.finished()
            }
        }
    }

    // ── Central card ─────────────────────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: 320
        height: 320
        radius: W.Tokens.rLg
        color: W.Tokens.bgSurface
        border.color: Qt.rgba(W.Tokens.accentPrimary.r,
                              W.Tokens.accentPrimary.g,
                              W.Tokens.accentPrimary.b, 0.30)
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 32
            spacing: 18

            // Tag header
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: tagTxt.implicitWidth + 22
                Layout.preferredHeight: 22
                radius: W.Tokens.rXs
                color: W.Tokens.primaryDim
                border.color: W.Tokens.accentPrimary
                border.width: 1

                Text {
                    id: tagTxt
                    anchors.centerIn: parent
                    text: "📍 CAPTURANDO EVENTO"
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.2
                }
            }

            // Circular countdown
            Item {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 140
                Layout.preferredHeight: 140

                // Track
                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: "transparent"
                    border.color: W.Tokens.borderBase
                    border.width: 2
                }

                // Progress ring — uses a Canvas for the arc
                Canvas {
                    id: ring
                    anchors.fill: parent
                    property real progress: root.active
                        ? (root.count / root.initialCount) : 1
                    Behavior on progress {
                        NumberAnimation { duration: 950; easing.type: Easing.Linear }
                    }
                    onProgressChanged: requestPaint()
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        ctx.lineWidth = 2
                        ctx.strokeStyle = W.Tokens.accentPrimary
                        ctx.lineCap = "round"
                        var cx = width / 2, cy = height / 2
                        var r = Math.min(cx, cy) - 1
                        ctx.beginPath()
                        ctx.arc(cx, cy, r, -Math.PI / 2,
                                -Math.PI / 2 + 2 * Math.PI * progress)
                        ctx.stroke()
                    }
                }

                Text {
                    anchors.centerIn: parent
                    text: root.count
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 66
                    font.weight: Font.Bold
                }
            }

            ColumnLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 4

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Marcando evento"
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.sans
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "2 MIN PRE · 2 MIN POST · CLIP DE 4 MIN"
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.mono
                    font.pixelSize: 11
                    font.letterSpacing: 1.0
                }
            }

            // Cancel button
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredHeight: 30
                Layout.preferredWidth: cancelTxt.implicitWidth + 28
                radius: W.Tokens.rSm
                color: cancelHvr.hovered ? Qt.rgba(1,1,1,0.04) : "transparent"
                border.color: W.Tokens.borderBase
                border.width: 1
                Behavior on color { ColorAnimation { duration: W.Tokens.durFast } }

                HoverHandler { id: cancelHvr }
                TapHandler   { onTapped: root.cancel() }

                Text {
                    id: cancelTxt
                    anchors.centerIn: parent
                    text: "CANCELAR · ESC"
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.mono
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.0
                }
            }
        }
    }
}
