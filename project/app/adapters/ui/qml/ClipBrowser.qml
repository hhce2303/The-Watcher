import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "." as W

// ── ClipBrowser ──────────────────────────────────────────────────────────────
// Network / local file browser for the Clips tab.
//
// Navigation model
// ────────────────
//  navStack  — [{label, path}]  breadcrumb history
//  currentItems — [{name, path, isDir, modified, size, ext}]  directory contents
//  selectedItem — single selected item (or null)
//
// Usage from Main.qml:
//   ClipBrowser { anchors.fill: parent; onPlayRequested: AppBridge.loadClip(path) }
// ─────────────────────────────────────────────────────────────────────────────
Item {
    id: root

    // Emitted when the user activates a video file (double-click or Play button)
    signal playRequested(string path)

    // ── State ─────────────────────────────────────────────────────────
    property var navStack:      []   // [{label:string, path:string}]
    property var currentItems:  []   // QVariantList from AppBridge.listDirectory
    property var selectedItem:  null // one item dict or null

    property string networkRoot: "\\\\SIG-SLC-Storage"
    property string currentPath: navStack.length > 0 ? navStack[navStack.length - 1].path : ""

    // ── Navigation helpers ─────────────────────────────────────────────
    function openPath(label, path) {
        navStack = navStack.concat([{ label: label, path: path }])
        selectedItem = null
        currentItems = AppBridge.listDirectory(path)
    }

    function goBack() {
        if (navStack.length === 0) return
        var ns = navStack.slice(0, navStack.length - 1)
        navStack = ns
        selectedItem = null
        currentItems = ns.length > 0 ? AppBridge.listDirectory(ns[ns.length - 1].path) : []
    }

    function goTocrumb(index) {
        navStack = navStack.slice(0, index + 1)
        selectedItem = null
        currentItems = AppBridge.listDirectory(navStack[navStack.length - 1].path)
    }

    function openRoot() {
        navStack = []
        selectedItem = null
        currentItems = []
    }

    function openItem(item) {
        if (item.isDir) openPath(item.name, item.path)
    }

    // ── Layout ────────────────────────────────────────────────────────
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ──────────────────────────────────────────────────────────────
        // LEFT SIDEBAR  (quick access)
        // ──────────────────────────────────────────────────────────────
        Rectangle {
            Layout.preferredWidth: 210
            Layout.fillHeight: true
            color: W.Tokens.bgSurface
            // right border only
            Rectangle {
                anchors { top: parent.top; bottom: parent.bottom; right: parent.right }
                width: 1; color: W.Tokens.borderBase
            }

            ColumnLayout {
                anchors { fill: parent; topMargin: 16 }
                spacing: 0

                // ── Network section ────────────────────────────────────
                SideLabel { text: "RED" }
                Item { height: 4 }

                SideEntry {
                    icon: "◈"; label: "SIG-SLC-Storage"
                    active: navStack.length > 0 && navStack[0].path === root.networkRoot
                    onActivated: {
                        if (navStack.length === 0 || navStack[0].path !== root.networkRoot) {
                            root.navStack = []
                            root.openPath("SIG-SLC-Storage", root.networkRoot)
                        }
                    }
                }

                Item { height: 20 }

                // Divider
                Rectangle {
                    Layout.fillWidth: true; height: 1
                    color: W.Tokens.borderBase
                    Layout.leftMargin: 14; Layout.rightMargin: 14
                }

                Item { height: 16 }

                // ── Local section ──────────────────────────────────────
                SideLabel { text: "LOCAL" }
                Item { height: 4 }

                SideEntry {
                    icon: "▤"; label: "Clips combinados"
                    active: navStack.length > 0 && navStack[0].path === "LOCAL_CLIPS"
                    onActivated: {
                        root.navStack = []
                        root.openPath("Clips combinados", "LOCAL_CLIPS")
                    }
                }
                SideEntry {
                    icon: "▦"; label: "Clips por pantalla"
                    active: navStack.length > 0 && navStack[0].path === "LOCAL_RAW"
                    onActivated: {
                        root.navStack = []
                        root.openPath("Clips por pantalla", "LOCAL_RAW")
                    }
                }

                Item { Layout.fillHeight: true }

                // ── Selection footer ───────────────────────────────────
                Rectangle {
                    Layout.fillWidth: true; height: 54
                    color: Qt.rgba(0, 0, 0, 0.2)
                    visible: root.selectedItem !== null && !root.selectedItem.isDir
                    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: W.Tokens.borderBase }

                    Column {
                        anchors {
                            left: parent.left; leftMargin: 14
                            right: parent.right; rightMargin: 14
                            verticalCenter: parent.verticalCenter
                        }
                        spacing: 3
                        Text {
                            width: parent.width; elide: Text.ElideRight
                            text: root.selectedItem ? root.selectedItem.name : ""
                            color: W.Tokens.textPrimary
                            font.family: W.Tokens.mono; font.pixelSize: 11
                        }
                        Text {
                            text: root.selectedItem ? root.selectedItem.size : ""
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.mono; font.pixelSize: 10
                        }
                    }
                }
            }
        }

        // ──────────────────────────────────────────────────────────────
        // MAIN PANEL
        // ──────────────────────────────────────────────────────────────
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ── Toolbar / breadcrumb ────────────────────────────────
            Rectangle {
                Layout.fillWidth: true; height: 46
                color: W.Tokens.bgBase
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }

                RowLayout {
                    anchors { left: parent.left; right: parent.right; leftMargin: 10; rightMargin: 10; verticalCenter: parent.verticalCenter }
                    spacing: 6

                    // Back / Up
                    NavBtn {
                        label: "←"
                        enabled: root.navStack.length > 0
                        onActivated: root.goBack()
                    }
                    NavBtn {
                        label: "↑"
                        enabled: root.navStack.length > 1
                        onActivated: root.goTocrumb(root.navStack.length - 2)
                    }

                    // Breadcrumb bar
                    Rectangle {
                        Layout.fillWidth: true; height: 30
                        color: Qt.rgba(0,0,0,0.28); radius: W.Tokens.rXs
                        border.color: W.Tokens.borderBase; border.width: 1
                        clip: true

                        Row {
                            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                            spacing: 0

                            // "Red" root crumb
                            Row {
                                spacing: 0
                                Text {
                                    text: "⊛  Red"
                                    color: root.navStack.length === 0 ? W.Tokens.textPrimary : W.Tokens.accentPrimary
                                    font.family: W.Tokens.sans; font.pixelSize: 12
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.openRoot() }
                                }
                                Text {
                                    visible: root.navStack.length > 0
                                    text: "  ›  "; color: W.Tokens.textDim; font.pixelSize: 12
                                }
                            }

                            Repeater {
                                model: root.navStack
                                delegate: Row {
                                    spacing: 0
                                    property bool isLast: index === root.navStack.length - 1
                                    Text {
                                        text: modelData.label
                                        color: isLast ? W.Tokens.textPrimary : W.Tokens.accentPrimary
                                        font.family: W.Tokens.sans; font.pixelSize: 12
                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: isLast ? Qt.ArrowCursor : Qt.PointingHandCursor
                                            onClicked: if (!isLast) root.goTocrumb(index)
                                        }
                                    }
                                    Text {
                                        visible: !isLast
                                        text: "  ›  "; color: W.Tokens.textDim; font.pixelSize: 12
                                    }
                                }
                            }
                        }
                    }

                    // Reload
                    NavBtn {
                        label: "⟳"
                        enabled: root.navStack.length > 0
                        onActivated: {
                            root.selectedItem = null
                            root.currentItems = AppBridge.listDirectory(root.currentPath)
                        }
                    }
                }
            }

            // ── Column headers ──────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true; height: 28
                color: W.Tokens.bgSurface
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: W.Tokens.borderBase }

                Row {
                    anchors { fill: parent; leftMargin: 42; rightMargin: 16 }

                    ColHdr { text: "NOMBRE";    width: parent.width - 42 - 155 - 84 - 52 }
                    ColHdr { text: "MODIFICADO"; width: 155 }
                    ColHdr { text: "TAMAÑO";    width: 84;  rightAlign: true }
                    ColHdr { text: "TIPO";      width: 52;  rightAlign: true }
                }
            }

            // ── File list ───────────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true
                color: W.Tokens.bgBase; clip: true

                // Empty / welcome state
                Column {
                    anchors.centerIn: parent; spacing: 14
                    visible: root.currentItems.length === 0

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.navStack.length === 0 ? "◈" : "∅"
                        color: Qt.rgba(1,1,1,0.06); font.pixelSize: 56
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.navStack.length === 0
                              ? "Selecciona una ubicación en el panel lateral"
                              : "Esta carpeta está vacía"
                        color: W.Tokens.textMuted
                        font.family: W.Tokens.sans; font.pixelSize: 13
                    }
                }

                ListView {
                    id: fileList
                    anchors.fill: parent
                    model: root.currentItems
                    clip: true; spacing: 0
                    visible: root.currentItems.length > 0

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    delegate: Rectangle {
                        id: rowBg
                        width: ListView.view.width; height: 42
                        property bool sel: root.selectedItem !== null && root.selectedItem.path === modelData.path

                        color: {
                            if (sel) return Qt.rgba(
                                W.Tokens.accentPrimary.r,
                                W.Tokens.accentPrimary.g,
                                W.Tokens.accentPrimary.b, 0.10)
                            if (rowHov.hovered) return Qt.rgba(1,1,1,0.04)
                            return index % 2 === 0 ? "transparent" : Qt.rgba(1,1,1,0.015)
                        }
                        Behavior on color { ColorAnimation { duration: 80 } }

                        HoverHandler { id: rowHov }

                        // Left selection accent
                        Rectangle {
                            width: 3; height: parent.height
                            color: sel ? W.Tokens.accentPrimary : "transparent"
                            Behavior on color { ColorAnimation { duration: 100 } }
                        }

                        // Bottom separator
                        Rectangle {
                            anchors.bottom: parent.bottom; width: parent.width; height: 1
                            color: W.Tokens.borderBase; opacity: 0.4
                        }

                        // Single / double click
                        TapHandler {
                            onTapped:       root.selectedItem = modelData
                            onDoubleTapped: {
                                if (modelData.isDir) {
                                    root.openItem(modelData)
                                } else {
                                    root.selectedItem = modelData
                                    root.playRequested(modelData.path)
                                }
                            }
                        }

                        // Row content
                        Row {
                            anchors { left: parent.left; leftMargin: 14; right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
                            spacing: 0

                            // ── Icon ────────────────────────────────
                            Rectangle {
                                width: 28; height: 28; radius: W.Tokens.rXs
                                color: {
                                    if (!modelData.isDir) return Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.12)
                                    return Qt.rgba(1,1,1,0.05)
                                }
                                Text {
                                    anchors.centerIn: parent
                                    text: modelData.isDir ? "▸" : "▶"
                                    color: modelData.isDir ? W.Tokens.textDim : W.Tokens.accentPrimary
                                    font.pixelSize: modelData.isDir ? 12 : 10
                                }
                            }

                            Item { width: 10 }

                            // ── Name ─────────────────────────────────
                            Text {
                                width: rowBg.width - 42 - 155 - 84 - 52 - 14 - 28 - 10 - 16
                                height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.name
                                color: modelData.isDir ? W.Tokens.textPrimary : W.Tokens.textMuted
                                font.family: W.Tokens.mono
                                font.pixelSize: 12
                                elide: Text.ElideRight
                            }

                            // ── Modified date ────────────────────────
                            Text {
                                width: 155; height: parent.height
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.modified || "—"
                                color: W.Tokens.textDim
                                font.family: W.Tokens.mono; font.pixelSize: 11
                            }

                            // ── Size ─────────────────────────────────
                            Text {
                                width: 84; height: parent.height
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.isDir ? "—" : (modelData.size || "—")
                                color: W.Tokens.textDim
                                font.family: W.Tokens.mono; font.pixelSize: 11
                            }

                            // ── Type badge ───────────────────────────
                            Item {
                                width: 52; height: parent.height
                                Rectangle {
                                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                                    width: typeTxt.implicitWidth + 10; height: 17; radius: 3
                                    color: modelData.isDir
                                           ? Qt.rgba(1,1,1,0.05)
                                           : Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.15)
                                    Text {
                                        id: typeTxt; anchors.centerIn: parent
                                        text: modelData.isDir ? "DIR" : (modelData.ext || "FILE")
                                        color: modelData.isDir ? W.Tokens.textDim : W.Tokens.accentPrimary
                                        font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                    }
                                }
                            }
                        }
                    } // delegate
                } // ListView
            }

            // ── Status bar ─────────────────────────────────────────
            Rectangle {
                Layout.fillWidth: true; height: 36
                color: W.Tokens.bgSurface
                Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: W.Tokens.borderBase }

                RowLayout {
                    anchors { fill: parent; leftMargin: 16; rightMargin: 12 }
                    spacing: 12

                    // Info text
                    Text {
                        Layout.fillWidth: true; elide: Text.ElideRight
                        text: {
                            if (root.selectedItem) {
                                return root.selectedItem.isDir
                                       ? "▸  " + root.selectedItem.name
                                       : "▶  " + root.selectedItem.name
                            }
                            if (root.currentItems.length > 0)
                                return root.currentItems.length + " elemento(s)"
                            return ""
                        }
                        color: root.selectedItem ? W.Tokens.textPrimary : W.Tokens.textDim
                        font.family: W.Tokens.mono; font.pixelSize: 11
                    }

                    // Date + size for selected file
                    Text {
                        visible: root.selectedItem !== null && !root.selectedItem.isDir
                        text: root.selectedItem
                              ? root.selectedItem.modified + "  ·  " + root.selectedItem.size
                              : ""
                        color: W.Tokens.textMuted; font.family: W.Tokens.mono; font.pixelSize: 10
                    }

                    // Play button
                    Rectangle {
                        visible: root.selectedItem !== null && !root.selectedItem.isDir
                        implicitWidth: playLbl.implicitWidth + 28; height: 26
                        radius: W.Tokens.rPill; color: W.Tokens.accentPrimary

                        Text {
                            id: playLbl; anchors.centerIn: parent
                            text: "▶  REPRODUCIR"
                            color: W.Tokens.bgBase
                            font.family: W.Tokens.sans; font.pixelSize: 10
                            font.weight: Font.Bold; font.letterSpacing: 0.4
                        }
                        HoverHandler { id: pbHov }
                        Rectangle { anchors.fill: parent; radius: parent.radius; color: Qt.rgba(1,1,1,0.18); opacity: pbHov.hovered ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 100 } } }
                        TapHandler { onTapped: if (root.selectedItem) root.playRequested(root.selectedItem.path) }
                    }
                }
            }

        } // ColumnLayout main panel
    } // RowLayout

    // ── Inline sub-components ─────────────────────────────────────────

    component SideLabel: Text {
        Layout.fillWidth: true
        Layout.leftMargin: 14
        color: W.Tokens.textDim
        font.family: W.Tokens.sans; font.pixelSize: 9
        font.weight: Font.Bold; font.letterSpacing: 1.2
    }

    component SideEntry: Rectangle {
        Layout.fillWidth: true; height: 34
        required property string icon
        required property string label
        required property bool   active
        signal activated

        color: active ? Qt.rgba(W.Tokens.accentPrimary.r, W.Tokens.accentPrimary.g, W.Tokens.accentPrimary.b, 0.10)
                      : (sh.hovered ? Qt.rgba(1,1,1,0.04) : "transparent")
        Behavior on color { ColorAnimation { duration: 100 } }

        // Left accent
        Rectangle { width: 2; height: parent.height; color: active ? W.Tokens.accentPrimary : "transparent" }

        HoverHandler { id: sh }
        TapHandler   { onTapped: parent.activated() }

        Row {
            anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
            spacing: 10
            Text {
                text: parent.parent.icon; font.pixelSize: 13
                color: parent.parent.active ? W.Tokens.accentPrimary : W.Tokens.textDim
            }
            Text {
                text: parent.parent.label
                color: parent.parent.active ? W.Tokens.accentPrimary : W.Tokens.textMuted
                font.family: W.Tokens.sans; font.pixelSize: 12
                font.weight: parent.parent.active ? Font.Medium : Font.Normal
            }
        }
    }

    component NavBtn: Rectangle {
        required property string label
        required property bool   enabled
        signal activated
        width: 28; height: 28; radius: W.Tokens.rXs
        color: nb.hovered && enabled ? Qt.rgba(1,1,1,0.08) : Qt.rgba(1,1,1,0.04)
        Behavior on color { ColorAnimation { duration: 80 } }
        HoverHandler { id: nb }
        TapHandler   { onTapped: if (parent.enabled) parent.activated() }
        Text {
            anchors.centerIn: parent; text: parent.label
            color: parent.enabled ? W.Tokens.textMuted : Qt.rgba(1,1,1,0.15)
            font.pixelSize: 14
        }
    }

    component ColHdr: Item {
        required property string text
        property bool rightAlign: false
        height: 28
        Text {
            anchors { fill: parent; rightMargin: rightAlign ? 0 : 0 }
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: parent.rightAlign ? Text.AlignRight : Text.AlignLeft
            text: parent.text
            color: W.Tokens.textDim
            font.family: W.Tokens.sans; font.pixelSize: 9
            font.weight: Font.Bold; font.letterSpacing: 0.9
        }
    }
}
