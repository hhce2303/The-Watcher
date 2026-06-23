import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// OutputPanel.qml — OneDrive delivery: ensure folder + share link.
//
//   States (saveState): "idle" | "working" | "linked" | "error"
//   Bound by the parent to AppBridge.oneDriveState / oneDriveFolder / oneDriveLink.
//
//   Signals:
//     saveRequested()   user clicked the primary action (ensure folder + link)
//     linkCopied()      user clicked "Copiar"
//
//   One click runs the whole real flow: search the destination folder → create
//   it if missing → produce a share link.  No fake progress, no mock data.

Rectangle {
    id: root

    property string saveState: "idle"
    property string destFolder: ""
    property string shareLink: ""
    property string errorText: ""

    signal saveRequested()
    signal linkCopied()

    color: W.Tokens.bgBase

    readonly property color cloudBlue: "#60A5FA"

    readonly property bool isIdle:       saveState === "idle"
    readonly property bool isWorking:    saveState === "working"
    readonly property bool isLinked:     saveState === "linked"
    readonly property bool isError:      saveState === "error"
    readonly property bool isActionable: isIdle || isError

    property bool copied: false
    Timer { id: copyResetTimer; interval: 2000; onTriggered: root.copied = false }

    Rectangle { anchors.left: parent.left; width: 1; height: parent.height
                color: W.Tokens.borderBase }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Header ────────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            color: "transparent"
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: W.Tokens.borderBase }

            RowLayout {
                anchors { fill: parent; leftMargin: 18; rightMargin: 18 }
                spacing: 8
                Text { text: "☁"; color: root.cloudBlue; font.pixelSize: 16 }
                Text { text: "ONEDRIVE · ENTREGA"
                       color: root.cloudBlue
                       font.family: W.Tokens.mono
                       font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 5; height: 5; radius: 3
                    Layout.alignment: Qt.AlignVCenter
                    color: root.isLinked  ? W.Tokens.accentOk
                         : root.isError   ? W.Tokens.accentRecord
                         : root.isWorking ? root.cloudBlue
                                          : W.Tokens.textDim
                }
                Text {
                    color: root.isLinked  ? W.Tokens.accentOk
                         : root.isError   ? W.Tokens.accentRecord
                         : root.isWorking ? root.cloudBlue
                                          : W.Tokens.textDim
                    font.family: W.Tokens.mono
                    font.pixelSize: 11; font.letterSpacing: 0.8
                    text: root.isLinked  ? "LISTO"
                        : root.isError   ? "ERROR"
                        : root.isWorking ? "PROCESANDO"
                                         : "EN ESPERA"
                }
            }
        }

        // ── Body ──────────────────────────────────────────────────────
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: parent.width - 36
                x: 18
                spacing: 16

                Item { height: 4 }

                // ── Destination folder ────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "CARPETA EN ONEDRIVE"
                           color: W.Tokens.textMuted
                           font.family: W.Tokens.mono
                           font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 32
                        radius: W.Tokens.rXs
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase; border.width: 1
                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                            spacing: 8
                            Text { text: "▤"; color: root.cloudBlue; font.pixelSize: 13 }
                            Text {
                                Layout.fillWidth: true
                                elide: Text.ElideMiddle
                                text: root.destFolder !== ""
                                      ? root.destFolder
                                      : "Se determinará al asegurar la carpeta"
                                color: root.destFolder !== ""
                                       ? W.Tokens.textPrimary : W.Tokens.textDim
                                font.family: W.Tokens.mono
                                font.pixelSize: 13
                            }
                        }
                    }
                }

                // ── Primary action ────────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    radius: W.Tokens.rSm

                    color: root.isIdle
                           ? (ph.hovered ? Qt.lighter(root.cloudBlue, 1.08) : root.cloudBlue)
                           : root.isError
                             ? Qt.rgba(W.Tokens.accentRecord.r, W.Tokens.accentRecord.g,
                                       W.Tokens.accentRecord.b, ph.hovered ? 0.24 : 0.16)
                             : root.isLinked
                               ? Qt.rgba(W.Tokens.accentOk.r, W.Tokens.accentOk.g,
                                         W.Tokens.accentOk.b, 0.14)
                               : W.Tokens.bgSurface
                    border.width: 1
                    border.color: root.isLinked
                                  ? Qt.rgba(W.Tokens.accentOk.r, W.Tokens.accentOk.g,
                                            W.Tokens.accentOk.b, 0.40)
                                  : root.isError
                                    ? Qt.rgba(W.Tokens.accentRecord.r, W.Tokens.accentRecord.g,
                                              W.Tokens.accentRecord.b, 0.45)
                                    : "transparent"
                    opacity: root.isWorking ? 0.7 : 1
                    Behavior on color   { ColorAnimation  { duration: 120 } }
                    Behavior on opacity { NumberAnimation { duration: 120 } }

                    HoverHandler { id: ph; enabled: root.isActionable }
                    TapHandler   { enabled: root.isActionable; onTapped: root.saveRequested() }

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: 8
                        Text {
                            text: root.isError ? "↻" : (root.isLinked ? "✓" : "☁")
                            color: root.isIdle ? W.Tokens.bgBase
                                   : (root.isError ? W.Tokens.accentRecord
                                   : (root.isLinked ? W.Tokens.accentOk : W.Tokens.textMuted))
                            font.pixelSize: 15; font.weight: Font.Bold
                            RotationAnimation on rotation {
                                running: root.isWorking; loops: Animation.Infinite
                                from: 0; to: 360; duration: 900
                            }
                        }
                        Text {
                            text: root.isIdle ? "Asegurar carpeta y enlace"
                                  : (root.isError ? "Reintentar"
                                  : (root.isLinked ? "Enlace listo" : "Procesando…"))
                            color: root.isIdle ? W.Tokens.bgBase
                                   : (root.isError ? W.Tokens.accentRecord
                                   : (root.isLinked ? W.Tokens.accentOk : W.Tokens.textMuted))
                            font.family: W.Tokens.sans
                            font.pixelSize: 14; font.weight: Font.Bold; font.letterSpacing: 0.4
                        }
                    }
                }

                // ── Error message ─────────────────────────────────────
                RowLayout {
                    visible: root.isError
                    Layout.fillWidth: true
                    spacing: 6
                    Rectangle { width: 5; height: 5; radius: 3
                                color: W.Tokens.accentRecord
                                Layout.alignment: Qt.AlignVCenter }
                    Text {
                        Layout.fillWidth: true
                        text: root.errorText !== ""
                              ? root.errorText
                              : "No se pudo asegurar la carpeta · reintentar"
                        color: W.Tokens.accentRecord
                        font.family: W.Tokens.mono
                        font.pixelSize: 11; font.letterSpacing: 0.6
                        wrapMode: Text.WordWrap
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1
                            color: W.Tokens.borderBase }

                // ── Share link ────────────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    RowLayout {
                        Text { text: "⌒"; color: W.Tokens.textMuted; font.pixelSize: 13 }
                        Text { text: "ENLACE COMPARTIDO"
                               color: W.Tokens.textMuted
                               font.family: W.Tokens.mono
                               font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                        Item { Layout.fillWidth: true }
                    }

                    // Not linked → empty / working state
                    Rectangle {
                        visible: !root.isLinked
                        Layout.fillWidth: true
                        Layout.preferredHeight: 38
                        radius: W.Tokens.rXs
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase; border.width: 1
                        RowLayout {
                            anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                            spacing: 8
                            Text { text: "⌒"; color: W.Tokens.textDim; font.pixelSize: 13 }
                            Text { text: root.isWorking
                                         ? "Generando enlace…"
                                         : "El enlace aparecerá aquí"
                                   color: W.Tokens.textDim
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 13; font.letterSpacing: 0.4 }
                            Item { Layout.fillWidth: true }
                        }
                    }

                    // Linked → real link + copy
                    Rectangle {
                        visible: root.isLinked
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        radius: W.Tokens.rXs
                        color: W.Tokens.bgSurface
                        border.color: Qt.rgba(0.38, 0.65, 0.98, 0.40)
                        border.width: 1

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 8 }
                            spacing: 8
                            Text { text: "⌒"; color: root.cloudBlue; font.pixelSize: 13 }
                            Text {
                                Layout.fillWidth: true
                                elide: Text.ElideMiddle
                                text: root.shareLink
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 12
                            }
                            Rectangle {
                                Layout.preferredHeight: 22
                                Layout.preferredWidth: cpRow.implicitWidth + 14
                                radius: 3
                                color: root.copied
                                       ? Qt.rgba(W.Tokens.accentOk.r, W.Tokens.accentOk.g,
                                                 W.Tokens.accentOk.b, 0.14)
                                       : W.Tokens.bgElevated
                                border.width: 1
                                border.color: root.copied
                                              ? Qt.rgba(W.Tokens.accentOk.r, W.Tokens.accentOk.g,
                                                        W.Tokens.accentOk.b, 0.40)
                                              : W.Tokens.borderBase

                                TapHandler {
                                    onTapped: {
                                        root.copied = true
                                        root.linkCopied()
                                        copyResetTimer.restart()
                                    }
                                }

                                RowLayout {
                                    id: cpRow
                                    anchors.centerIn: parent
                                    spacing: 4
                                    Text { text: root.copied ? "✓" : "⎘"
                                           color: root.copied ? W.Tokens.accentOk : W.Tokens.textMuted
                                           font.pixelSize: 12 }
                                    Text { text: root.copied ? "COPIADO" : "COPIAR"
                                           color: root.copied ? W.Tokens.accentOk : W.Tokens.textMuted
                                           font.family: W.Tokens.mono
                                           font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 0.8 }
                                }
                            }
                        }
                    }
                }

                Item { height: 16 }
            }
        }
    }
}
