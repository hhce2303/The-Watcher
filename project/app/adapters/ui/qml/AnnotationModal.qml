import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "." as W

// AnnotationModal.qml — Event tagging form shown after pre-roll countdown.
//
//   Properties:
//     active           : bool       — visible flag
//     eventTimecode    : string     — e.g. "00:42:17"
//     presetTags       : var        — array of strings
//
//   Signals:
//     saved(tag, severity, note)    — user confirmed
//     skipped()                     — user clicked "Sin etiqueta"
//
//   Drop in the recording tab anchored fill parent. Open with `open()`.

Rectangle {
    id: root
    anchors.fill: parent
    color: Qt.rgba(W.Tokens.bgBase.r, W.Tokens.bgBase.g, W.Tokens.bgBase.b, 0.88)
    visible: active
    opacity: active ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: W.Tokens.durMed } }
    z: 50

    property bool active: false
    property string eventTimecode: "00:00:00"
    property var presetTags: ["crash", "lag", "auth error",
                              "memory leak", "session drop", "ui glitch"]

    signal saved(string tag, string severity, string note)
    signal skipped()

    function open(tc) {
        if (tc !== undefined) eventTimecode = tc
        tagInput.text = ""
        noteInput.text = ""
        severityGroup.value = "medium"
        active = true
        tagInput.forceActiveFocus()
    }
    function close() { active = false }

    Keys.onEscapePressed: { close(); skipped() }
    focus: active

    // ── Card ─────────────────────────────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: 480
        radius: W.Tokens.rLg
        color: W.Tokens.bgSurface
        border.color: W.Tokens.borderSubtle
        border.width: 1
        height: bodyCol.implicitHeight + headerRow.implicitHeight + footerRow.implicitHeight + 32

        // Header
        Rectangle {
            id: headerRow
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: 50
            color: "transparent"

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: W.Tokens.borderBase
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 20
                spacing: 10

                Rectangle {
                    Layout.preferredWidth: 6
                    Layout.preferredHeight: 6
                    radius: 3
                    color: W.Tokens.accentYellow
                }
                Text {
                    text: "Evento marcado"
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.sans
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: "T+" + root.eventTimecode
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.mono
                    font.pixelSize: 13
                }
            }
        }

        // Body
        ColumnLayout {
            id: bodyCol
            anchors.top: headerRow.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 20
            spacing: 16

            // ── Tag input + preset chips ─────────────
            ColumnLayout {
                spacing: 8
                Text {
                    text: "ETIQUETA"
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.sans
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.4
                }
                Rectangle {
                    Layout.fillWidth: true
                    height: 36
                    color: W.Tokens.bgBase
                    border.color: tagInput.activeFocus
                                  ? W.Tokens.accentPrimary
                                  : W.Tokens.borderBase
                    border.width: 1
                    radius: W.Tokens.rSm
                    Behavior on border.color { ColorAnimation { duration: 120 } }

                    TextField {
                        id: tagInput
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        placeholderText: "ej. crash en checkout"
                        color: W.Tokens.textPrimary
                        placeholderTextColor: W.Tokens.textDim
                        font.family: W.Tokens.sans
                        font.pixelSize: 15
                        background: Item {}
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: root.presetTags
                        delegate: Rectangle {
                            property bool selected: tagInput.text === modelData
                            width: chipTxt.implicitWidth + 20
                            height: 22
                            radius: W.Tokens.rPill
                            color: selected ? W.Tokens.primaryDim : "transparent"
                            border.color: selected
                                          ? W.Tokens.accentPrimary
                                          : W.Tokens.borderBase
                            border.width: 1
                            Behavior on color { ColorAnimation { duration: 120 } }
                            Behavior on border.color { ColorAnimation { duration: 120 } }

                            HoverHandler { id: chipHvr }
                            TapHandler   { onTapped: tagInput.text = modelData }

                            Text {
                                id: chipTxt
                                anchors.centerIn: parent
                                text: modelData
                                color: selected ? W.Tokens.accentPrimary : W.Tokens.textMuted
                                font.family: W.Tokens.sans
                                font.pixelSize: 12
                                font.weight: Font.Medium
                                Behavior on color { ColorAnimation { duration: 120 } }
                            }
                        }
                    }
                }
            }

            // ── Severity ─────────────────────────────
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "SEVERIDAD"
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.sans
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.4
                }

                Rectangle {
                    id: severityGroup
                    property string value: "medium"

                    Layout.fillWidth: true
                    height: 34
                    radius: W.Tokens.rSm
                    color: W.Tokens.bgBase
                    border.color: W.Tokens.borderBase
                    border.width: 1

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 3
                        spacing: 2

                        Repeater {
                            model: [
                                { id: "low",    label: "Baja",  color: W.Tokens.accentOk },
                                { id: "medium", label: "Media", color: W.Tokens.accentYellow },
                                { id: "high",   label: "Alta",  color: W.Tokens.accentRecord }
                            ]
                            delegate: Rectangle {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: W.Tokens.rXs
                                color: severityGroup.value === modelData.id
                                       ? W.Tokens.bgSurface : "transparent"
                                Behavior on color { ColorAnimation { duration: 120 } }

                                HoverHandler { id: sevHvr }
                                TapHandler   { onTapped: severityGroup.value = modelData.id }

                                RowLayout {
                                    anchors.centerIn: parent
                                    spacing: 6
                                    Rectangle {
                                        Layout.preferredWidth: 6
                                        Layout.preferredHeight: 6
                                        radius: 3
                                        color: modelData.color
                                    }
                                    Text {
                                        text: modelData.label
                                        color: severityGroup.value === modelData.id
                                               ? modelData.color
                                               : W.Tokens.textMuted
                                        font.family: W.Tokens.sans
                                        font.pixelSize: 13
                                        font.weight: Font.DemiBold
                                        Behavior on color { ColorAnimation { duration: 120 } }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ── Note ─────────────────────────────────
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: "NOTA (OPCIONAL)"
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.sans
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.4
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 68
                    radius: W.Tokens.rSm
                    color: W.Tokens.bgBase
                    border.color: noteInput.activeFocus
                                  ? W.Tokens.accentPrimary
                                  : W.Tokens.borderBase
                    border.width: 1
                    Behavior on border.color { ColorAnimation { duration: 120 } }

                    TextArea {
                        id: noteInput
                        anchors.fill: parent
                        anchors.margins: 10
                        placeholderText: "Contexto adicional…"
                        color: W.Tokens.textPrimary
                        placeholderTextColor: W.Tokens.textDim
                        font.family: W.Tokens.sans
                        font.pixelSize: 14
                        wrapMode: TextArea.Wrap
                        background: Item {}
                    }
                }
            }

            // ── Clip timing readout ──────────────────
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 36
                radius: W.Tokens.rSm
                color: W.Tokens.bgBase
                border.color: W.Tokens.borderBase
                border.width: 1

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12

                    Text {
                        text: "CLIP FINAL · 4 MIN"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.mono
                        font.pixelSize: 12
                        font.letterSpacing: 0.8
                    }
                    Item { Layout.fillWidth: true }

                    RowLayout {
                        spacing: 8
                        Text {
                            text: "−2:00 pre"
                            color: W.Tokens.accentPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 12
                        }
                        Text { text: "│"; color: W.Tokens.borderSubtle; font.pixelSize: 12 }
                        Text {
                            text: "● EVENT"
                            color: W.Tokens.accentRecord
                            font.family: W.Tokens.mono
                            font.pixelSize: 12
                            font.weight: Font.Bold
                        }
                        Text { text: "│"; color: W.Tokens.borderSubtle; font.pixelSize: 12 }
                        Text {
                            text: "+2:00 post"
                            color: W.Tokens.accentPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }

        // Footer actions
        Rectangle {
            id: footerRow
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: 56
            color: "transparent"

            Rectangle {
                anchors.top: parent.top
                width: parent.width
                height: 1
                color: W.Tokens.borderBase
            }

            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8

                Item { Layout.fillWidth: true }

                // Skip
                Rectangle {
                    Layout.preferredHeight: 32
                    Layout.preferredWidth: skipTxt.implicitWidth + 32
                    radius: W.Tokens.rSm
                    color: skipHvr.hovered ? Qt.rgba(1,1,1,0.04) : "transparent"
                    border.color: W.Tokens.borderBase
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 120 } }

                    HoverHandler { id: skipHvr }
                    TapHandler   {
                        onTapped: { root.close(); root.skipped() }
                    }

                    Text {
                        id: skipTxt
                        anchors.centerIn: parent
                        text: "Sin etiqueta"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.sans
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                }

                // Save
                Rectangle {
                    Layout.preferredHeight: 32
                    Layout.preferredWidth: saveTxt.implicitWidth + 44
                    radius: W.Tokens.rSm
                    color: saveHvr.hovered
                           ? Qt.darker(W.Tokens.accentPrimary, 1.05)
                           : W.Tokens.accentPrimary
                    Behavior on color { ColorAnimation { duration: 120 } }

                    HoverHandler { id: saveHvr }
                    TapHandler   {
                        onTapped: {
                            var t = tagInput.text.trim()
                            if (t.length === 0) t = "sin etiqueta"
                            root.close()
                            root.saved(t, severityGroup.value, noteInput.text)
                        }
                    }

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: 8
                        Text {
                            id: saveTxt
                            text: "Guardar evento"
                            color: W.Tokens.bgBase
                            font.family: W.Tokens.sans
                            font.pixelSize: 13
                            font.weight: Font.Bold
                            font.letterSpacing: 0.5
                        }
                        Rectangle {
                            Layout.preferredWidth: enterTxt.implicitWidth + 10
                            Layout.preferredHeight: 14
                            radius: 2
                            color: Qt.rgba(W.Tokens.bgBase.r,
                                           W.Tokens.bgBase.g,
                                           W.Tokens.bgBase.b, 0.20)
                            Text {
                                id: enterTxt
                                anchors.centerIn: parent
                                text: "↵"
                                color: W.Tokens.bgBase
                                font.family: W.Tokens.mono
                                font.pixelSize: 11
                            }
                        }
                    }
                }
            }
        }
    }
}
