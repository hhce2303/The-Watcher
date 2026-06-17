import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "." as W

// RoleSetupWizard.qml
//
// Full-screen first-run overlay shown when SettingsBridge.role === "".
// The user selects one of three roles; clicking "Configurar este equipo"
// calls SettingsBridge.setRole() and this overlay becomes invisible.
//
// Parent: Main.qml loads this via a Loader when role is empty.

Item {
    id: root

    // Role data — labels, icons, and descriptions for each role card.
    readonly property var roles: [
        {
            id:    "operator",
            icon:  "📡",
            title: "Operador",
            sub:   "Monitoreo 24/7",
            desc:  "Graba continuamente todas las pantallas asignadas. La ventana permanece siempre activa y la grabación nunca se interrumpe. Sin acceso a ajustes ni clips."
        },
        {
            id:    "supervisor",
            icon:  "🔍",
            title: "Supervisor",
            sub:   "Auditoría y revisión",
            desc:  "Accede al reproductor de clips desde la red o unidad local. No graba. Ideal para estaciones de supervisión o revisión de incidentes."
        },
        {
            id:    "it",
            icon:  "⚙️",
            title: "IT",
            sub:   "Administración completa",
            desc:  "Ajustes completos: encoder, almacenamiento, editor de clips y cambio de rol con PIN. Para el personal técnico responsable del despliegue."
        }
    ]

    property string selectedRole: ""

    // ── Background ────────────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: W.Tokens.bgBase
    }

    // ── Content ───────────────────────────────────────────────────────
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 860)
        spacing: 0

        // Header
        ColumnLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: 48
            spacing: 10

            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "The Watcher"
                color: W.Tokens.accentPrimary
                font.family: W.Tokens.mono
                font.pixelSize: 15
                font.weight: Font.DemiBold
                font.letterSpacing: 2.0
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "Configura este equipo"
                color: W.Tokens.textPrimary
                font.family: W.Tokens.sans
                font.pixelSize: 30
                font.weight: Font.DemiBold
            }
            Text {
                Layout.alignment: Qt.AlignHCenter
                text: "Selecciona el rol de este PC. Esta configuración se guarda localmente y\npuede cambiarse después con el PIN IT."
                color: W.Tokens.textMuted
                font.family: W.Tokens.sans
                font.pixelSize: 15
                horizontalAlignment: Text.AlignHCenter
                lineHeight: 1.5
            }
        }

        // Role cards row
        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            Repeater {
                model: root.roles
                delegate: Rectangle {
                    Layout.fillWidth: true
                    height: 230
                    radius: W.Tokens.rMd
                    property bool selected: root.selectedRole === modelData.id
                    property bool hovered: cardHvr.hovered

                    color: selected
                           ? Qt.rgba(W.Tokens.accentPrimary.r,
                                     W.Tokens.accentPrimary.g,
                                     W.Tokens.accentPrimary.b, 0.10)
                           : (hovered
                              ? Qt.rgba(1,1,1,0.04)
                              : W.Tokens.bgSurface)

                    border.color: selected
                                  ? W.Tokens.accentPrimary
                                  : W.Tokens.borderBase
                    border.width: selected ? 2 : 1

                    Behavior on color       { ColorAnimation { duration: 140 } }
                    Behavior on border.color { ColorAnimation { duration: 140 } }

                    HoverHandler { id: cardHvr }
                    TapHandler   {
                        onTapped: root.selectedRole = modelData.id
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 24
                        spacing: 10

                        Text {
                            text: modelData.icon
                            font.pixelSize: 30
                        }

                        ColumnLayout {
                            spacing: 3
                            Text {
                                text: modelData.title
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.sans
                                font.pixelSize: 18
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: modelData.sub
                                color: W.Tokens.accentPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 12
                                font.letterSpacing: 0.8
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: modelData.desc
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.sans
                            font.pixelSize: 14
                            wrapMode: Text.WordWrap
                            lineHeight: 1.5
                        }

                        Item { Layout.fillHeight: true }
                    }

                    // Selected indicator dot
                    Rectangle {
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: 14
                        width: 10; height: 10; radius: 5
                        color: W.Tokens.accentPrimary
                        visible: parent.selected
                    }
                }
            }
        }

        // Confirm button
        Item { Layout.preferredHeight: 32 }

        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            width: 240; height: 44
            radius: W.Tokens.rSm
            color: root.selectedRole !== ""
                   ? (confirmHvr.hovered
                      ? Qt.rgba(W.Tokens.accentPrimary.r,
                                W.Tokens.accentPrimary.g,
                                W.Tokens.accentPrimary.b, 0.85)
                      : W.Tokens.accentPrimary)
                   : Qt.rgba(1,1,1,0.08)

            Behavior on color { ColorAnimation { duration: 120 } }

            HoverHandler { id: confirmHvr }
            TapHandler {
                enabled: root.selectedRole !== ""
                onTapped: SettingsBridge.setRole(root.selectedRole)
            }

            Text {
                anchors.centerIn: parent
                text: "Configurar este equipo"
                color: root.selectedRole !== ""
                       ? W.Tokens.bgBase
                       : W.Tokens.textDim
                font.family: W.Tokens.sans
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
        }

        Item { Layout.preferredHeight: 20 }
    }
}
