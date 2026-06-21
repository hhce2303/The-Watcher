import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
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

    property string fileName: ""
    // Real clip metadata from AppBridge.currentClipInfo (ffprobe):
    // { resolution, codec, fps, bitrate, durationSeconds }. Empty {} → "—".
    property var    clipInfo: ({})
    // Media source URL (AppBridge.mediaUrl(currentClipPath)); "" → placeholder.
    property url    source: ""

    // Playback state is OWNED by the MediaPlayer (real position/duration), not
    // driven externally. Marks are editable fractions (0..1 of duration).
    readonly property real duration:
        player.duration > 0 ? player.duration / 1000
                            : ((clipInfo && clipInfo.durationSeconds) ? clipInfo.durationSeconds : 0)
    readonly property bool playing:  player.playbackState === MediaPlayer.PlayingState
    readonly property real playhead: player.duration > 0 ? player.position / player.duration : 0
    property real inMark:  0.0
    property real outMark: 1.0

    // Timeline zoom + frame stepping.
    property real zoom: 1.0
    readonly property int fps:
        (clipInfo && clipInfo.fps && parseFloat(clipInfo.fps) > 0) ? Math.round(parseFloat(clipInfo.fps)) : 30
    readonly property int tickCount: Math.max(8, Math.round(8 * zoom))

    // ── Transport — operate the REAL player ────────────────────────────────
    function togglePlay() {
        if (root.source == "") return
        if (player.playbackState === MediaPlayer.PlayingState) player.pause()
        else player.play()
    }
    function seekFraction(f) {
        if (player.duration > 0)
            player.position = Math.max(0, Math.min(1, f)) * player.duration
    }
    function frameStep(dir) {
        if (player.duration <= 0) return
        player.pause()
        var stepMs = 1000.0 / Math.max(1, root.fps)
        player.position = Math.max(0, Math.min(player.duration, player.position + dir * stepMs))
    }
    function markIn()  { root.inMark  = root.playhead; if (root.outMark < root.inMark) root.outMark = 1.0 }
    function markOut() { root.outMark = root.playhead; if (root.inMark > root.outMark) root.inMark = 0.0 }

    function setZoom(z) { root.zoom = Math.max(1, Math.min(8, z)) }

    // Recenter the timeline viewport on the playhead when zoom changes.
    onZoomChanged: {
        var cw = tlFlick.width * root.zoom
        tlFlick.contentX = Math.max(0, Math.min(cw - tlFlick.width,
                                    root.playhead * cw - tlFlick.width / 2))
    }

    color: W.Tokens.bgBase

    // The real media player (Qt FFmpeg backend). Nothing plays until a source
    // is set and play() is called. Pauses at the OUT mark while previewing.
    MediaPlayer {
        id: player
        source: root.source
        videoOutput: videoOut
        audioOutput: AudioOutput { id: audioOut }
        onPositionChanged: {
            if (playbackState === MediaPlayer.PlayingState
                && root.outMark < 1.0 && duration > 0
                && position >= root.outMark * duration) {
                pause()
            }
        }
    }

    function fmt(f) {
        var total = f * root.duration
        var mm = Math.floor(total / 60)
        var ss = Math.floor(total % 60)
        var ff = Math.floor((total - Math.floor(total)) * root.fps)
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
                        // Honest metadata: real ffprobe values, "—" for any missing field.
                        text: {
                            var ci  = root.clipInfo || {}
                            var res = ci.resolution ? ci.resolution : "—"
                            var fps = ci.fps ? (ci.fps + "FPS") : "—"
                            var cod = ci.codec ? ("" + ci.codec).toUpperCase() : "—"
                            var br  = ci.bitrate ? ("  ·  " + ci.bitrate) : ""
                            return res + " · " + fps + " · " + cod + br
                        }
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

                    // Real video frames (Qt FFmpeg backend), letterboxed to 16:9.
                    VideoOutput {
                        id: videoOut
                        anchors.fill: parent
                        fillMode: VideoOutput.PreserveAspectFit
                        visible: root.source != ""
                    }

                    // Diagonal stripes pattern with lower opacity
                    Canvas {
                        id: stripes
                        visible: root.source == ""
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
                        visible: root.source == ""
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

                    // Placeholder (only when no clip is loaded)
                    ColumnLayout {
                        visible: root.source == ""
                        anchors.centerIn: parent
                        spacing: 12
                        Text { text: "▦"; color: Qt.rgba(255, 255, 255, 0.15)
                               font.pixelSize: 44
                               Layout.alignment: Qt.AlignHCenter }
                        Text { text: "SIN CLIP CARGADO"
                               color: W.Tokens.textMuted
                               font.family: W.Tokens.mono
                               font.pixelSize: 13; font.letterSpacing: 2.0; font.weight: Font.DemiBold
                               Layout.alignment: Qt.AlignHCenter }
                        Text { text: "Selecciona un archivo y pulsa «Cargar para editar»"
                               color: W.Tokens.textDim
                               font.family: W.Tokens.mono
                               font.pixelSize: 12; font.letterSpacing: 0.6
                               Layout.alignment: Qt.AlignHCenter }
                    }

                    // HUD top-left: timecode
                    Rectangle {
                        visible: root.source != ""
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
                        visible: root.source != ""
                        anchors { top: parent.top; right: parent.right; margins: 12 }
                        height: 24; width: frameTxt.implicitWidth + 16
                        color: Qt.rgba(0, 0, 0, 0.6)
                        radius: W.Tokens.rSm
                        border.color: Qt.rgba(255, 255, 255, 0.1); border.width: 1
                        Text {
                            id: frameTxt
                            anchors.centerIn: parent
                            text: "FRAME " + Math.floor(root.playhead * root.duration * root.fps)
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono
                            font.pixelSize: 11; font.letterSpacing: 1.0; font.weight: Font.DemiBold
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

            TransportBtn { glyph: "[ ◀"; tip: "Marca IN"
                onClicked: root.markIn() }
            TransportBtn { glyph: "◂"; tip: "Frame anterior"; onClicked: root.frameStep(-1) }
            TransportBtn {
                glyph: root.playing ? "❚❚" : "▶"
                primary: true
                onClicked: root.togglePlay()
            }
            TransportBtn { glyph: "▸"; tip: "Frame siguiente"; onClicked: root.frameStep(1) }
            TransportBtn { glyph: "▶ ]"; tip: "Marca OUT"
                onClicked: root.markOut() }
            Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18
                        color: W.Tokens.borderBase; Layout.leftMargin: 4 }

            // Zoom de la línea de tiempo
            TransportBtn { glyph: "−"; tip: "Alejar"; onClicked: root.setZoom(root.zoom / 1.5) }
            Text {
                text: Math.round(root.zoom * 100) + "%"
                color: W.Tokens.textMuted
                font.family: W.Tokens.mono; font.pixelSize: 12; font.weight: Font.Bold
                Layout.alignment: Qt.AlignVCenter
                Layout.minimumWidth: 44
                horizontalAlignment: Text.AlignHCenter
            }
            TransportBtn { glyph: "+"; tip: "Acercar"; onClicked: root.setZoom(root.zoom * 1.5) }
            TransportBtn { glyph: "⤢"; tip: "Ajustar"; onClicked: root.setZoom(1) }

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

        // ── Ruler (zoom-aware, synced to the timeline viewport) ────────
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 16
            Layout.leftMargin: 18; Layout.rightMargin: 18
            Layout.topMargin: 8
            Flickable {
                id: rulerFlick
                anchors.fill: parent
                interactive: false
                clip: true
                contentWidth: Math.max(width, width * root.zoom)
                contentHeight: height
                contentX: tlFlick.contentX
                Item {
                    width: rulerFlick.contentWidth
                    height: rulerFlick.height
                    Repeater {
                        model: root.tickCount + 1
                        delegate: ColumnLayout {
                            x: (parent.width / root.tickCount) * index - implicitWidth / 2
                            spacing: 2
                            Rectangle { width: 1; height: 4; color: W.Tokens.borderSubtle
                                        Layout.alignment: Qt.AlignHCenter }
                            Text {
                                text: root.fmt(index / root.tickCount).substring(0, 5)
                                color: W.Tokens.textDim
                                font.family: W.Tokens.mono
                                font.pixelSize: 10; font.letterSpacing: 0.4
                            }
                        }
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

            Flickable {
                id: tlFlick
                anchors.fill: parent
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentWidth: Math.max(width, width * root.zoom)
                contentHeight: height

            Rectangle {
                id: trackBg
                width: tlFlick.contentWidth
                height: tlFlick.height
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

                // Played progress — real position fill (0 → playhead).
                Rectangle {
                    anchors.top: parent.top; anchors.bottom: parent.bottom
                    anchors.margins: 1
                    x: 1
                    width: Math.max(0, root.playhead * (trackBg.width - 2))
                    color: Qt.rgba(W.Tokens.accentMonitor.r, W.Tokens.accentMonitor.g,
                                   W.Tokens.accentMonitor.b, 0.16)
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
                        root.seekFraction(f)
                    }
                }
            }
            }
        }

        // ── Hint bar ──────────────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 18; Layout.rightMargin: 18
            Layout.topMargin: 6; Layout.bottomMargin: 12
            spacing: 14
            Text {
                text: root.clipInfo && root.clipInfo.codec
                      ? (("" + root.clipInfo.codec).toUpperCase()
                         + (root.clipInfo.resolution ? "  ·  " + root.clipInfo.resolution : "")
                         + "  ·  " + root.fps + " FPS")
                      : ""
                color: W.Tokens.textDim
                font.family: W.Tokens.mono
                font.pixelSize: 11; font.letterSpacing: 0.6
            }
            Item { Layout.fillWidth: true }
            Text { text: "ESPACIO · play/pause   ◂ ▸ · frame   I/O · marcas"
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
