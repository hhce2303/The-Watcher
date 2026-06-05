import QtQuick
import QtQuick.Layouts
import ".." as W

// WSettingsRow.qml — Standard form row: label + helper text on the left,
// control slot on the right. Use as a delegate for forms.
//
//   Usage:
//     WSettingsRow {
//         label: "Bitrate"
//         helper: "Calidad del video en Mbps."
//         WStepper { value: 6.4; min: 1; max: 50; step: 0.5; unit: "Mbps" }
//     }
//
//   Set vertical: true for full-width controls (e.g. path inputs, tag editors).

Item {
    id: root
    default property alias content: holder.data
    property string label: ""
    property string helper: ""
    property bool vertical: false

    implicitHeight: vertical
        ? labelCol.implicitHeight + holder.implicitHeight + 28
        : Math.max(labelCol.implicitHeight, holder.implicitHeight) + 28

    Layout.fillWidth: true

    ColumnLayout {
        anchors.fill: parent
        spacing: root.vertical ? 10 : 0

        // Top: divider on hover (subtle)
        // Bottom border applied at the bottom

        GridLayout {
            Layout.fillWidth: true
            columns: root.vertical ? 1 : 2
            rowSpacing: 4
            columnSpacing: 24

            ColumnLayout {
                id: labelCol
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: 4

                Text {
                    text: root.label
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.sans
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Text {
                    visible: root.helper !== ""
                    text: root.helper
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.sans
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    Layout.maximumWidth: parent.width
                }
            }

            Item {
                id: holder
                Layout.alignment: root.vertical ? Qt.AlignLeft : Qt.AlignRight | Qt.AlignVCenter
                Layout.fillWidth: root.vertical
                implicitHeight: childrenRect.height
                implicitWidth: childrenRect.width
            }
        }

        Rectangle {                  // bottom divider
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            Layout.topMargin: 10
            color: W.Tokens.borderBase
        }
    }
}
