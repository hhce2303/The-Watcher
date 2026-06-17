import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// VideoEditor.qml — video editor workspace: preview + transport + timeline.
//
//   Properties:
//     fileName    : string  shown in toolbar
//     duration    : int     seconds
//     playing     : bool    transport state
//     playhead    : real    0..1
//     inMark      : real    0..1
//     outMark     : real    0..1
//
//   Signals:
//     toggled()             play/pause
//     scrubbed(real f)      user clicked on timeline (0..1)
//     markedIn(real f)
//     markedOut(real f)

Rectangle {
    id: root

    property string fileName: "14-02-11_event.mp4"
    property int    duration: 983
    property bool   playing: false
    property real   playhead: 0.32
    property real   inMark:  0.12
    property real   outMark: 0.83

    signal toggled()
    signal scrubbed(real f)
    signal markedIn(real f)
    signal markedOut(real f)

    color: W.Tokens.bgBase

    // Event markers (positions are 0..1 along the timeline)
    readonly property var events: [
        { at: 0.04, label: "load",        tone: "ok"   },
        { at: 0.18, label: "401 inicial", tone: "warn" },
        { at: 0.31, label: "401",         tone: "warn" },
        { at: 0.46, label: "500",         tone: "rec"  },
        { at: 0.58, label: "401 burst",   tone: "warn" },
        { at: 0.81, label: "reconnect",   tone: "ok"   },
    ]
    function toneColor(t) {
        if (t === "rec")  return W.Tokens.accentRecord
        if (t === "warn") return W.Tokens.accentYellow
        return W.Tokens.accentOk
    }

    function fmt(f) {
        var total = f * root.duration
        var mm = Math.floor(total / 60)
        var ss = Math.floor(total % 60)
        var ff = Math.floor((total - Math.floor(total)) * 24)
        return String(mm).padStart(2, "0") + ":"
             + String(ss).padStart(2, "0") + ":"
             + String(ff).padStart(2, "0")
    }

    // ── Layout ────────────────────────────────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Editor toolbar ────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            color: "transparent"
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: W.Tokens.borderBase }

            RowLayout {
                anchors { fill: parent; leftMargin: 18; rightMargin: 18 }
                spacing: 12

                Text { text: "▦"; color: W.Tokens.accentMonitor
                       font.pixelSize: 13; font.weight: Font.Bold }
                Text { text: "EDITOR · SESIÓN ACTIVA"
                       color: W.Tokens.accentMonitor
                       font.family: W.Tokens.mono
                       font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                Rectangle {
                    width: 5; height: 5; radius: 3
                    color: W.Tokens.accentRecord
                    Layout.alignment: Qt.AlignVCenter
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.4; duration: 700 }
                        NumberAnimation { to: 1.0; duration: 700 }
                    }
                }
                Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 16
                            color: W.Tokens.borderBase }
                Text {
                    Layout.maximumWidth: 320
                    elide: Text.ElideMiddle
                    text: root.fileName
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 11
                }
                Rectangle {
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: metaTxt.implicitWidth + 14
                    radius: 3
                    color: W.Tokens.bgSurface
                    border.color: W.Tokens.borderBase; border.width: 1
                    Text {
                        id: metaTxt; anchors.centerIn: parent
                        text: "1920×1080 · 24FPS · H.264"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }

                Item { Layout.fillWidth: true }

                Rectangle {
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: oTxt.implicitWidth + 14
                    radius: 3
                    color: W.Tokens.bgSurface
                    border.color: W.Tokens.borderBase; border.width: 1
                    Text {
                        id: oTxt; anchors.centerIn: parent
                        text: "16:23 ORIGINAL"
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.mono
                        font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }
                Text { text: "→"; color: W.Tokens.textDim; font.pixelSize: 11 }
                Rectangle {
                    Layout.preferredHeight: 18
                    Layout.preferredWidth: eTxt.implicitWidth + 14
                    radius: 3
                    color: W.Tokens.primaryDim
                    border.color: Qt.rgba(W.Tokens.accentPrimary.r,
                                          W.Tokens.accentPrimary.g,
                                          W.Tokens.accentPrimary.b, 0.40)
                    border.width: 1
                    Text {
                        id: eTxt; anchors.centerIn: parent
                        text: root.fmt(root.outMark - root.inMark) + " EDITADO"
                        color: W.Tokens.accentPrimary
                        font.family: W.Tokens.mono
                        font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }
            }
        }

        // ── Preview area ──────────────────────────────────────────────
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: 320

            Item {
                anchors.fill: parent
                anchors.margins: 18

                // 16:9 framed centered preview
                Rectangle {
                    id: preview
                    anchors.centerIn: parent
                    width: Math.min(parent.width, parent.height * 16/9)
                    height: Math.min(parent.height, parent.width * 9/16)
                    color: W.Tokens.bgSurface
                    border.color: W.Tokens.borderBase; border.width: 1
                    radius: W.Tokens.rXs
                    clip: true

                    // Diagonal stripes pattern
                    Canvas {
                        id: stripes
                        anchors.fill: parent
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            ctx.save()
                            ctx.translate(width / 2, height / 2)
                            ctx.rotate(Math.PI / 4)
                            ctx.translate(-width, -height)
                            for (var x = 0; x < width * 3; x += 20) {
                                ctx.fillStyle = (x / 10) % 2 < 1
                                                ? "#141E30" : "#0D1220"
                                ctx.fillRect(x, 0, 10, height * 3)
                            }
                            ctx.restore()
                        }
                    }

                    // Radial vignette (use Canvas instead of a gradient rect
                    // because QML's Gradient only does linear).
                    Canvas {
                        anchors.fill: parent
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            var g = ctx.createRadialGradient(width/2, height/2, 20,
                                                             width/2, height/2,
                                                             Math.max(width, height) / 1.2)
                            g.addColorStop(0, "rgba(7, 9, 15, 0)")
                            g.addColorStop(1, "rgba(7, 9, 15, 0.7)")
                            ctx.fillStyle = g
                            ctx.fillRect(0, 0, width, height)
                        }
                    }

                    // Center info
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 10
                        Text { text: "▦"; color: W.Tokens.textMuted
                               font.pixelSize: 38
                               Layout.alignment: Qt.AlignHCenter }
                        Text { text: "VIDEO PREVIEW"
                               color: W.Tokens.textMuted
                               font.family: W.Tokens.mono
                               font.pixelSize: 10; font.letterSpacing: 1.6
                               Layout.alignment: Qt.AlignHCenter }
                        Text { text: Math.round(root.playhead * root.duration)
                                    + "s / " + root.duration + "s"
                               color: W.Tokens.textDim
                               font.family: W.Tokens.mono
                               font.pixelSize: 9; font.letterSpacing: 0.8
                               Layout.alignment: Qt.AlignHCenter }
                    }

                    // HUD top-left: timecode
                    RowLayout {
                        anchors { top: parent.top; left: parent.left
                                  margins: 10 }
                        spacing: 6
                        Rectangle { width: 5; height: 5; radius: 3
                                    color: W.Tokens.accentRecord
                                    Layout.alignment: Qt.AlignVCenter
                                    SequentialAnimation on opacity {
                                        loops: Animation.Infinite
                                        NumberAnimation { to: 0.4; duration: 700 }
                                        NumberAnimation { to: 1.0; duration: 700 } } }
                        Text { text: root.fmt(root.playhead)
                               color: W.Tokens.textPrimary
                               font.family: W.Tokens.mono
                               font.pixelSize: 9; font.letterSpacing: 0.8 }
                    }
                    // HUD top-right: frame
                    Text {
                        anchors { top: parent.top; right: parent.right; margins: 10 }
                        text: "FRAME " + Math.floor(root.playhead * root.duration * 24)
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 9; font.letterSpacing: 0.8
                    }
                    // HUD bottom-left: chips
                    Row {
                        anchors { bottom: parent.bottom; left: parent.left
                                  margins: 10 }
                        spacing: 4
                        Rectangle {
                            height: 16; width: opCh.implicitWidth + 10
                            radius: 2
                            color: Qt.rgba(0, 0, 0, 0.55)
                            border.color: W.Tokens.borderBase; border.width: 1
                            Text { id: opCh; anchors.centerIn: parent
                                   text: "OP-28"; color: W.Tokens.textPrimary
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 8; font.weight: Font.Bold; font.letterSpacing: 0.8 }
                        }
                        Rectangle {
                            height: 16; width: evCh.implicitWidth + 10
                            radius: 2
                            color: Qt.rgba(0, 0, 0, 0.55)
                            border.color: Qt.rgba(W.Tokens.accentYellow.r,
                                                  W.Tokens.accentYellow.g,
                                                  W.Tokens.accentYellow.b, 0.50)
                            border.width: 1
                            Text { id: evCh; anchors.centerIn: parent
                                   text: "EVT · auth error"
                                   color: W.Tokens.accentYellow
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 8; font.weight: Font.Bold; font.letterSpacing: 0.8 }
                        }
                    }
                }
            }
        }

        // ── Transport row ─────────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 18; Layout.rightMargin: 18
            Layout.topMargin: 10
            spacing: 8

            TransportBtn { glyph: "[ ◀"; tip: "Mark IN"
                onClicked: root.markedIn(root.playhead) }
            TransportBtn { glyph: "◂"; onClicked: {} }
            TransportBtn {
                glyph: root.playing ? "❚❚" : "▶"
                primary: true
                onClicked: root.toggled()
            }
            TransportBtn { glyph: "▸"; onClicked: {} }
            TransportBtn { glyph: "▶ ]"; tip: "Mark OUT"
                onClicked: root.markedOut(root.playhead) }
            Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18
                        color: W.Tokens.borderBase; Layout.leftMargin: 4 }
            TransportBtn { glyph: "✂"; tip: "Cut"; onClicked: {} }

            Item { Layout.fillWidth: true }

            // In / Out / Duration readout
            RowLayout {
                spacing: 10
                Text {
                    text: "IN " + root.fmt(root.inMark)
                    color: W.Tokens.accentMonitor
                    font.family: W.Tokens.mono
                    font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 0.8
                }
                Text { text: "·"; color: W.Tokens.textDim }
                Text {
                    text: "OUT " + root.fmt(root.outMark)
                    color: W.Tokens.accentMonitor
                    font.family: W.Tokens.mono
                    font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 0.8
                }
                Text { text: "·"; color: W.Tokens.textDim }
                Text {
                    text: "DUR " + root.fmt(root.outMark - root.inMark)
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 0.8
                }
            }
        }

        // ── Ruler ─────────────────────────────────────────────────────
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 16
            Layout.leftMargin: 18; Layout.rightMargin: 18
            Layout.topMargin: 8
            Repeater {
                model: 9
                delegate: ColumnLayout {
                    x: (parent.width / 8) * index - implicitWidth / 2
                    spacing: 2
                    Rectangle { width: 1; height: 4; color: W.Tokens.borderSubtle
                                Layout.alignment: Qt.AlignHCenter }
                    Text {
                        text: root.fmt(index / 8).substring(0, 5)
                        color: W.Tokens.textDim
                        font.family: W.Tokens.mono
                        font.pixelSize: 8; font.letterSpacing: 0.4
                    }
                }
            }
        }

        // ── Timeline track ────────────────────────────────────────────
        Item {
            id: track
            Layout.fillWidth: true
            Layout.preferredHeight: 64
            Layout.leftMargin: 18; Layout.rightMargin: 18
            Layout.topMargin: 2

            Rectangle {
                id: trackBg
                anchors.fill: parent
                color: W.Tokens.bgSurface
                border.color: W.Tokens.borderBase; border.width: 1
                radius: W.Tokens.rXs
                clip: true

                // Selected range
                Rectangle {
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    x: root.inMark * parent.width
                    width: (root.outMark - root.inMark) * parent.width
                    color: Qt.rgba(W.Tokens.accentPrimary.r,
                                   W.Tokens.accentPrimary.g,
                                   W.Tokens.accentPrimary.b, 0.16)
                    Rectangle {
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                        width: 2
                        color: W.Tokens.accentMonitor
                    }
                    Rectangle {
                        anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                        width: 2
                        color: W.Tokens.accentMonitor
                    }
                }

                // Waveform (procedural)
                Row {
                    anchors { fill: parent; topMargin: 4; bottomMargin: 4
                              leftMargin: 4; rightMargin: 4 }
                    spacing: 1
                    Repeater {
                        model: 160
                        delegate: Rectangle {
                            property real v: {
                                var a = Math.sin(index * 0.18) * 0.4
                                var b = Math.sin(index * 0.05 + 1) * 0.3
                                var c = Math.sin(index * 0.41) * 0.15
                                return Math.max(0.1, 0.5 + a + b + c)
                            }
                            width: (track.width - 8) / 160 - 1
                            height: parent.height * v * 0.7
                            anchors.verticalCenter: parent.verticalCenter
                            color: W.Tokens.accentMonitor
                            opacity: 0.45
                            radius: 0.5
                        }
                    }
                }

                // Event markers
                Repeater {
                    model: root.events
                    delegate: Rectangle {
                        anchors { top: parent.top; bottom: parent.bottom }
                        x: modelData.at * parent.width - 1
                        width: 2
                        color: root.toneColor(modelData.tone)
                        opacity: 0.9
                        Rectangle {
                            anchors.centerIn: parent
                            width: 8; height: parent.height + 6
                            color: "transparent"
                            border.color: root.toneColor(modelData.tone)
                            border.width: 1
                            opacity: 0.30
                        }
                    }
                }

                // Playhead
                Rectangle {
                    anchors { top: parent.top; bottom: parent.bottom; topMargin: -2; bottomMargin: -2 }
                    x: root.playhead * parent.width - 1
                    width: 2
                    color: W.Tokens.textPrimary
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        width: 10; height: 7
                        color: W.Tokens.textPrimary
                        // simple triangle via clip — render with 3 small rects
                        Rectangle { x: 0; y: 0; width: 10; height: 1; color: parent.color }
                        Rectangle { x: 1; y: 1; width:  8; height: 1; color: parent.color }
                        Rectangle { x: 2; y: 2; width:  6; height: 1; color: parent.color }
                        Rectangle { x: 3; y: 3; width:  4; height: 1; color: parent.color }
                        Rectangle { x: 4; y: 4; width:  2; height: 1; color: parent.color }
                    }
                }

                TapHandler {
                    onTapped: {
                        var f = Math.max(0, Math.min(1, point.position.x / trackBg.width))
                        root.scrubbed(f)
                    }
                }
            }
        }

        // ── Event legend ──────────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 18; Layout.rightMargin: 18
            Layout.topMargin: 6; Layout.bottomMargin: 12
            spacing: 14
            Text { text: "EVENTOS:"; color: W.Tokens.textDim
                   font.family: W.Tokens.mono
                   font.pixelSize: 9; font.letterSpacing: 1.2 }
            Repeater {
                model: root.events
                delegate: RowLayout {
                    spacing: 5
                    Rectangle { width: 4; height: 4; radius: 2
                                color: root.toneColor(modelData.tone)
                                Layout.alignment: Qt.AlignVCenter }
                    Text { text: modelData.label
                           color: W.Tokens.textMuted
                           font.family: W.Tokens.mono
                           font.pixelSize: 9; font.letterSpacing: 0.4 }
                }
            }
            Item { Layout.fillWidth: true }
            Text { text: "ESPACIO · play/pause   I/O · marcas"
                   color: W.Tokens.textDim
                   font.family: W.Tokens.mono
                   font.pixelSize: 9; font.letterSpacing: 0.4 }
        }
    }

    // ── Local component: transport button ─────────────────────────────────
    component TransportBtn : Rectangle {
        id: btn
        property string glyph
        property string tip: ""
        property bool   primary: false
        signal clicked()

        implicitWidth: primary ? 40 : 32
        implicitHeight: 32
        radius: W.Tokens.rXs
        color: primary
               ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                         W.Tokens.accentPrimary.b, hh.hovered ? 1 : 0.85)
               : (hh.hovered ? W.Tokens.bgElevated : W.Tokens.bgSurface)
        border.color: primary ? W.Tokens.accentPrimary : W.Tokens.borderBase
        border.width: 1
        Behavior on color { ColorAnimation { duration: 100 } }

        HoverHandler { id: hh }
        TapHandler   { onTapped: btn.clicked() }
        scale: hh.hovered ? 1.02 : 1.0
        Behavior on scale { NumberAnimation { duration: 100 } }

        ToolTip.visible: hh.hovered && btn.tip.length > 0
        ToolTip.text: btn.tip

        Text {
            anchors.centerIn: parent
            text: btn.glyph
            color: btn.primary ? W.Tokens.bgBase : W.Tokens.textPrimary
            font.family: btn.glyph.length > 1 ? W.Tokens.mono : "sans-serif"
            font.pixelSize: 12
            font.weight: Font.Bold
        }
    }
}
