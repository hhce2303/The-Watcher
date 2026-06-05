import QtQuick
import QtQuick.Layouts
import ".." as W

// WHotkey.qml — Visual hotkey display (e.g. ["Ctrl", "1"] → [Ctrl] + [1])
//
//   Properties:
//     keys : var   — array of strings

Item {
    id: root
    property var keys: []

    implicitHeight: 28
    implicitWidth: row.implicitWidth

    HoverHandler { id: hvr }

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: 4

        Repeater {
            model: root.keys.length
            delegate: Item {
                Layout.preferredHeight: 28
                implicitWidth: keyBlock.width + (index < root.keys.length - 1 ? 12 : 0)

                Rectangle {
                    id: keyBlock
                    width: keyTxt.implicitWidth + 16
                    height: 28
                    radius: W.Tokens.rSm
                    color: W.Tokens.bgBase
                    border.color: hvr.hovered
                                  ? W.Tokens.borderSubtle
                                  : W.Tokens.borderBase
                    border.width: 1
                    Behavior on border.color { ColorAnimation { duration: 120 } }

                    Text {
                        id: keyTxt
                        anchors.centerIn: parent
                        text: root.keys[index]
                        color: W.Tokens.textPrimary
                        font.family: W.Tokens.mono
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                }

                Text {
                    anchors.left: keyBlock.right
                    anchors.leftMargin: 4
                    anchors.verticalCenter: keyBlock.verticalCenter
                    visible: index < root.keys.length - 1
                    text: "+"
                    color: W.Tokens.textDim
                    font.pixelSize: 10
                }
            }
        }
    }
}
