import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "." as W

// WindowControls.qml — custom minimize / maximize-restore / close cluster.
//
// The app runs as a frameless fullscreen Window (no OS title bar), so these
// are in-app buttons. Close HIDES to the tray (recording + WS server keep
// running); real quit is the tray "Exit" action. The Operator role gets NO
// controls — its monitoring window is intentionally indestructible.
//
//   role : "" | "operator" | "supervisor" | "it"

RowLayout {
    id: rootC
    property string role: ""
    readonly property bool locked: role === "operator"
    spacing: 4
    visible: !locked

    readonly property var win: Window.window
    readonly property bool isFullScreen: win ? (win.visibility === Window.FullScreen) : true

    component WinBtn : Rectangle {
        id: b
        property string glyph: ""
        property bool   danger: false
        property string tip: ""
        signal clicked()
        implicitWidth: 34
        implicitHeight: 26
        radius: W.Tokens.rXs
        color: hov.hovered
               ? (danger ? Qt.rgba(W.Tokens.accentRecord.r, W.Tokens.accentRecord.g, W.Tokens.accentRecord.b, 0.85)
                         : Qt.rgba(1, 1, 1, 0.08))
               : "transparent"
        HoverHandler { id: hov }
        TapHandler { onTapped: b.clicked() }
        ToolTip.visible: hov.hovered && b.tip.length > 0
        ToolTip.text: b.tip
        Text {
            anchors.centerIn: parent
            text: b.glyph
            color: (b.danger && hov.hovered) ? W.Tokens.bgBase : W.Tokens.textMuted
            font.family: W.Tokens.sans
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }

    WinBtn {
        glyph: "—"; tip: "Minimizar"
        onClicked: { if (rootC.win) rootC.win.showMinimized() }
    }
    WinBtn {
        glyph: rootC.isFullScreen ? "❐" : "▢"
        tip: rootC.isFullScreen ? "Restaurar ventana" : "Pantalla completa"
        onClicked: {
            if (!rootC.win) return
            if (rootC.win.visibility === Window.FullScreen) rootC.win.showNormal()
            else rootC.win.showFullScreen()
        }
    }
    WinBtn {
        glyph: "✕"; danger: true; tip: "Cerrar a la bandeja"
        onClicked: { if (rootC.win) rootC.win.hide() }
    }
}
