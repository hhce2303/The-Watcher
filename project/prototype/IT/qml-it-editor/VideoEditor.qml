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
                       font.pixelSize: 15; font.weight: Font.Bold }
                Text { text: "EDITOR · SESIÓN ACTIVA"
                       color: W.Tokens.accentMonitor
                       font.family: W.Tokens.mono
                       font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6 }
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
                    font.pixelSize: 13
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
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8
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
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8
                    }
                }
                Text { text: "→"; color: W.Tokens.textDim; font.pixelSize: 13 }
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
                        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8
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
                    color: W.Tokens.bgBase
                    border.color: W.Tokens.borderSubtle; border.width: 1
                    radius: W.Tokens.rMd
                    clip: true

                    // Diagonal stripes pattern with lower opacity
                    Canvas {
                        id: stripes
                        anchors.fill: parent
                        opacity: 0.5
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            ctx.save()
                            ctx.translate(width / 2, height / 2)
                            ctx.rotate(Math.PI / 4)
                            ctx.translate(-width, -height)
                            for (var x = 0; x < width * 3; x += 16) {
                                ctx.fillStyle = (x / 8) % 2 < 1
                                                ? Qt.rgba(1, 1, 1, 0.02) : Qt.rgba(0, 0, 0, 0.1)
                                ctx.fillRect(x, 0, 8, height * 3)
                            }
                            ctx.restore()
                        }
                    }

                    // Radial vignette deeper and more polished
                    Canvas {
                        anchors.fill: parent
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.clearRect(0, 0, width, height)
                            var g = ctx.createRadialGradient(width/2, height/2, 0,
                                                             width/2, height/2,
                                                             Math.max(width, height) / 1.1)
                            g.addColorStop(0, "rgba(7, 9, 15, 0.1)")
                            g.addColorStop(0.7, "rgba(7, 9, 15, 0.6)")
                            g.addColorStop(1, "rgba(7, 9, 15, 0.95)")
                            ctx.fillStyle = g
                            ctx.fillRect(0, 0, width, height)
                        }
                    }

                    // Inner glow
                    Rectangle {
                        anchors.fill: parent
                        color: "transparent"
                        border.color: Qt.rgba(255, 255, 255, 0.05)
                        border.width: 1
                        radius: W.Tokens.rMd
                    }

                    // Center info
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 12
                        Text { text: "▦"; color: Qt.rgba(255, 255, 255, 0.15)
                               font.pixelSize: 44
                               Layout.alignment: Qt.AlignHCenter }
                        Text { text: "VIDEO PREVIEW"
                               color: W.Tokens.textMuted
                               font.family: W.Tokens.mono
                               font.pixelSize: 13; font.letterSpacing: 2.0; font.weight: Font.DemiBold
                               Layout.alignment: Qt.AlignHCenter }
                        Text { text: Math.round(root.playhead * root.duration)
                                    + "s / " + root.duration + "s"
                               color: W.Tokens.textDim
                               font.family: W.Tokens.mono
                               font.pixelSize: 12; font.letterSpacing: 1.0
                               Layout.alignment: Qt.AlignHCenter }
                    }

                    // HUD top-left: timecode
                    Rectangle {
                        anchors { top: parent.top; left: parent.left; margins: 12 }
                        height: 24; width: timecodeLayout.implicitWidth + 16
                        color: Qt.rgba(0, 0, 0, 0.6)
                        radius: W.Tokens.rSm
                        border.color: Qt.rgba(255, 255, 255, 0.1); border.width: 1
                        RowLayout {
                            id: timecodeLayout
                            anchors.centerIn: parent
                            spacing: 8
                            Rectangle { width: 6; height: 6; radius: 3
                                        color: W.Tokens.accentRecord
                                        Layout.alignment: Qt.AlignVCenter
                                        SequentialAnimation on opacity {
                                            loops: Animation.Infinite
                                            NumberAnimation { to: 0.3; duration: 800; easing.type: Easing.InOutSine }
                                            NumberAnimation { to: 1.0; duration: 800; easing.type: Easing.InOutSine } } }
                            Text { text: root.fmt(root.playhead)
                                   color: W.Tokens.textPrimary
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 12; font.letterSpacing: 1.0; font.weight: Font.DemiBold }
                        }
                    }

                    // HUD top-right: frame
                    Rectangle {
                        anchors { top: parent.top; right: parent.right; margins: 12 }
                        height: 24; width: frameTxt.implicitWidth + 16
                        color: Qt.rgba(0, 0, 0, 0.6)
                        radius: W.Tokens.rSm
                        border.color: Qt.rgba(255, 255, 255, 0.1); border.width: 1
                        Text {
                            id: frameTxt
                            anchors.centerIn: parent
                            text: "FRAME " + Math.floor(root.playhead * root.duration * 24)
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono
                            font.pixelSize: 11; font.letterSpacing: 1.0; font.weight: Font.DemiBold
                        }
                    }

                    // HUD bottom-left: chips
                    Row {
                        anchors { bottom: parent.bottom; left: parent.left; margins: 12 }
                        spacing: 6
                        Rectangle {
                            height: 20; width: opCh.implicitWidth + 12
                            radius: W.Tokens.rSm
                            color: Qt.rgba(0, 0, 0, 0.7)
                            border.color: Qt.rgba(255, 255, 255, 0.15); border.width: 1
                            Text { id: opCh; anchors.centerIn: parent
                                   text: "OP-28"; color: W.Tokens.textPrimary
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.0 }
                        }
                        Rectangle {
                            height: 20; width: evCh.implicitWidth + 12
                            radius: W.Tokens.rSm
                            color: Qt.rgba(0, 0, 0, 0.7)
                            border.color: Qt.rgba(W.Tokens.accentYellow.r,
                                                  W.Tokens.accentYellow.g,
                                                  W.Tokens.accentYellow.b, 0.50)
                            border.width: 1
                            Text { id: evCh; anchors.centerIn: parent
                                   text: "EVT · auth error"
                                   color: W.Tokens.accentYellow
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.0 }
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
                    font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 0.8
                }
                Text { text: "·"; color: W.Tokens.textDim }
                Text {
                    text: "OUT " + root.fmt(root.outMark)
                    color: W.Tokens.accentMonitor
                    font.family: W.Tokens.mono
                    font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 0.8
                }
                Text { text: "·"; color: W.Tokens.textDim }
                Text {
                    text: "DUR " + root.fmt(root.outMark - root.inMark)
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 0.8
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
                        font.pixelSize: 10; font.letterSpacing: 0.4
                    }
                }
            }
        }

        // ── Timeline track ────────────────────────────────────────────
        Item {
            id: track
            Layout.fillWidth: true
            Layout.preferredHeight: 72
            Layout.leftMargin: 18; Layout.rightMargin: 18
            Layout.topMargin: 2

            Rectangle {
                id: trackBg
                anchors.fill: parent
                color: W.Tokens.bgElevated
                border.color: W.Tokens.borderBase; border.width: 1
                radius: W.Tokens.rSm
                clip: true

                // Inner shadow for depth
                Rectangle {
                    anchors.fill: parent
                    color: "transparent"
                    border.color: Qt.rgba(0, 0, 0, 0.4)
                    border.width: 2
                    radius: W.Tokens.rSm
                }

                // Selected range background
                Rectangle {
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    x: root.inMark * parent.width
                    width: (root.outMark - root.inMark) * parent.width
                    color: Qt.rgba(W.Tokens.accentPrimary.r,
                                   W.Tokens.accentPrimary.g,
                                   W.Tokens.accentPrimary.b, 0.12)
                }

                // Waveform (procedural)
                Row {
                    anchors { fill: parent; topMargin: 6; bottomMargin: 6
                              leftMargin: 4; rightMargin: 4 }
                    spacing: 2
                    Repeater {
                        model: 120
                        delegate: Rectangle {
                            property real v: {
                                var a = Math.sin(index * 0.22) * 0.5
                                var b = Math.sin(index * 0.08 + 1) * 0.3
                                var c = Math.sin(index * 0.55) * 0.2
                                return Math.max(0.05, 0.4 + a + b + c)
                            }
                            property bool inSelection: {
                                var pos = (index + 0.5) / 120
                                return pos >= root.inMark && pos <= root.outMark
                            }
                            width: (track.width - 8) / 120 - 2
                            height: parent.height * v * 0.85
                            anchors.verticalCenter: parent.verticalCenter
                            color: inSelection ? W.Tokens.accentPrimary : W.Tokens.accentMonitor
                            opacity: inSelection ? 0.9 : 0.3
                            radius: width / 2
                            Behavior on color { ColorAnimation { duration: W.Tokens.durFast } }
                            Behavior on opacity { NumberAnimation { duration: W.Tokens.durFast } }
                        }
                    }
                }

                // Selected range borders (In/Out markers)
                Rectangle {
                    anchors.top: parent.top; anchors.bottom: parent.bottom
                    x: root.inMark * parent.width
                    width: 2
                    color: W.Tokens.accentPrimary
                    Rectangle { anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
                                width: 8; height: 8; radius: 2; color: W.Tokens.accentPrimary }
                }
                Rectangle {
                    anchors.top: parent.top; anchors.bottom: parent.bottom
                    x: root.outMark * parent.width - 2
                    width: 2
                    color: W.Tokens.accentPrimary
                    Rectangle { anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
                                width: 8; height: 8; radius: 2; color: W.Tokens.accentPrimary }
                }

                // Event markers
                Repeater {
                    model: root.events
                    delegate: Rectangle {
                        anchors { top: parent.top; bottom: parent.bottom }
                        x: modelData.at * parent.width - 1
                        width: 2
                        color: root.toneColor(modelData.tone)
                        opacity: 0.85
                        Rectangle {
                            anchors.centerIn: parent
                            width: 8; height: parent.height
                            color: "transparent"
                            border.color: root.toneColor(modelData.tone)
                            border.width: 1
                            opacity: 0.25
                            radius: 2
                        }
                    }
                }

                // Playhead
                Rectangle {
                    anchors { top: parent.top; bottom: parent.bottom }
                    x: root.playhead * parent.width - 1
                    width: 2
                    color: "#FFFFFF"
                    
                    // Glow effect
                    Rectangle {
                        anchors.centerIn: parent
                        width: 6; height: parent.height
                        color: Qt.rgba(255, 255, 255, 0.15)
                    }

                    // Playhead handle
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        anchors.topMargin: -6
                        width: 12; height: 12
                        color: "#FFFFFF"
                        radius: 3
                        rotation: 45
                        border.color: Qt.rgba(0, 0, 0, 0.5)
                        border.width: 1
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
                   font.pixelSize: 11; font.letterSpacing: 1.2 }
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
                           font.pixelSize: 11; font.letterSpacing: 0.4 }
                }
            }
            Item { Layout.fillWidth: true }
            Text { text: "ESPACIO · play/pause   I/O · marcas"
                   color: W.Tokens.textDim
                   font.family: W.Tokens.mono
                   font.pixelSize: 11; font.letterSpacing: 0.4 }
        }
    }

    // ── Local component: transport button ─────────────────────────────────
    component TransportBtn : Rectangle {
        id: btn
        property string glyph
        property string tip: ""
        property bool   primary: false
        signal clicked()

        implicitWidth: primary ? 46 : 36
        implicitHeight: 36
        radius: W.Tokens.rSm
        
        property color _baseColor: primary 
                                   ? W.Tokens.accentPrimary 
                                   : W.Tokens.bgElevated
        property color _hoverColor: primary 
                                    ? Qt.lighter(W.Tokens.accentPrimary, 1.1) 
                                    : Qt.lighter(W.Tokens.bgElevated, 1.5)

        color: hh.hovered ? _hoverColor : _baseColor
        
        border.color: primary ? Qt.rgba(255,255,255,0.2) : W.Tokens.borderSubtle
        border.width: 1
        
        Behavior on color { ColorAnimation { duration: W.Tokens.durFast; easing.type: Easing.OutQuad } }

        // Subtle glow effect when hovered
        Rectangle {
            anchors.fill: parent
            anchors.margins: -4
            radius: W.Tokens.rSm + 4
            color: "transparent"
            border.color: primary ? W.Tokens.accentPrimary : "transparent"
            border.width: 2
            opacity: hh.hovered ? 0.3 : 0.0
            Behavior on opacity { NumberAnimation { duration: W.Tokens.durFast } }
        }

        HoverHandler { id: hh }
        TapHandler   { 
            onTapped: {
                // Click effect animation
                clickAnim.restart()
                btn.clicked() 
            }
        }
        
        scale: hh.hovered ? 1.05 : 1.0
        Behavior on scale { NumberAnimation { duration: W.Tokens.durFast; easing.type: Easing.OutBack } }

        SequentialAnimation on scale {
            id: clickAnim
            running: false
            NumberAnimation { to: 0.95; duration: 50 }
            NumberAnimation { to: hh.hovered ? 1.05 : 1.0; duration: 100 }
        }

        ToolTip.visible: hh.hovered && btn.tip.length > 0
        ToolTip.text: btn.tip

        Text {
            anchors.centerIn: parent
            text: btn.glyph
            color: btn.primary ? W.Tokens.bgBase : W.Tokens.textPrimary
            font.family: btn.glyph.length > 1 ? W.Tokens.mono : "sans-serif"
            font.pixelSize: 16
            font.weight: Font.Bold
        }
    }
}
