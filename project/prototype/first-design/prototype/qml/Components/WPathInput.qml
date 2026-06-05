import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import ".." as W

// WPathInput.qml — Filesystem path field with EXAMINAR button.
//
//   Usage:
//     WPathInput {
//         path: settings.segPath
//         onBrowse: fileDialog.open()
//         onPathChanged: settings.segPath = path
//     }

Rectangle {
    id: root
    property string path: ""
    signal browse()

    height: 32
    radius: W.Tokens.rSm
    color: W.Tokens.bgBase
    border.color: pathField.activeFocus
                  ? W.Tokens.accentPrimary
                  : W.Tokens.borderBase
    border.width: 1
    Behavior on border.color { ColorAnimation { duration: 120 } }
    clip: true

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Text {
            Layout.leftMargin: 10
            text: "📁"
            color: W.Tokens.textMuted
            font.pixelSize: 11
        }

        TextField {
            id: pathField
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 6
            text: root.path
            color: W.Tokens.textPrimary
            font.family: W.Tokens.mono
            font.pixelSize: 11
            background: Item {}
            onTextEdited: root.path = text
        }

        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: browseTxt.implicitWidth + 24
            color: browseHvr.hovered
                   ? Qt.lighter(W.Tokens.bgElevated, 1.15)
                   : W.Tokens.bgElevated
            Behavior on color { ColorAnimation { duration: 100 } }

            Rectangle {
                anchors.left: parent.left
                width: 1
                height: parent.height
                color: W.Tokens.borderBase
            }

            HoverHandler { id: browseHvr }
            TapHandler   { onTapped: root.browse() }

            Text {
                id: browseTxt
                anchors.centerIn: parent
                text: "EXAMINAR"
                color: W.Tokens.textMuted
                font.family: W.Tokens.sans
                font.pixelSize: 10
                font.weight: Font.DemiBold
                font.letterSpacing: 1.0
            }
        }
    }
}
