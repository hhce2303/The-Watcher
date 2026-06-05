import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import ".." as W

// WDropdown.qml — Native ComboBox styled with Watcher tokens.
//
//   Usage:
//     WDropdown {
//         model: ["nvenc", "qsv", "amf", "x264"]
//         currentValue: settings.encoder
//         onActivated: settings.encoder = currentValue
//     }

ComboBox {
    id: root
    property int boxWidth: 220
    width: boxWidth
    height: 32

    font.family: W.Tokens.sans
    font.pixelSize: 12
    font.weight: Font.Medium

    background: Rectangle {
        color: W.Tokens.bgBase
        border.color: root.activeFocus
                      ? W.Tokens.accentPrimary
                      : W.Tokens.borderBase
        border.width: 1
        radius: W.Tokens.rSm
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    contentItem: Text {
        leftPadding: 12
        rightPadding: 28
        text: root.displayText
        color: W.Tokens.textPrimary
        font: root.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: root.width - width - 10
        y: (root.height - height) / 2
        text: "▼"
        color: W.Tokens.textMuted
        font.family: W.Tokens.mono
        font.pixelSize: 9
    }

    popup: Popup {
        y: root.height + 4
        width: root.width
        padding: 4

        background: Rectangle {
            color: W.Tokens.bgSurface
            border.color: W.Tokens.borderBase
            border.width: 1
            radius: W.Tokens.rSm
        }

        contentItem: ListView {
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
        }
    }

    delegate: ItemDelegate {
        width: root.width - 8
        height: 28

        background: Rectangle {
            color: hovered ? Qt.rgba(1,1,1,0.05) : "transparent"
            radius: W.Tokens.rXs
        }

        contentItem: Text {
            text: modelData
            color: W.Tokens.textPrimary
            font.family: W.Tokens.sans
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            leftPadding: 8
        }
    }
}
