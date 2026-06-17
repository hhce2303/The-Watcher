import QtQuick
import QtQuick.Layouts
import "." as W

// Statusbar.qml — Bottom statusbar with recording state, buffer, and system OK.
//
//   Properties:
//     recordSec  : int
//     eventCount : int
//     storagePath: string

Rectangle {
    id: root
    height: 24
    color: W.Tokens.bgElevated
    border.color: W.Tokens.borderBase
    border.width: 0

    Rectangle {                     // top hairline
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: W.Tokens.borderBase
    }

    property int recordSec: 0
    property int eventCount: 0
    property string storagePath: "C:/WatcherData"

    function fmtTime(total) {
        var h = Math.floor(total / 3600)
        var m = Math.floor((total % 3600) / 60)
        var s = total % 60
        return String(h).padStart(2,"0") + ":"
             + String(m).padStart(2,"0") + ":"
             + String(s).padStart(2,"0")
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 14

        // ● GRABANDO 00:42:17
        RowLayout {
            spacing: 6
            Rectangle {
                Layout.preferredWidth: 5
                Layout.preferredHeight: 5
                radius: 3
                color: W.Tokens.accentRecord
            }
            Text {
                text: "GRABANDO"
                color: W.Tokens.accentRecord
                font.family: W.Tokens.mono
                font.pixelSize: 12
                font.weight: Font.DemiBold
                font.letterSpacing: 1.0
            }
            Text {
                text: root.fmtTime(root.recordSec)
                color: W.Tokens.textPrimary
                font.family: W.Tokens.mono
                font.pixelSize: 12
            }
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: W.Tokens.borderBase
        }

        Text {
            text: root.eventCount + " eventos"
            color: W.Tokens.textMuted
            font.family: W.Tokens.mono
            font.pixelSize: 12
        }
        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: W.Tokens.borderBase
        }

        Text {
            text: "buffer 2:00 / 60 seg"
            color: W.Tokens.textMuted
            font.family: W.Tokens.mono
            font.pixelSize: 12
        }
        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: W.Tokens.borderBase
        }

        Text {
            text: root.storagePath
            color: W.Tokens.textMuted
            font.family: W.Tokens.mono
            font.pixelSize: 12
        }

        Item { Layout.fillWidth: true }

        RowLayout {
            spacing: 6
            Rectangle {
                Layout.preferredWidth: 4
                Layout.preferredHeight: 4
                radius: 2
                color: W.Tokens.accentOk
            }
            Text {
                text: "SISTEMA OK"
                color: W.Tokens.accentOk
                font.family: W.Tokens.mono
                font.pixelSize: 12
                font.letterSpacing: 0.8
            }
        }

        Rectangle {
            Layout.preferredWidth: 1
            Layout.preferredHeight: 12
            color: W.Tokens.borderBase
        }

        Text {
            text: "build 2026.05.24"
            color: W.Tokens.textDim
            font.family: W.Tokens.mono
            font.pixelSize: 12
        }
    }
}
