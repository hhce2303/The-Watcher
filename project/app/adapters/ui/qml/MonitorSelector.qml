import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// MonitorSelector.qml — reusable screen-selection list.
//
// Extracted from Main.qml's operator sidebar so the SAME control is used in
// both the operator recording view and the IT editor's "Grabación" tab (DRY —
// one place to fix the toggle/checkbox logic).
//
// Reads AppBridge.monitors (live, role-agnostic — detection runs regardless of
// role) and toggles clip-selection via AppBridge.toggleMonitor(fingerprint).
// Owns its own active-count badge so no ambient root property is required.
//
//   showHeader : bool   show the "PANTALLAS  n/total" header (default true)

ColumnLayout {
    id: msRoot
    spacing: 0

    property bool showHeader: true
    property var  screens: AppBridge.monitors
    readonly property int activeCount: {
        var n = 0
        for (var i = 0; i < screens.length; i++) if (screens[i].active) n++
        return n
    }

    // ── Header ────────────────────────────────────────────────────────
    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 44
        visible: msRoot.showHeader
        color: "transparent"
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }
        RowLayout {
            anchors { fill: parent; leftMargin: 16; rightMargin: 12 }
            Text {
                text: "PANTALLAS"
                color: W.Tokens.textMuted
                font.family: W.Tokens.sans; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.4
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                width: msBadge.implicitWidth + 12; height: 18; radius: W.Tokens.rPill
                color: W.Tokens.primaryDim
                Text {
                    id: msBadge; anchors.centerIn: parent
                    text: msRoot.activeCount + "/" + msRoot.screens.length
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                }
            }
        }
    }

    // ── Screen list ─────────────────────────────────────────────────────
    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: msRoot.screens
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        delegate: Rectangle {
            width: ListView.view.width
            height: 58
            color: modelData.active ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.06) : "transparent"
            Behavior on color { ColorAnimation { duration: 150 } }

            HoverHandler { id: sh }
            Rectangle {
                anchors.fill: parent; color: W.Tokens.textPrimary
                opacity: sh.hovered ? 0.03 : 0
                Behavior on opacity { NumberAnimation { duration: 100 } }
            }
            TapHandler { onTapped: AppBridge.toggleMonitor(modelData.fingerprint) }

            // Left active bar
            Rectangle {
                width: 3; height: parent.height
                color: modelData.active ? W.Tokens.accentPrimary : "transparent"
                Behavior on color { ColorAnimation { duration: 150 } }
            }
            // Bottom divider
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase; opacity: 0.5 }

            RowLayout {
                anchors { fill: parent; leftMargin: 14; rightMargin: 14 }
                spacing: 10

                // Checkbox
                Rectangle {
                    width: 18; height: 18; radius: 4
                    color: modelData.active ? W.Tokens.accentPrimary : "transparent"
                    border.color: modelData.active ? W.Tokens.accentPrimary : W.Tokens.borderSubtle
                    border.width: 1.5
                    Behavior on color { ColorAnimation { duration: 150 } }
                    Text {
                        anchors.centerIn: parent; text: "✓"
                        color: modelData.active ? W.Tokens.bgBase : "transparent"
                        font.pixelSize: 10; font.weight: Font.Bold
                    }
                }

                // Name + resolution
                Column {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        text: modelData.name
                        color: modelData.active ? W.Tokens.textPrimary : W.Tokens.textMuted
                        font.family: W.Tokens.sans; font.pixelSize: 12; font.weight: Font.Bold
                        Behavior on color { ColorAnimation { duration: 150 } }
                    }
                    Text {
                        text: modelData.res
                        color: W.Tokens.textDim
                        font.family: W.Tokens.mono; font.pixelSize: 10
                    }
                }

                // Index number
                Text {
                    text: String(modelData.idx + 1).padStart(2, "0")
                    color: modelData.active ? W.Tokens.accentMonitor : W.Tokens.borderSubtle
                    font.family: W.Tokens.mono; font.pixelSize: 22; font.weight: Font.Bold
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
            }
        }

        // Empty hint (no monitors detected)
        Text {
            anchors.centerIn: parent
            visible: list.count === 0
            text: "Sin pantallas detectadas"
            color: W.Tokens.textDim; font.family: W.Tokens.mono; font.pixelSize: 12
        }
    }
}
