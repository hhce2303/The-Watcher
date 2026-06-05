import QtQuick
import QtQuick.Controls
import "." as W

// TextInput.qml — small wrapper around TextField that matches the dark
// surface/border tokens used across the app. Single-line; emits valueEdited
// when the user changes the text.
//
//   Properties:
//     value : string
//   Signals:
//     valueEdited(string v)

Rectangle {
    id: root
    property string value: ""
    signal valueEdited(string v)

    implicitHeight: 36
    radius: W.Tokens.rXs + 1
    color: W.Tokens.bgSurface
    border.color: input.activeFocus ? W.Tokens.accentPrimary : W.Tokens.borderBase
    border.width: 1
    Behavior on border.color { ColorAnimation { duration: 120 } }

    TextField {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        text: root.value
        onTextChanged: if (text !== root.value) root.valueEdited(text)
        color: W.Tokens.textPrimary
        placeholderTextColor: W.Tokens.textDim
        font.family: W.Tokens.mono
        font.pixelSize: 12
        font.weight: Font.DemiBold
        selectByMouse: true
        background: Rectangle { color: "transparent" }
        verticalAlignment: TextInput.AlignVCenter
    }
}
