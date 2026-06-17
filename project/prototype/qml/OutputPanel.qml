import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// OutputPanel.qml — OneDrive delivery + share link panel.
//
//   States (saveState property): "idle" | "uploading" | "done" | "linked" | "error"
//
//   Signals:
//     saveRequested()     user clicked "Guardar en OneDrive"
//     linkRequested()     user clicked "Generar enlace compartido"
//     linkCopied()        user clicked "Copiar"
//
//   The panel owns its uploading→done progress animation locally.

Rectangle {
    id: root

    property string saveState: "idle"
    property string filename: "op-28_auth-error_2026-06-09_14-02.mp4"
    property string destFolder: "SLC / clips-supervisor / 2026-06"
    property string shareLink:
        "https://sigslc-my.sharepoint.com/:v:/g/personal/it/EVm9pK1lQ7Z…op28-auth"

    signal saveRequested()
    signal linkRequested()
    signal linkCopied()

    color: W.Tokens.bgBase

    // brand tints
    readonly property color cloudBlue: "#60A5FA"
    readonly property color nasTeal:   "#22D3EE"

    // local progress 0..100
    property int progress: 0
    property bool copied: false

    // ── Drive progress when uploading ─────────────────────────────────────
    Timer {
        id: progressTimer
        interval: 24       // ~24ms × 100 ≈ 2.4s, like the React version
        repeat: true
        running: false
        onTriggered: {
            if (root.progress >= 100) {
                progressTimer.stop()
                root.saveState = "done"
            } else {
                root.progress += 1
            }
        }
    }

    onSaveStateChanged: {
        if (saveState === "uploading") { progress = 0; progressTimer.start() }
        else if (saveState === "idle" || saveState === "error") { progressTimer.stop(); progress = 0 }
        else if (saveState === "done" || saveState === "linked") { progress = 100 }
    }

    Timer {
        id: copyResetTimer
        interval: 2000; repeat: false
        onTriggered: root.copied = false
    }

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
                Text { text: "☁"; color: root.cloudBlue; font.pixelSize: 14 }
                Text { text: "ONEDRIVE · ENTREGA"
                       color: root.cloudBlue
                       font.family: W.Tokens.mono
                       font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                Item { Layout.fillWidth: true }
                Rectangle { width: 5; height: 5; radius: 3
                            color: W.Tokens.accentOk
                            Layout.alignment: Qt.AlignVCenter }
                Text { text: "SYNC"
                       color: W.Tokens.accentOk
                       font.family: W.Tokens.mono
                       font.pixelSize: 9; font.letterSpacing: 0.8 }
            }
        }

        // ── Body (scrollable) ─────────────────────────────────────────
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: parent.width - 36
                x: 18
                spacing: 16

                Item { height: 4 }

                // ── Filename ──────────────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "NOMBRE DE ARCHIVO"
                           color: W.Tokens.textMuted
                           font.family: W.Tokens.mono
                           font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 32
                        radius: W.Tokens.rXs
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase; border.width: 1
                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                            spacing: 8
                            Text { text: "▦"; color: W.Tokens.accentMonitor
                                   font.pixelSize: 11 }
                            Text {
                                Layout.fillWidth: true
                                elide: Text.ElideMiddle
                                text: root.filename
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 11
                            }
                        }
                    }
                }

                // ── Destination ───────────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Text { text: "CARPETA EN ONEDRIVE"
                           color: W.Tokens.textMuted
                           font.family: W.Tokens.mono
                           font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 32
                        radius: W.Tokens.rXs
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase; border.width: 1
                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                            spacing: 8
                            Text { text: "▤"; color: root.cloudBlue
                                   font.pixelSize: 11 }
                            Text {
                                Layout.fillWidth: true
                                text: root.destFolder
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.mono
                                font.pixelSize: 11
                            }
                            Text { text: "▾"; color: W.Tokens.textMuted
                                   font.pixelSize: 10 }
                        }
                    }
                }

                // ── Save section ──────────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    // Save button
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 40
                        radius: W.Tokens.rSm

                        readonly property bool isIdle:      root.saveState === "idle"
                        readonly property bool isUploading: root.saveState === "uploading"
                        readonly property bool isError:     root.saveState === "error"
                        readonly property bool isDone:      root.saveState === "done"
                                                          || root.saveState === "linked"
                        readonly property bool isActionable: isIdle || isError

                        color: isIdle
                               ? (sh.hovered ? Qt.lighter(root.cloudBlue, 1.08)
                                              : root.cloudBlue)
                               : (isError ? Qt.rgba(W.Tokens.accentRecord.r,
                                                    W.Tokens.accentRecord.g,
                                                    W.Tokens.accentRecord.b,
                                                    sh.hovered ? 0.24 : 0.16)
                               : (isDone ? Qt.rgba(W.Tokens.accentOk.r,
                                                   W.Tokens.accentOk.g,
                                                   W.Tokens.accentOk.b, 0.14)
                                         : W.Tokens.bgSurface))
                        border.color: isDone
                                      ? Qt.rgba(W.Tokens.accentOk.r,
                                                W.Tokens.accentOk.g,
                                                W.Tokens.accentOk.b, 0.40)
                                      : (isError ? Qt.rgba(W.Tokens.accentRecord.r,
                                                           W.Tokens.accentRecord.g,
                                                           W.Tokens.accentRecord.b, 0.45)
                                                 : "transparent")
                        border.width: 1
                        opacity: isUploading ? 0.7 : 1
                        Behavior on color   { ColorAnimation  { duration: 120 } }
                        Behavior on opacity { NumberAnimation { duration: 120 } }

                        HoverHandler { id: sh; enabled: parent.isActionable }
                        TapHandler {
                            enabled: parent.isActionable
                            onTapped: root.saveRequested()
                        }

                        RowLayout {
                            anchors.centerIn: parent
                            spacing: 8
                            Text {
                                text: parent.parent.isError ? "↻"
                                      : (parent.parent.isIdle ? "↥" : "↥")
                                color: parent.parent.isIdle ? W.Tokens.bgBase
                                       : (parent.parent.isError ? W.Tokens.accentRecord
                                       : (parent.parent.isDone ? W.Tokens.accentOk
                                                                : W.Tokens.textMuted))
                                font.pixelSize: 13; font.weight: Font.Bold
                            }
                            Text {
                                text: parent.parent.isIdle
                                      ? "Guardar en OneDrive"
                                      : (parent.parent.isError
                                         ? "Reintentar subida"
                                         : (parent.parent.isUploading
                                            ? "Subiendo… " + root.progress + "%"
                                            : "Subida completa"))
                                color: parent.parent.isIdle ? W.Tokens.bgBase
                                       : (parent.parent.isError ? W.Tokens.accentRecord
                                       : (parent.parent.isDone ? W.Tokens.accentOk
                                                                : W.Tokens.textMuted))
                                font.family: W.Tokens.sans
                                font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 0.4
                            }
                        }
                    }

                    // Error message row (upload failed)
                    RowLayout {
                        visible: root.saveState === "error"
                        Layout.fillWidth: true
                        spacing: 6
                        Rectangle { width: 5; height: 5; radius: 3
                                    color: W.Tokens.accentRecord
                                    Layout.alignment: Qt.AlignVCenter }
                        Text {
                            Layout.fillWidth: true
                            text: "No se pudo subir a OneDrive · reintentar"
                            color: W.Tokens.accentRecord
                            font.family: W.Tokens.mono
                            font.pixelSize: 9; font.letterSpacing: 0.6
                            wrapMode: Text.WordWrap
                        }
                    }

                    // Progress bar (uploading + done)
                    ColumnLayout {
                        visible: root.saveState === "uploading"
                                  || root.saveState === "done"
                                  || root.saveState === "linked"
                        Layout.fillWidth: true
                        spacing: 5

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 5
                            radius: 3
                            color: W.Tokens.bgSurface
                            border.color: W.Tokens.borderBase; border.width: 1
                            clip: true

                            Rectangle {
                                height: parent.height
                                width: parent.width * (root.progress / 100)
                                radius: parent.radius
                                gradient: Gradient {
                                    orientation: Gradient.Horizontal
                                    GradientStop {
                                        position: 0.0
                                        color: root.saveState === "uploading"
                                               ? root.cloudBlue
                                               : W.Tokens.accentOk
                                    }
                                    GradientStop {
                                        position: 1.0
                                        color: root.saveState === "uploading"
                                               ? W.Tokens.accentPrimary
                                               : W.Tokens.accentOk
                                    }
                                }
                                Behavior on width { NumberAnimation { duration: 80 } }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            Text {
                                text: root.saveState === "uploading"
                                      ? Math.round(root.progress * 3.42) + " MB / 342 MB"
                                      : "342 MB · cifrado AES-256"
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.mono
                                font.pixelSize: 9; font.letterSpacing: 0.6
                            }
                            Item { Layout.fillWidth: true }
                            Text {
                                text: root.saveState === "uploading"
                                      ? Math.round(root.progress * 1.4) + " MB/s"
                                      : "✓ COMPLETO"
                                color: root.saveState === "uploading"
                                       ? root.cloudBlue : W.Tokens.accentOk
                                font.family: W.Tokens.mono
                                font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 0.6
                            }
                        }
                    }
                }

                // ── Share section ─────────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    readonly property bool ready:
                        root.saveState === "done" || root.saveState === "linked"
                    readonly property bool linked: root.saveState === "linked"

                    RowLayout {
                        Text { text: "⌒"; color: W.Tokens.textMuted; font.pixelSize: 11 }
                        Text { text: "ENLACE COMPARTIDO"
                               color: W.Tokens.textMuted
                               font.family: W.Tokens.mono
                               font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                        Rectangle {
                            visible: parent.parent.linked
                            Layout.preferredHeight: 16
                            Layout.preferredWidth: lkTxt.implicitWidth + 12
                            radius: 3
                            color: Qt.rgba(W.Tokens.accentOk.r,
                                           W.Tokens.accentOk.g,
                                           W.Tokens.accentOk.b, 0.14)
                            border.color: Qt.rgba(W.Tokens.accentOk.r,
                                                  W.Tokens.accentOk.g,
                                                  W.Tokens.accentOk.b, 0.40)
                            border.width: 1
                            Text { id: lkTxt; anchors.centerIn: parent
                                   text: "✓ ACTIVO · 7 DÍAS"
                                   color: W.Tokens.accentOk
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 8; font.weight: Font.Bold; font.letterSpacing: 0.6 }
                        }
                        Item { Layout.fillWidth: true }
                    }

                    // Not ready: dashed empty state
                    Rectangle {
                        visible: !parent.ready
                        Layout.fillWidth: true
                        Layout.preferredHeight: 38
                        radius: W.Tokens.rXs
                        color: W.Tokens.bgSurface
                        border.color: W.Tokens.borderBase; border.width: 1
                        RowLayout {
                            anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                            spacing: 8
                            Text { text: "⌒"; color: W.Tokens.textDim
                                   font.pixelSize: 11 }
                            Text { text: "Disponible tras subir el archivo"
                                   color: W.Tokens.textDim
                                   font.family: W.Tokens.mono
                                   font.pixelSize: 11; font.letterSpacing: 0.4 }
                            Item { Layout.fillWidth: true }
                        }
                    }

                    // Ready but not linked: generate button
                    Rectangle {
                        visible: parent.ready && !parent.linked
                        Layout.fillWidth: true
                        Layout.preferredHeight: 34
                        radius: W.Tokens.rXs + 1
                        color: gh.hovered
                               ? Qt.lighter(W.Tokens.accentPrimary, 1.08)
                               : W.Tokens.accentPrimary
                        Behavior on color { ColorAnimation { duration: 100 } }

                        HoverHandler { id: gh }
                        TapHandler { onTapped: root.linkRequested() }

                        RowLayout {
                            anchors.centerIn: parent
                            spacing: 8
                            Text { text: "⌒"; color: W.Tokens.bgBase
                                   font.pixelSize: 11; font.weight: Font.Bold }
                            Text { text: "Generar enlace compartido"
                                   color: W.Tokens.bgBase
                                   font.family: W.Tokens.sans
                                   font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 0.4 }
                        }
                    }

                    // Linked: show link + copy
                    ColumnLayout {
                        visible: parent.linked
                        Layout.fillWidth: true
                        spacing: 6

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 34
                            radius: W.Tokens.rXs
                            color: W.Tokens.bgSurface
                            border.color: Qt.rgba(0.38, 0.65, 0.98, 0.40)
                            border.width: 1

                            RowLayout {
                                anchors { fill: parent; leftMargin: 10; rightMargin: 8 }
                                spacing: 8
                                Text { text: "⌒"; color: root.cloudBlue
                                       font.pixelSize: 11 }
                                Text {
                                    Layout.fillWidth: true
                                    elide: Text.ElideMiddle
                                    text: root.shareLink
                                    color: W.Tokens.textPrimary
                                    font.family: W.Tokens.mono
                                    font.pixelSize: 10
                                }
                                Rectangle {
                                    Layout.preferredHeight: 22
                                    Layout.preferredWidth: cpRow.implicitWidth + 14
                                    radius: 3
                                    color: root.copied
                                           ? Qt.rgba(W.Tokens.accentOk.r,
                                                     W.Tokens.accentOk.g,
                                                     W.Tokens.accentOk.b, 0.14)
                                           : W.Tokens.bgElevated
                                    border.color: root.copied
                                                  ? Qt.rgba(W.Tokens.accentOk.r,
                                                            W.Tokens.accentOk.g,
                                                            W.Tokens.accentOk.b, 0.40)
                                                  : W.Tokens.borderBase
                                    border.width: 1

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
                                               color: root.copied
                                                      ? W.Tokens.accentOk
                                                      : W.Tokens.textMuted
                                               font.pixelSize: 10 }
                                        Text {
                                            text: root.copied ? "COPIADO" : "COPIAR"
                                            color: root.copied
                                                   ? W.Tokens.accentOk
                                                   : W.Tokens.textMuted
                                            font.family: W.Tokens.mono
                                            font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 0.8
                                        }
                                    }
                                }
                            }
                        }

                        // Permissions + Expiry
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 42
                                radius: W.Tokens.rXs
                                color: W.Tokens.bgSurface
                                border.color: W.Tokens.borderBase; border.width: 1
                                ColumnLayout {
                                    anchors { fill: parent; leftMargin: 10; rightMargin: 10
                                              topMargin: 6; bottomMargin: 6 }
                                    spacing: 2
                                    Text { text: "PERMISO"
                                           color: W.Tokens.textDim
                                           font.family: W.Tokens.mono
                                           font.pixelSize: 9; font.letterSpacing: 0.8 }
                                    Text { text: "Lectura"
                                           color: W.Tokens.textPrimary
                                           font.family: W.Tokens.sans
                                           font.pixelSize: 11; font.weight: Font.DemiBold }
                                }
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 42
                                radius: W.Tokens.rXs
                                color: W.Tokens.bgSurface
                                border.color: W.Tokens.borderBase; border.width: 1
                                ColumnLayout {
                                    anchors { fill: parent; leftMargin: 10; rightMargin: 10
                                              topMargin: 6; bottomMargin: 6 }
                                    spacing: 2
                                    Text { text: "EXPIRA"
                                           color: W.Tokens.textDim
                                           font.family: W.Tokens.mono
                                           font.pixelSize: 9; font.letterSpacing: 0.8 }
                                    Text { text: "16 Jun · 14:30"
                                           color: W.Tokens.textPrimary
                                           font.family: W.Tokens.sans
                                           font.pixelSize: 11; font.weight: Font.DemiBold }
                                }
                            }
                        }

                        // Notify supervisor
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 32
                            Layout.topMargin: 4
                            radius: W.Tokens.rXs + 1
                            color: "transparent"
                            border.color: W.Tokens.borderBase; border.width: 1
                            HoverHandler { id: nh }
                            Rectangle { anchors.fill: parent; radius: parent.radius
                                        color: W.Tokens.textPrimary
                                        opacity: nh.hovered ? 0.04 : 0 }
                            RowLayout {
                                anchors.centerIn: parent
                                spacing: 8
                                Text { text: "🔔"; color: W.Tokens.textPrimary
                                       font.pixelSize: 11 }
                                Text { text: "Notificar a Ana Ramírez"
                                       color: W.Tokens.textPrimary
                                       font.family: W.Tokens.sans
                                       font.pixelSize: 11; font.weight: Font.Medium }
                            }
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1
                            color: W.Tokens.borderBase; Layout.topMargin: 4 }

                // ── Recent activity ───────────────────────────────────
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text { text: "ACTIVIDAD RECIENTE"
                           color: W.Tokens.textMuted
                           font.family: W.Tokens.mono
                           font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.6 }

                    Repeater {
                        model: [
                            { op: "Op-28", sup: "AR", t: "hace 1 min",
                              state: "EDITING", tone: "primary" },
                            { op: "Op-12", sup: "JS", t: "hace 38 min",
                              state: "OK", tone: "ok" },
                            { op: "Op-07", sup: "AR", t: "hace 2 h",
                              state: "OK", tone: "ok" },
                            { op: "Op-44", sup: "LP", t: "ayer 18:22",
                              state: "OK", tone: "ok" },
                        ]
                        delegate: Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 42
                            radius: W.Tokens.rXs
                            readonly property color tone:
                                modelData.tone === "primary" ? W.Tokens.accentPrimary
                                : modelData.tone === "ok"    ? W.Tokens.accentOk
                                                              : W.Tokens.accentYellow
                            color: index === 0
                                   ? Qt.rgba(tone.r, tone.g, tone.b, 0.08)
                                   : W.Tokens.bgSurface
                            border.color: index === 0
                                          ? Qt.rgba(tone.r, tone.g, tone.b, 0.30)
                                          : W.Tokens.borderBase
                            border.width: 1

                            RowLayout {
                                anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                                spacing: 10
                                W.OperatorAvatar {
                                    size: 26
                                    initials: modelData.sup
                                    tone: parent.parent.tone
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1
                                    Text { text: modelData.op
                                           color: W.Tokens.textPrimary
                                           font.family: W.Tokens.mono
                                           font.pixelSize: 11; font.weight: Font.Bold }
                                    Text { text: modelData.t
                                           color: W.Tokens.textMuted
                                           font.family: W.Tokens.mono
                                           font.pixelSize: 9; font.letterSpacing: 0.6 }
                                }
                                Rectangle {
                                    Layout.preferredHeight: 16
                                    Layout.preferredWidth: stTxt.implicitWidth + 12
                                    radius: 3
                                    color: Qt.rgba(parent.parent.tone.r,
                                                   parent.parent.tone.g,
                                                   parent.parent.tone.b, 0.14)
                                    border.color: Qt.rgba(parent.parent.tone.r,
                                                          parent.parent.tone.g,
                                                          parent.parent.tone.b, 0.40)
                                    border.width: 1
                                    Text { id: stTxt; anchors.centerIn: parent
                                           text: modelData.state
                                           color: parent.parent.parent.tone
                                           font.family: W.Tokens.mono
                                           font.pixelSize: 8; font.weight: Font.Bold; font.letterSpacing: 0.6 }
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
