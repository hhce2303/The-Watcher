import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import ".." as W

// WStepper.qml — Integer/float input with − / + buttons and unit suffix.
//
//   Usage:
//     WStepper {
//         value: 6.4
//         min: 1; max: 50; step: 0.5
//         unit: "Mbps"
//         onValueChanged: settings.bitrate = value
//     }

Rectangle {
    id: root
    property real value: 0
    property real min: 0
    property real max: 9999
    property real step: 1
    property string unit: ""
    property int boxWidth: 110

    width: boxWidth
    height: 32
    radius: W.Tokens.rSm
    color: W.Tokens.bgBase
    border.color: W.Tokens.borderBase
    border.width: 1

    function clamp(v) { return Math.max(min, Math.min(max, v)) }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // −
        Rectangle {
            Layout.preferredWidth: 26
            Layout.fillHeight: true
            color: minusHvr.hovered ? Qt.rgba(1,1,1,0.04) : "transparent"
            Behavior on color { ColorAnimation { duration: 80 } }

            HoverHandler { id: minusHvr }
            TapHandler   {
                onTapped: root.value = root.clamp(root.value - root.step)
            }

            Text {
                anchors.centerIn: parent
                text: "−"
                color: W.Tokens.textMuted
                font.family: W.Tokens.sans
                font.pixelSize: 14
            }
        }

        TextField {
            id: valueField
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: root.value
            color: W.Tokens.textPrimary
            font.family: W.Tokens.mono
            font.pixelSize: 12
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            background: Item {}
            onEditingFinished: {
                var n = Number(text)
                if (!isNaN(n)) root.value = root.clamp(n)
                else text = root.value
            }
        }

        Text {
            visible: root.unit !== ""
            Layout.rightMargin: 6
            text: root.unit
            color: W.Tokens.textMuted
            font.family: W.Tokens.mono
            font.pixelSize: 9
            font.letterSpacing: 0.6
        }

        // +
        Rectangle {
            Layout.preferredWidth: 26
            Layout.fillHeight: true
            color: plusHvr.hovered ? Qt.rgba(1,1,1,0.04) : "transparent"
            Behavior on color { ColorAnimation { duration: 80 } }

            HoverHandler { id: plusHvr }
            TapHandler   {
                onTapped: root.value = root.clamp(root.value + root.step)
            }

            Text {
                anchors.centerIn: parent
                text: "+"
                color: W.Tokens.textMuted
                font.family: W.Tokens.sans
                font.pixelSize: 14
            }
        }
    }
}
