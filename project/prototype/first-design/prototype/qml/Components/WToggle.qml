import QtQuick
import QtQuick.Layouts
import ".." as W

// WToggle.qml — On/off switch.
//
//   Usage:
//     WToggle { checked: settings.autoStart; onToggled: settings.autoStart = checked }

Rectangle {
    id: root
    property bool checked: false
    signal toggled()

    width: 36
    height: 20
    radius: 10
    color: checked ? W.Tokens.accentPrimary : W.Tokens.borderBase
    Behavior on color { ColorAnimation { duration: 160 } }

    HoverHandler { id: hvr }
    TapHandler   {
        onTapped: {
            root.checked = !root.checked
            root.toggled()
        }
    }

    Rectangle {
        x: root.checked ? 18 : 2
        y: 2
        width: 16
        height: 16
        radius: 8
        color: root.checked ? W.Tokens.bgBase : W.Tokens.textMuted
        Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 160 } }
    }
}
