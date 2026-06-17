import QtQuick
import QtQuick.Layouts
import "." as W

// OperatorAvatar.qml — small monogram tile used for supervisor + IT user.
// Matches the existing token system: tinted square w/ initials in mono font.
//
//   Properties:
//     initials  : string  (1–3 chars)
//     tone      : color   (defaults to accentPrimary)
//     size      : int     (px square; default 32)

Rectangle {
    id: root

    property string initials: "··"
    property color  tone: W.Tokens.accentPrimary
    property int    size: 32

    implicitWidth: size
    implicitHeight: size
    radius: Math.max(3, Math.round(size / 4))
    color: Qt.rgba(tone.r, tone.g, tone.b, 0.16)
    border.color: Qt.rgba(tone.r, tone.g, tone.b, 0.32)
    border.width: 1

    Text {
        anchors.centerIn: parent
        text: root.initials
        color: root.tone
        font.family: W.Tokens.mono
        font.pixelSize: Math.max(9, Math.round(root.size * 0.34))
        font.weight: Font.Bold
        font.letterSpacing: 0.3
    }
}
