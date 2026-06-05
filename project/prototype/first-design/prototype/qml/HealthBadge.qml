import QtQuick
import QtQuick.Layouts
import "." as W

// HealthBadge.qml — Small instrument readout (CPU, DISK, FPS) used in the
// titlebar. Compose three of these horizontally.

Item {
    id: root
    property string label: ""
    property string value: ""
    property color valueColor: W.Tokens.textPrimary

    implicitHeight: 18
    implicitWidth: row.implicitWidth

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: 6

        Text {
            text: root.label
            color: W.Tokens.textMuted
            font.family: W.Tokens.mono
            font.pixelSize: 9
            font.weight: Font.DemiBold
            font.letterSpacing: 1.2
        }
        Text {
            text: root.value
            color: root.valueColor
            font.family: W.Tokens.mono
            font.pixelSize: 10
            font.weight: Font.DemiBold
        }
    }
}
