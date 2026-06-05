import QtQuick
import QtQuick.Layouts
import ".." as W

// WSeg.qml — Segmented radio (2-4 options).
//
//   Usage:
//     WSeg {
//         model: ["compact", "regular", "comfy"]
//         currentValue: settings.density
//         onSelected: settings.density = value
//     }
//
//   Or with label/value pairs:
//     model: [{ value: 30, label: "30" }, { value: 60, label: "60" }]

Rectangle {
    id: root
    property var model: []
    property var currentValue: ""

    signal selected(var value)

    implicitHeight: 32
    implicitWidth: row.implicitWidth + 6
    radius: W.Tokens.rSm
    color: W.Tokens.bgBase
    border.color: W.Tokens.borderBase
    border.width: 1

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 3
        spacing: 2

        Repeater {
            model: root.model
            delegate: Rectangle {
                property var itemValue: typeof modelData === "object" ? modelData.value : modelData
                property string itemLabel: typeof modelData === "object" ? modelData.label : modelData
                property bool active: root.currentValue === itemValue

                Layout.fillHeight: true
                Layout.preferredWidth: segTxt.implicitWidth + 24
                radius: W.Tokens.rXs
                color: active ? W.Tokens.bgSurface : "transparent"
                Behavior on color { ColorAnimation { duration: 120 } }

                HoverHandler { id: segHvr }
                TapHandler   {
                    onTapped: {
                        root.currentValue = itemValue
                        root.selected(itemValue)
                    }
                }

                Text {
                    id: segTxt
                    anchors.centerIn: parent
                    text: itemLabel
                    color: active ? W.Tokens.textPrimary : W.Tokens.textMuted
                    font.family: W.Tokens.sans
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
            }
        }
    }
}
