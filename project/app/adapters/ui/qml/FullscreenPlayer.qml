import QtQuick
import QtQuick.Window
import QtMultimedia
import "." as W

// FullscreenPlayer.qml — lossless fullscreen review (R-4, ADR-0003).
//
// Reuses the editor's single MediaPlayer by reparenting its videoOutput to this
// window's VideoOutput while visible, then restoring it on close. No second
// decode, no quality loss; renders at the monitor's native resolution.
//
//   sharedPlayer : the editor's MediaPlayer
//   inlineOutput : the VideoOutput to restore when closing
Window {
    id: fs

    property var sharedPlayer: null
    property var inlineOutput: null

    visibility: Window.FullScreen
    color: "black"
    title: "The Watcher — Pantalla completa"

    onVisibleChanged: {
        if (fs.sharedPlayer === null)
            return
        if (fs.visible)
            fs.sharedPlayer.videoOutput = fsOut
        else if (fs.inlineOutput !== null)
            fs.sharedPlayer.videoOutput = fs.inlineOutput
    }

    VideoOutput {
        id: fsOut
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectFit
    }

    // Esc / F to exit.
    Item {
        anchors.fill: parent
        focus: true
        Keys.onPressed: function(e) {
            if (e.key === Qt.Key_Escape || e.key === Qt.Key_F)
                fs.close()
        }
    }

    // Exit hint.
    Rectangle {
        anchors { top: parent.top; right: parent.right; margins: 16 }
        width: hintTxt.implicitWidth + 20; height: 28; radius: 6
        color: Qt.rgba(0, 0, 0, 0.6)
        Text {
            id: hintTxt
            anchors.centerIn: parent
            text: "ESC / F · salir"
            color: "#F8FAFC"
            font.family: W.Tokens.mono
            font.pixelSize: 12
        }
    }
}
