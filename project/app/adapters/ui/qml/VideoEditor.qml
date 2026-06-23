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

    // Spatial zoom/pan of the picture (R-3b) — lossless up to native resolution.
    property real picZoom: 1.0
    property real picPanX: 0.0
    property real picPanY: 0.0

    // Evidence reel (R-1): selected clip in EditorBridge.clips + export state.
    property int    reelSelected: -1
    // Guards for the reel↔editor round-trip (see loadReelClip): true while we
    // programmatically open a reel clip, so the currentClipPath watcher won't
    // clear the selection and restored marks won't echo back onto the clip.
    property bool   _openingReel: false
    property bool   _suspendMarkSync: false

    // ── Multi-clip sequence state (B) ──────────────────────────────────────
    // The big timeline renders the whole reel end-to-end; these track WHERE the
    // open clip sits in global reel time so one MediaPlayer can drive a global
    // playhead and auto-advance across clips.
    property real   selClipStartGlobal: 0   // global start (s) of the open reel clip
    property real   selClipInSecs:      0   // open clip's IN  (s in source)
    property real   selClipOutSecs:     0   // open clip's OUT (s in source)
    property real   reelElapsed:        0   // global seconds elapsed across the reel
    property int    _pendingPlayIndex: -1   // clip awaiting media-load to resume playback

    property bool   exporting: false
    property int    exportPct: 0
    property string exportMsg: ""

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

    // ── Spatial zoom (R-3b) ────────────────────────────────────────────────
    function resetPicZoom() { root.picZoom = 1.0; root.picPanX = 0.0; root.picPanY = 0.0 }
    function nudgePicZoom(factor) {
        root.picZoom = Math.max(1, Math.min(6, root.picZoom * factor))
        if (root.picZoom <= 1.001) root.resetPicZoom()
    }

    // ── Evidence reel (R-1, R-5) — via EditorBridge (global context prop) ───
    // Add the loaded clip to the reel, already trimmed to the current IN/OUT
    // marks, then select it so further mark edits keep updating it live.
    function addToReel() {
        if (AppBridge.currentClipPath === "" || root.duration <= 0) return
        EditorBridge.addClipTrimmed(AppBridge.currentClipPath, root.duration,
                                    root.inMark, root.outMark)
        root.reelSelected = EditorBridge.count - 1
    }
    function applyMarksToReel() {
        // Push the current IN/OUT marks (fractions) onto the selected reel clip.
        if (root.reelSelected >= 0)
            EditorBridge.setTrimFraction(root.reelSelected, root.inMark, root.outMark)
    }

    // Open a reel clip in the preview: load its source, restore its stored
    // IN/OUT as marks, and select it. The guards stop this round-trip from
    // clearing the selection (currentClipPath watcher) or echoing the restored
    // marks straight back onto the clip (_syncSelectedTrim).
    function loadReelClip(md, idx) {
        if (!md) return
        root._suspendMarkSync = true
        root._openingReel = true
        AppBridge.loadClip(md.sourcePath)
        root.reelSelected = idx
        var dur = md.sourceDuration
        root.inMark  = dur > 0 ? md.inPoint  / dur : 0.0
        root.outMark = dur > 0 ? md.outPoint / dur : 1.0
        root._recomputeSelGlobals()
        root.reelElapsed = root.selClipStartGlobal
        root._openingReel = false
        root._suspendMarkSync = false
    }
    function openReelClip(i) {
        var list = EditorBridge.clips
        if (i < 0 || i >= list.length) return
        root.loadReelClip(list[i], i)
    }
    // Recompute where the open clip sits in global reel time (its start offset
    // and its IN/OUT in source seconds). Kept in sync on select + on every trim.
    function _recomputeSelGlobals() {
        var list = EditorBridge.clips
        var i = root.reelSelected
        if (i < 0 || i >= list.length) {
            root.selClipStartGlobal = 0; root.selClipInSecs = 0; root.selClipOutSecs = 0
            return
        }
        var s = 0
        for (var k = 0; k < i; k++) s += list[k].trimmedDuration
        root.selClipStartGlobal = s
        root.selClipInSecs  = list[i].inPoint
        root.selClipOutSecs = list[i].outPoint
    }
    // Live-apply mark edits to the clip currently open from the reel.
    function _syncSelectedTrim() {
        if (root._suspendMarkSync || root.reelSelected < 0) return
        EditorBridge.setTrimFraction(root.reelSelected, root.inMark, root.outMark)
    }
    onInMarkChanged:  root._syncSelectedTrim()
    onOutMarkChanged: root._syncSelectedTrim()
    function toggleFullscreen() {
        if (fsPlayer.visible) fsPlayer.close()
        else fsPlayer.showFullScreen()
    }

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
            var localSecs = position / 1000

            // Global playhead: where we are across the WHOLE reel. When a reel
            // clip is open, offset the local time by the clip's start; otherwise
            // (single-clip preview) the global position is just the local time.
            if (root.reelSelected >= 0)
                root.reelElapsed = root.selClipStartGlobal
                                 + Math.max(0, localSecs - root.selClipInSecs)
            else
                root.reelElapsed = localSecs

            if (playbackState !== MediaPlayer.PlayingState || duration <= 0)
                return

            // Reel clip open: stop at its OUT, then auto-advance to the next clip
            // so play() traverses the whole sequence (B2).
            if (root.reelSelected >= 0) {
                if (localSecs >= root.selClipOutSecs - 0.04) {
                    var next = root.reelSelected + 1
                    if (next < EditorBridge.count) {
                        root._pendingPlayIndex = next   // resume after media loads
                        root.openReelClip(next)
                    } else {
                        pause()
                    }
                }
            // Single-clip preview: pause at the editing OUT mark (legacy).
            } else if (root.outMark < 1.0 && position >= root.outMark * duration) {
                pause()
            }
        }
        // When the next clip's media is ready, seek to its IN and resume — this
        // is what makes the playhead cross clip boundaries during reel playback.
        onMediaStatusChanged: {
            if (mediaStatus === MediaPlayer.LoadedMedia && root._pendingPlayIndex >= 0) {
                player.position = root.selClipInSecs * 1000
                player.play()
                root._pendingPlayIndex = -1
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

    // mm:ss from an absolute seconds value (reel durations).
    function fmtSecs(s) {
        var t = Math.max(0, Math.floor(s))
        return String(Math.floor(t / 60)).padStart(2, "0") + ":"
             + String(t % 60).padStart(2, "0")
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
                        // Spatial zoom/pan (R-3b): scale around centre, then pan.
                        // Scales the real decoded frame → lossless up to source res.
                        transform: [
                            Scale {
                                origin.x: videoOut.width / 2; origin.y: videoOut.height / 2
                                xScale: root.picZoom; yScale: root.picZoom
                            },
                            Translate { x: root.picPanX; y: root.picPanY }
                        ]
                    }

                    // Wheel = zoom, drag = pan (only while zoomed in).
                    WheelHandler {
                        target: null
                        enabled: root.source != ""
                        onWheel: function(ev) {
                            root.nudgePicZoom(ev.angleDelta.y > 0 ? 1.12 : 1 / 1.12)
                        }
                    }
                    DragHandler {
                        target: null
                        enabled: root.source != "" && root.picZoom > 1.001
                        property real baseX: 0
                        property real baseY: 0
                        onActiveChanged: if (active) { baseX = root.picPanX; baseY = root.picPanY }
                        onActiveTranslationChanged: {
                            root.picPanX = baseX + activeTranslation.x
                            root.picPanY = baseY + activeTranslation.y
                        }
                    }

                    // Spatial-zoom badge (top-centre) when zoomed.
                    Rectangle {
                        visible: root.picZoom > 1.001
                        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 12 }
                        height: 22; width: zTxt.implicitWidth + 16; radius: W.Tokens.rSm
                        color: Qt.rgba(0, 0, 0, 0.6)
                        Text { id: zTxt; anchors.centerIn: parent
                               text: "ZOOM " + Math.round(root.picZoom * 100) + "%  ·  arrastra para mover"
                               color: W.Tokens.textPrimary; font.family: W.Tokens.mono; font.pixelSize: 11 }
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

            Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 18
                        color: W.Tokens.borderBase; Layout.leftMargin: 4 }

            // Reel + view actions (R-1, R-3b, R-4).
            TransportBtn { glyph: "＋"; tip: "Añadir clip al reel"; onClicked: root.addToReel() }
            TransportBtn { glyph: "✂"; tip: "Aplicar recorte IN/OUT al clip seleccionado del reel"
                           onClicked: root.applyMarksToReel() }
            TransportBtn { glyph: "⛶"; tip: "Pantalla completa"; onClicked: root.toggleFullscreen() }
            TransportBtn { glyph: "⟲"; tip: "Restablecer zoom de imagen"; onClicked: root.resetPicZoom() }

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
                                // Sequence view → global reel time; else single-clip time.
                                text: EditorBridge.count > 0
                                      ? root.fmtSecs((index / root.tickCount) * EditorBridge.totalDuration)
                                      : root.fmt(index / root.tickCount).substring(0, 5)
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

                // ── Single-clip surface — used only while the reel is empty ──
                // (lets you trim a freshly loaded clip before adding it with ＋)
                Item {
                    anchors.fill: parent
                    visible: EditorBridge.count === 0

                    Rectangle {   // selected IN..OUT range
                        anchors.top: parent.top; anchors.bottom: parent.bottom
                        x: root.inMark * parent.width
                        width: (root.outMark - root.inMark) * parent.width
                        color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                                       W.Tokens.accentPrimary.b, 0.12)
                    }
                    Rectangle {   // played progress
                        anchors.top: parent.top; anchors.bottom: parent.bottom
                        anchors.margins: 1; x: 1
                        width: Math.max(0, root.playhead * (trackBg.width - 2))
                        color: Qt.rgba(W.Tokens.accentMonitor.r, W.Tokens.accentMonitor.g,
                                       W.Tokens.accentMonitor.b, 0.16)
                    }
                    Rectangle {   // IN marker
                        anchors.top: parent.top; anchors.bottom: parent.bottom
                        x: root.inMark * parent.width; width: 2; color: W.Tokens.accentPrimary
                        Rectangle { anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
                                    width: 8; height: 8; radius: 2; color: W.Tokens.accentPrimary }
                    }
                    Rectangle {   // OUT marker
                        anchors.top: parent.top; anchors.bottom: parent.bottom
                        x: root.outMark * parent.width - 2; width: 2; color: W.Tokens.accentPrimary
                        Rectangle { anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
                                    width: 8; height: 8; radius: 2; color: W.Tokens.accentPrimary }
                    }
                    Rectangle {   // playhead
                        anchors { top: parent.top; bottom: parent.bottom }
                        x: root.playhead * parent.width - 1; width: 2; color: "#FFFFFF"
                        Rectangle { anchors.centerIn: parent; width: 6; height: parent.height
                                    color: Qt.rgba(255, 255, 255, 0.15) }
                    }
                    TapHandler {
                        onTapped: root.seekFraction(Math.max(0, Math.min(1, point.position.x / trackBg.width)))
                    }
                }

                // ── Sequence surface — the whole reel as one multi-clip track ──
                // Every clip is a block sized by its trimmed duration, laid
                // end-to-end. A single global playhead crosses all of them.
                Item {
                    anchors.fill: parent
                    visible: EditorBridge.count > 0

                    Row {
                        id: seqRow
                        anchors.fill: parent
                        anchors.margins: 1
                        spacing: 0
                        Repeater {
                            model: EditorBridge.clips
                            delegate: Rectangle {
                                id: seqCell
                                required property var modelData
                                required property int index
                                width: (EditorBridge.totalDuration > 0
                                        ? modelData.trimmedDuration / EditorBridge.totalDuration : 0) * seqRow.width
                                height: seqRow.height
                                clip: true
                                color: index === root.reelSelected
                                       ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                                                 W.Tokens.accentPrimary.b, 0.22)
                                       : W.Tokens.bgSurface
                                border.width: 1
                                border.color: index === root.reelSelected
                                              ? W.Tokens.accentPrimary : W.Tokens.borderBase

                                // Played fill inside the open clip's block.
                                Rectangle {
                                    visible: seqCell.index === root.reelSelected
                                    anchors { top: parent.top; bottom: parent.bottom; left: parent.left }
                                    anchors.margins: 1
                                    width: {
                                        var d = root.selClipOutSecs - root.selClipInSecs
                                        if (d <= 0) return 0
                                        var f = Math.max(0, Math.min(1,
                                            (root.reelElapsed - root.selClipStartGlobal) / d))
                                        return f * (seqCell.width - 2)
                                    }
                                    color: Qt.rgba(W.Tokens.accentMonitor.r, W.Tokens.accentMonitor.g,
                                                   W.Tokens.accentMonitor.b, 0.18)
                                }
                                Column {
                                    anchors.fill: parent; anchors.margins: 5; spacing: 2; clip: true
                                    Text { width: parent.width; elide: Text.ElideRight
                                           text: (seqCell.index + 1) + ". " + seqCell.modelData.fileName
                                           color: W.Tokens.textPrimary; font.family: W.Tokens.mono
                                           font.pixelSize: 10; font.weight: Font.DemiBold }
                                    Text { text: root.fmtSecs(seqCell.modelData.trimmedDuration)
                                           color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 10 }
                                }
                                // Boundary divider on the right edge.
                                Rectangle {
                                    anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                                    width: 1; color: W.Tokens.bgBase
                                    visible: seqCell.index < EditorBridge.count - 1
                                }
                                // Tap a block to open it; tap the open block to seek within it.
                                TapHandler {
                                    id: seqTap
                                    onTapped: {
                                        if (root.reelSelected !== seqCell.index) {
                                            root.loadReelClip(seqCell.modelData, seqCell.index)
                                        } else if (player.duration > 0) {
                                            var lf = Math.max(0, Math.min(1, seqTap.point.position.x / seqCell.width))
                                            player.position = (seqCell.modelData.inPoint
                                                + lf * seqCell.modelData.trimmedDuration) * 1000
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // Global playhead across the entire reel.
                    Rectangle {
                        visible: EditorBridge.totalDuration > 0
                        anchors { top: parent.top; bottom: parent.bottom }
                        x: Math.max(0, Math.min(1, root.reelElapsed / EditorBridge.totalDuration))
                           * trackBg.width - 1
                        width: 2; color: "#FFFFFF"
                        Rectangle { anchors.centerIn: parent; width: 6; height: parent.height
                                    color: Qt.rgba(255, 255, 255, 0.15) }
                        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top
                                    anchors.topMargin: -6; width: 12; height: 12; color: "#FFFFFF"
                                    radius: 3; rotation: 45
                                    border.color: Qt.rgba(0, 0, 0, 0.5); border.width: 1 }
                    }
                }
            }
            }
        }

        // ── Reel de evidencia (R-1) — clips añadidos, reordenables ─────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 98
            Layout.leftMargin: 18; Layout.rightMargin: 18; Layout.topMargin: 8
            color: W.Tokens.bgElevated
            border.color: W.Tokens.borderBase; border.width: 1
            radius: W.Tokens.rSm

            ColumnLayout {
                anchors.fill: parent; anchors.margins: 8; spacing: 6

                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    Text { text: "REEL DE EVIDENCIA"
                           color: W.Tokens.accentMonitor; font.family: W.Tokens.mono
                           font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.4 }
                    Text { text: EditorBridge.count + " clip(s) · " + root.fmtSecs(EditorBridge.totalDuration)
                           color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 11 }
                    Item { Layout.fillWidth: true }
                    Text {
                        visible: root.exportMsg !== ""
                        text: root.exporting ? ("Exportando… " + root.exportPct + "%") : root.exportMsg
                        color: root.exporting ? W.Tokens.accentPrimary : W.Tokens.textMuted
                        font.family: W.Tokens.mono; font.pixelSize: 11
                        elide: Text.ElideRight; Layout.maximumWidth: 220
                    }
                    Rectangle {
                        Layout.preferredHeight: 24
                        Layout.preferredWidth: exLbl.implicitWidth + 22
                        radius: W.Tokens.rXs
                        enabled: EditorBridge.count > 0 && !root.exporting
                        opacity: enabled ? 1 : 0.4
                        color: exHov.hovered && enabled
                               ? Qt.lighter(W.Tokens.accentPrimary, 1.1) : W.Tokens.accentPrimary
                        HoverHandler { id: exHov }
                        TapHandler { onTapped: if (parent.enabled) EditorBridge.exportReel() }
                        Text { id: exLbl; anchors.centerIn: parent; text: "⏏ EXPORTAR REEL"
                               color: W.Tokens.bgBase; font.family: W.Tokens.sans
                               font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.4 }
                    }
                }

                Item {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Text {
                        anchors.centerIn: parent
                        visible: EditorBridge.count === 0
                        text: "Carga un clip y pulsa ＋ para añadirlo al reel"
                        color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 12
                    }
                    ListView {
                        anchors.fill: parent
                        orientation: ListView.Horizontal
                        spacing: 6; clip: true
                        model: EditorBridge.clips
                        visible: EditorBridge.count > 0
                        delegate: Rectangle {
                            id: reelCell
                            required property var modelData
                            required property int index
                            width: Math.max(84, (EditorBridge.totalDuration > 0
                                   ? modelData.trimmedDuration / EditorBridge.totalDuration : 0) * 360)
                            height: ListView.view.height
                            radius: W.Tokens.rXs
                            color: root.reelSelected === index
                                   ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                                             W.Tokens.accentPrimary.b, 0.18)
                                   : W.Tokens.bgSurface
                            border.color: root.reelSelected === index
                                          ? W.Tokens.accentPrimary : W.Tokens.borderBase
                            border.width: 1
                            TapHandler { onTapped: root.loadReelClip(reelCell.modelData, reelCell.index) }

                            ColumnLayout {
                                anchors.fill: parent; anchors.margins: 6; spacing: 2
                                Text { Layout.fillWidth: true
                                       text: (reelCell.index + 1) + ". " + reelCell.modelData.fileName
                                       color: W.Tokens.textPrimary; font.family: W.Tokens.mono
                                       font.pixelSize: 11; elide: Text.ElideRight }
                                Item { Layout.fillHeight: true }
                                Text { text: root.fmtSecs(reelCell.modelData.trimmedDuration)
                                       color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 10 }
                            }
                            Row {
                                anchors { top: parent.top; right: parent.right; margins: 3 }
                                spacing: 2
                                ReelMini { glyph: "‹"
                                    onActivated: { EditorBridge.moveClip(reelCell.index, reelCell.index - 1)
                                                   root.reelSelected = Math.max(0, reelCell.index - 1) } }
                                ReelMini { glyph: "›"
                                    onActivated: { EditorBridge.moveClip(reelCell.index, reelCell.index + 1)
                                                   root.reelSelected = reelCell.index + 1 } }
                                ReelMini { glyph: "✕"; danger: true
                                    onActivated: { EditorBridge.removeClip(reelCell.index); root.reelSelected = -1 } }
                            }
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

    // Export status feedback from EditorBridge (global context property).
    Connections {
        target: EditorBridge
        function onExportProgress(f) { root.exporting = true; root.exportPct = Math.round(f * 100) }
        function onExportFinished(p) { root.exporting = false; root.exportPct = 100; root.exportMsg = "✓ Exportado" }
        function onExportFailed(m)   { root.exporting = false; root.exportMsg = "✗ " + m }
        function onLoadNotice(m)     { root.exporting = false; root.exportMsg = m }
        // Trims/reorders change clip durations → keep the open clip's global
        // offset and the sequence layout in sync.
        function onTimelineChanged()  { root._recomputeSelGlobals() }
    }

    // When a clip is loaded by anything other than a reel selection (NAS
    // "Cargar para editar", the file dialog, clearing), drop the reel selection
    // so subsequent mark edits don't silently re-trim an unrelated reel clip.
    Connections {
        target: AppBridge
        function onCurrentClipPathChanged() {
            if (!root._openingReel) root.reelSelected = -1
        }
    }

    // Lossless fullscreen review window (R-4, ADR-0003).
    W.FullscreenPlayer {
        id: fsPlayer
        sharedPlayer: player
        inlineOutput: videoOut
    }

    // ── Local component: tiny reel cell button ────────────────────────────
    component ReelMini : Rectangle {
        id: mini
        property string glyph: ""
        property bool   danger: false
        signal activated()
        width: 16; height: 16; radius: 3
        color: mh.hovered
               ? (mini.danger ? Qt.rgba(W.Tokens.accentRecord.r, W.Tokens.accentRecord.g,
                                        W.Tokens.accentRecord.b, 0.30)
                              : Qt.rgba(1, 1, 1, 0.12))
               : Qt.rgba(0, 0, 0, 0.35)
        HoverHandler { id: mh }
        TapHandler   { onTapped: mini.activated() }
        Text {
            anchors.centerIn: parent; text: mini.glyph
            color: mini.danger ? W.Tokens.accentRecord : W.Tokens.textMuted
            font.pixelSize: 11; font.weight: Font.Bold
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
