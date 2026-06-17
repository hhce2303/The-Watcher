import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// NASBrowser.qml — file browser for SIG-SLC-Storage NAS.
// Shows breadcrumb, storage stats, file tree with the supervisor's requested
// file pre-expanded and highlighted.
//
// The tree is flattened to a ListModel because recursive components in QML
// are awkward and we know the tree shape ahead of time. Folders track their
// own expanded state via row visibility.
//
//   Properties:
//     selectedPath  : string   currently selected file path
//   Signals:
//     fileSelected(string path, var node)

Rectangle {
    id: root

    property string selectedPath:
        "SIG-SLC-Storage/raw/2026-06-09/operator-28/14-02-11_event.mp4"

    signal fileSelected(string path, var node)

    color: W.Tokens.bgSurface
    border.color: W.Tokens.borderBase
    border.width: 1
    border.color: "transparent"

    // ── Tree data (flat) ──────────────────────────────────────────────────
    // depth | name | kind ("dir"|"file") | path | parent | meta
    ListModel {
        id: rows
        ListElement { depth: 0; name: "SIG-SLC-Storage"; kind: "dir"
                      path: "SIG-SLC-Storage";  parent: "";  expanded: true
                      requested: false; dur: ""; size: ""; mod: "" }

        ListElement { depth: 1; name: "raw"; kind: "dir"
                      path: "SIG-SLC-Storage/raw"
                      parent: "SIG-SLC-Storage"; expanded: true
                      requested: false; dur: ""; size: ""; mod: "" }

        ListElement { depth: 2; name: "2026-06-09"; kind: "dir"
                      path: "SIG-SLC-Storage/raw/2026-06-09"
                      parent: "SIG-SLC-Storage/raw"; expanded: true
                      requested: false; dur: ""; size: ""; mod: "" }

        ListElement { depth: 3; name: "operator-28"; kind: "dir"
                      path: "SIG-SLC-Storage/raw/2026-06-09/operator-28"
                      parent: "SIG-SLC-Storage/raw/2026-06-09"; expanded: true
                      requested: false; dur: ""; size: ""; mod: "" }

        ListElement { depth: 4; name: "13-22-07_event.mp4"; kind: "file"
                      path: "SIG-SLC-Storage/raw/2026-06-09/operator-28/13-22-07_event.mp4"
                      parent: "SIG-SLC-Storage/raw/2026-06-09/operator-28"; expanded: false
                      requested: false; dur: "02:14"; size: "184 MB"; mod: "13:24 hoy" }
        ListElement { depth: 4; name: "13-58-11_event.mp4"; kind: "file"
                      path: "SIG-SLC-Storage/raw/2026-06-09/operator-28/13-58-11_event.mp4"
                      parent: "SIG-SLC-Storage/raw/2026-06-09/operator-28"; expanded: false
                      requested: false; dur: "01:08"; size: "92 MB";  mod: "14:00 hoy" }
        ListElement { depth: 4; name: "14-02-11_event.mp4"; kind: "file"
                      path: "SIG-SLC-Storage/raw/2026-06-09/operator-28/14-02-11_event.mp4"
                      parent: "SIG-SLC-Storage/raw/2026-06-09/operator-28"; expanded: false
                      requested: true;  dur: "16:23"; size: "342 MB"; mod: "14:18 hoy" }

        ListElement { depth: 3; name: "operator-12"; kind: "dir"
                      path: "SIG-SLC-Storage/raw/2026-06-09/operator-12"
                      parent: "SIG-SLC-Storage/raw/2026-06-09"; expanded: false
                      requested: false; dur: ""; size: ""; mod: "" }
        ListElement { depth: 3; name: "operator-07"; kind: "dir"
                      path: "SIG-SLC-Storage/raw/2026-06-09/operator-07"
                      parent: "SIG-SLC-Storage/raw/2026-06-09"; expanded: false
                      requested: false; dur: ""; size: ""; mod: "" }
        ListElement { depth: 3; name: "operator-41"; kind: "dir"
                      path: "SIG-SLC-Storage/raw/2026-06-09/operator-41"
                      parent: "SIG-SLC-Storage/raw/2026-06-09"; expanded: false
                      requested: false; dur: ""; size: ""; mod: "" }

        ListElement { depth: 2; name: "2026-06-08"; kind: "dir"
                      path: "SIG-SLC-Storage/raw/2026-06-08"
                      parent: "SIG-SLC-Storage/raw"; expanded: false
                      requested: false; dur: ""; size: ""; mod: "" }
        ListElement { depth: 2; name: "2026-06-07"; kind: "dir"
                      path: "SIG-SLC-Storage/raw/2026-06-07"
                      parent: "SIG-SLC-Storage/raw"; expanded: false
                      requested: false; dur: ""; size: ""; mod: "" }

        ListElement { depth: 1; name: "processed"; kind: "dir"
                      path: "SIG-SLC-Storage/processed"
                      parent: "SIG-SLC-Storage"; expanded: false
                      requested: false; dur: ""; size: ""; mod: "" }
        ListElement { depth: 1; name: "archive"; kind: "dir"
                      path: "SIG-SLC-Storage/archive"
                      parent: "SIG-SLC-Storage"; expanded: false
                      requested: false; dur: ""; size: ""; mod: "" }
    }

    // O(n) lookup: is this row visible given its ancestor chain?
    function isVisible(idx) {
        var row = rows.get(idx)
        if (row.depth === 0) return true
        // Walk up via parent paths
        var pidx = -1
        for (var i = 0; i < rows.count; i++) {
            if (rows.get(i).path === row.parent) { pidx = i; break }
        }
        if (pidx < 0) return false
        if (!rows.get(pidx).expanded) return false
        return isVisible(pidx)
    }
    function toggle(idx) {
        var row = rows.get(idx)
        if (row.kind !== "dir") return
        rows.setProperty(idx, "expanded", !row.expanded)
    }

    // ── Layout ────────────────────────────────────────────────────────────
    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── Header ────────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: hdrCol.implicitHeight + 22
            color: "transparent"
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: W.Tokens.borderBase }

            ColumnLayout {
                id: hdrCol
                anchors { fill: parent; leftMargin: 16; rightMargin: 16
                          topMargin: 12; bottomMargin: 10 }
                spacing: 10

                RowLayout {
                    spacing: 8
                    Text { text: "▤"; color: "#22D3EE"; font.pixelSize: 15
                           font.weight: Font.Bold }
                    Text { text: "SIG-SLC-STORAGE · NAS"
                           color: "#22D3EE"
                           font.family: W.Tokens.mono
                           font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6 }
                    Item { Layout.fillWidth: true }
                    Rectangle { width: 5; height: 5; radius: 3
                                color: W.Tokens.accentOk
                                Layout.alignment: Qt.AlignVCenter }
                    Text { text: "MONTADO"
                           color: W.Tokens.accentOk
                           font.family: W.Tokens.mono
                           font.pixelSize: 11; font.letterSpacing: 0.8 }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 30
                    radius: W.Tokens.rXs
                    color: W.Tokens.bgBase
                    border.color: searchF.activeFocus ? W.Tokens.accentPrimary
                                                      : W.Tokens.borderBase
                    border.width: 1
                    Behavior on border.color { ColorAnimation { duration: 120 } }
                    RowLayout {
                        anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                        spacing: 8
                        Text { text: "⌕"; color: W.Tokens.textMuted; font.pixelSize: 14 }
                        TextField {
                            id: searchF
                            Layout.fillWidth: true
                            placeholderText: "Buscar archivo…"
                            placeholderTextColor: W.Tokens.textDim
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.sans; font.pixelSize: 13
                            background: Rectangle { color: "transparent" }
                            selectByMouse: true
                        }
                    }
                }
            }
        }

        // ── Storage stats ─────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 42
            color: "transparent"
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: W.Tokens.borderBase }

            ColumnLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 16
                          topMargin: 10; bottomMargin: 10 }
                spacing: 4
                RowLayout {
                    Text { text: "USO"; color: W.Tokens.textMuted
                           font.family: W.Tokens.mono; font.pixelSize: 11
                           font.letterSpacing: 0.8 }
                    Item { Layout.fillWidth: true }
                    Text { text: "4.2 TB / 12 TB"; color: W.Tokens.textPrimary
                           font.family: W.Tokens.mono; font.pixelSize: 11
                           font.weight: Font.DemiBold }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 3
                    radius: 2
                    color: W.Tokens.borderBase
                    Rectangle {
                        height: parent.height; width: parent.width * 0.35
                        radius: parent.radius
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#22D3EE" }
                            GradientStop { position: 1.0; color: W.Tokens.accentPrimary }
                        }
                    }
                }
            }
        }

        // ── Breadcrumb ────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            color: W.Tokens.bgBase
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: W.Tokens.borderBase }

            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                spacing: 4
                Text { text: "SIG-SLC-Storage"; color: W.Tokens.textMuted
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Text { text: "/"; color: W.Tokens.textDim
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Text { text: "raw"; color: W.Tokens.textMuted
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Text { text: "/"; color: W.Tokens.textDim
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Text { text: "2026-06-09"; color: W.Tokens.textMuted
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Text { text: "/"; color: W.Tokens.textDim
                       font.family: W.Tokens.mono; font.pixelSize: 12 }
                Text { text: "operator-28"; color: W.Tokens.textPrimary
                       font.family: W.Tokens.mono; font.pixelSize: 12
                       font.weight: Font.DemiBold }
                Item { Layout.fillWidth: true }
            }
        }

        // ── Tree list ─────────────────────────────────────────────────
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: rows
            spacing: 0
            interactive: true
            boundsBehavior: Flickable.StopAtBounds

            delegate: TreeRow {
                width: list.width
                rowIdx: index
                browserRoot: root
            }
        }

        // ── Footer ────────────────────────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            color: W.Tokens.bgSurface
            Rectangle { anchors.top: parent.top; width: parent.width
                        height: 1; color: W.Tokens.borderBase }
            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 16 }
                spacing: 8
                Text { text: "⌁"; color: W.Tokens.textDim; font.pixelSize: 12 }
                Text { text: "SMB · 10 GbE · 924 MB/s"
                       color: W.Tokens.textDim
                       font.family: W.Tokens.mono
                       font.pixelSize: 11; font.letterSpacing: 0.8 }
                Item { Layout.fillWidth: true }
            }
        }
    }

    // ── Row delegate component ────────────────────────────────────────────
    component TreeRow : Rectangle {
        id: rowR
        property int  rowIdx
        property var  browserRoot

        readonly property var row: rows.get(rowIdx)
        readonly property bool visible_: browserRoot.isVisible(rowIdx)
        readonly property bool isFile: row.kind === "file"
        readonly property bool isSelected: isFile && browserRoot.selectedPath === row.path

        visible: visible_
        height: visible_ ? (isFile ? 38 : 28) : 0
        color: isSelected
               ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                         W.Tokens.accentPrimary.b, 0.18)
               : (row.requested && !isSelected
                  ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                            W.Tokens.accentPrimary.b, 0.06)
                  : (hh.hovered ? Qt.rgba(1,1,1,0.025) : "transparent"))

        Rectangle {
            visible: rowR.isSelected || (rowR.row.requested && !rowR.isSelected)
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 2
            color: rowR.isSelected ? W.Tokens.accentPrimary
                                    : Qt.rgba(W.Tokens.accentPrimary.r,
                                              W.Tokens.accentPrimary.g,
                                              W.Tokens.accentPrimary.b, 0.50)
        }

        HoverHandler { id: hh }
        TapHandler {
            onTapped: {
                if (rowR.isFile) browserRoot.fileSelected(rowR.row.path, rowR.row)
                else             browserRoot.toggle(rowR.rowIdx)
            }
        }

        RowLayout {
            anchors {
                fill: parent
                leftMargin: 16 + rowR.row.depth * 14
                rightMargin: 12
            }
            spacing: 8

            // Chevron (folders only, not root)
            Text {
                text: rowR.row.expanded ? "▾" : "▸"
                color: W.Tokens.textMuted
                font.pixelSize: 11
                visible: !rowR.isFile && rowR.row.depth > 0
                Layout.preferredWidth: 10
            }

            // Icon
            Text {
                text: rowR.isFile ? "▦" : "▤"
                color: rowR.isFile
                       ? (rowR.row.requested ? W.Tokens.accentPrimary
                                              : W.Tokens.textMuted)
                       : (rowR.row.depth === 0 ? "#22D3EE" : W.Tokens.textMuted)
                font.pixelSize: 13
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1
                Text {
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    text: rowR.row.name
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 13
                    font.weight: (rowR.row.depth === 0 || rowR.row.requested)
                                 ? Font.Bold : Font.Medium
                }
                Text {
                    visible: rowR.isFile
                    text: rowR.row.dur + "  ·  " + rowR.row.size
                    color: W.Tokens.textMuted
                    font.family: W.Tokens.mono
                    font.pixelSize: 11
                    font.letterSpacing: 0.4
                }
            }

            // SOLICITADO badge / file count / check
            Rectangle {
                visible: rowR.isFile && rowR.row.requested && !rowR.isSelected
                Layout.preferredHeight: 16
                Layout.preferredWidth: solTxt.implicitWidth + 12
                radius: 3
                color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                               W.Tokens.accentPrimary.b, 0.16)
                border.color: Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g,
                                      W.Tokens.accentPrimary.b, 0.40)
                border.width: 1
                Text {
                    id: solTxt; anchors.centerIn: parent
                    text: "SOLICITADO"
                    color: W.Tokens.accentPrimary
                    font.family: W.Tokens.mono
                    font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 0.6
                }
            }
            Text {
                visible: rowR.isSelected
                text: "✓"
                color: W.Tokens.accentPrimary
                font.pixelSize: 14; font.weight: Font.Bold
            }
        }
    }
}
