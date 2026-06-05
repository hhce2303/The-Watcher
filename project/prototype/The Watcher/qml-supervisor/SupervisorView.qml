import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "." as W

// SupervisorView.qml — Supervisor role: status-aware operator grid + clip request form.
//
// Direction: Variant B (confirmed). Card detail = standard; default grouping = status;
// default sort = priority. Sort + grouping live in the toolbar (operator-level
// control), not in global tweaks.
//
//   Public API: none — the view is self-contained.

Item {
    id: root

    // ── Sample data (replace with model binding in production) ─────────────
    property var operators: makeOps()

    function makeOps() {
        var stations = ["NOC-A", "NOC-B", "NOC-C", "REMOTE", "FLOOR-2"]
        var tags     = ["lag spike", "crash · prod-api", "auth error",
                        "session drop", "memory leak", "disk full", "timeout",
                        null, null, null]
        var ago      = ["hace 2m", "hace 11m", "hace 38m", "hace 1h",
                        "hace 2h", "hace 4h", "ayer 18:42", "2d", null]
        function r(s) { var x = Math.sin(s) * 10000; return x - Math.floor(x) }
        var out = []
        for (var i = 1; i <= 47; i++) {
            var rn = r(i + 7), st
            if      (rn < 0.12) st = "rec"
            else if (rn < 0.62) st = "online"
            else if (rn < 0.78) st = "idle"
            else                st = "offline"
            var tag = st === "offline" ? null
                     : tags[Math.floor(r(i + 17) * tags.length)]
            out.push({
                n: i,
                num: String(i).padStart(2, "0"),
                name: "Operator-" + String(i).padStart(2, "0"),
                status: st,
                station: stations[Math.floor(r(i + 33) * stations.length)],
                eventTag: tag,
                lastEvent: tag ? ago[Math.floor(r(i + 41) * ago.length)] : null,
                buffer: st === "rec" ? (1 + Math.floor(r(i + 55) * 59)) + "s / 60s"
                       : (st === "online" ? "60s / 60s" : null),
                pinned: (i === 7 || i === 12 || i === 28 || i === 41),
            })
        }
        return out
    }

    // ── Interactive state ─────────────────────────────────────────────────
    property string query: ""
    property string statusFilter: "all"      // all | rec | online | event | idle | offline
    property string sortMode: "priority"     // priority | number | lastEvent | station
    property string grouping: "status"       // status | station | none

    property var    selectedOp: null
    property string startTime: "2026-06-04 14:00"
    property string endTime:   "2026-06-04 14:30"
    property string desc: ""
    property var    sentRequests: [
        { op: "12", tag: "lag spike",        t: "14:02", state: "IT" },
        { op: "07", tag: "crash · prod-api", t: "11:47", state: "OK" },
    ]

    // ── Derived: filtered + sorted + grouped ──────────────────────────────
    function filteredOps() {
        var q = root.query.trim().toLowerCase()
        var out = []
        for (var i = 0; i < root.operators.length; i++) {
            var o = root.operators[i]
            if (root.statusFilter !== "all") {
                if (root.statusFilter === "event") {
                    if (!o.eventTag) continue
                } else if (o.status !== root.statusFilter) {
                    continue
                }
            }
            if (q) {
                var hay = (o.num + " " + o.name + " " + o.station + " "
                           + (o.eventTag || "")).toLowerCase()
                if (hay.indexOf(q) < 0) continue
            }
            out.push(o)
        }
        return out
    }

    function sortOps(arr) {
        var rank = { rec: 0, online: 1, idle: 2, offline: 3 }
        var cmp
        if (root.sortMode === "number") {
            cmp = function(a,b) { return a.n - b.n }
        } else if (root.sortMode === "lastEvent") {
            cmp = function(a,b) {
                var ta = a.eventTag ? 0 : 1, tb = b.eventTag ? 0 : 1
                if (ta !== tb) return ta - tb
                return a.n - b.n
            }
        } else if (root.sortMode === "station") {
            cmp = function(a,b) {
                if (a.station !== b.station) return a.station < b.station ? -1 : 1
                return a.n - b.n
            }
        } else {
            // priority
            cmp = function(a,b) {
                if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status]
                if (!!a.eventTag !== !!b.eventTag)     return a.eventTag ? -1 : 1
                return a.n - b.n
            }
        }
        var copy = arr.slice()
        copy.sort(cmp)
        // favorites first (stable within already-sorted)
        copy.sort(function(a,b) { return (b.pinned?1:0) - (a.pinned?1:0) })
        return copy
    }

    function groupedOps() {
        var sorted = sortOps(filteredOps())
        if (root.grouping === "status") {
            var bins = { rec: [], online: [], idle: [], offline: [] }
            sorted.forEach(function(o) { bins[o.status].push(o) })
            var out = []
            var defs = [
                { id: "rec",     title: "GRABANDO AHORA", tone: W.Tokens.accentRecord },
                { id: "online",  title: "EN LÍNEA",       tone: W.Tokens.accentOk },
                { id: "idle",    title: "INACTIVOS",      tone: W.Tokens.accentYellow },
                { id: "offline", title: "SIN CONEXIÓN",   tone: W.Tokens.textDim },
            ]
            defs.forEach(function(d) {
                if (bins[d.id].length > 0)
                    out.push({ id: d.id, title: d.title, tone: d.tone, ops: bins[d.id] })
            })
            return out
        }
        if (root.grouping === "station") {
            var map = {}
            sorted.forEach(function(o) {
                if (!map[o.station]) map[o.station] = []
                map[o.station].push(o)
            })
            var keys = Object.keys(map).sort()
            return keys.map(function(k) {
                return { id: k, title: k.toUpperCase(),
                         tone: W.Tokens.accentPrimary, ops: map[k] }
            })
        }
        return [{ id: "all", title: "OPERADORES · " + sorted.length,
                  tone: W.Tokens.accentPrimary, ops: sorted }]
    }

    // ── Status counts (for chips) ─────────────────────────────────────────
    function statusCounts() {
        var c = { all: 0, rec: 0, online: 0, idle: 0, offline: 0, event: 0 }
        root.operators.forEach(function(o) {
            c.all++; c[o.status]++
            if (o.eventTag) c.event++
        })
        return c
    }
    readonly property var counts: statusCounts()

    // ── Actions ───────────────────────────────────────────────────────────
    function clearSelection() { root.selectedOp = null }
    function submitRequest() {
        if (!root.selectedOp) return
        var now = new Date()
        var hh = String(now.getHours()).padStart(2, "0")
        var mm = String(now.getMinutes()).padStart(2, "0")
        var rec = {
            op: root.selectedOp.num,
            tag: root.desc.length > 0 ? root.desc
                : (root.selectedOp.eventTag ? root.selectedOp.eventTag : "revisión"),
            t: hh + ":" + mm, state: "IT"
        }
        root.sentRequests = [rec].concat(root.sentRequests)
        root.desc = ""
        root.selectedOp = null
    }

    function applyPreset(mins) {
        var now = new Date()
        var past = new Date(now.getTime() - mins * 60000)
        function fmt(d) {
            return d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2, "0")
                 + "-" + String(d.getDate()).padStart(2, "0")
                 + " " + String(d.getHours()).padStart(2, "0")
                 + ":" + String(d.getMinutes()).padStart(2, "0")
        }
        root.startTime = fmt(past)
        root.endTime   = fmt(now)
    }

    // ── Keyboard: Ctrl+K focuses search, Esc clears selection ─────────────
    Shortcut {
        sequence: "Ctrl+K"
        onActivated: searchField.forceActiveFocus()
    }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (searchField.activeFocus) { root.query = ""; searchField.focus = false }
            else root.clearSelection()
        }
    }

    // ── Body: two columns ─────────────────────────────────────────────────
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── Left: toolbar + grid ──────────────────────────────────────────
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // Sticky toolbar
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: toolbar.implicitHeight + 28
                color: W.Tokens.bgBase
                Rectangle { anchors.bottom: parent.bottom; width: parent.width
                            height: 1; color: W.Tokens.borderBase }

                ColumnLayout {
                    id: toolbar
                    anchors {
                        fill: parent
                        leftMargin: 20; rightMargin: 20
                        topMargin: 14; bottomMargin: 14
                    }
                    spacing: 10

                    // Search field
                    Rectangle {
                        Layout.fillWidth: true
                        height: 38
                        radius: W.Tokens.rSm
                        color: W.Tokens.bgSurface
                        border.color: searchField.activeFocus ? W.Tokens.accentPrimary
                                                              : W.Tokens.borderBase
                        border.width: 1
                        Behavior on border.color { ColorAnimation { duration: 120 } }

                        RowLayout {
                            anchors { fill: parent; leftMargin: 14; rightMargin: 10 }
                            spacing: 10

                            Text {
                                text: "⌕"
                                color: W.Tokens.textMuted
                                font.pixelSize: 14
                            }

                            TextField {
                                id: searchField
                                Layout.fillWidth: true
                                placeholderText: "Buscar operador, número, estación o etiqueta de evento…"
                                placeholderTextColor: W.Tokens.textDim
                                text: root.query
                                onTextChanged: root.query = text
                                color: W.Tokens.textPrimary
                                font.family: W.Tokens.sans
                                font.pixelSize: 13
                                background: Rectangle { color: "transparent" }
                                selectByMouse: true
                            }

                            // Clear
                            Rectangle {
                                visible: root.query.length > 0
                                width: 22; height: 22; radius: W.Tokens.rXs
                                color: clrH.hovered ? W.Tokens.bgElevated : "transparent"
                                border.color: W.Tokens.borderBase; border.width: 1
                                HoverHandler { id: clrH }
                                TapHandler   { onTapped: { root.query = ""; searchField.focus = false } }
                                Text { anchors.centerIn: parent; text: "✕"
                                       color: W.Tokens.textMuted; font.pixelSize: 9 }
                            }

                            // Kbd hint
                            Rectangle {
                                width: kHint.implicitWidth + 10; height: 18
                                radius: 3
                                color: "transparent"
                                border.color: W.Tokens.borderBase; border.width: 1
                                Text {
                                    id: kHint; anchors.centerIn: parent
                                    text: "⌘K"
                                    color: W.Tokens.textMuted
                                    font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                }
                            }
                        }
                    }

                    // Filter chips + sort/group menus
                    Flow {
                        Layout.fillWidth: true
                        spacing: 6

                        Repeater {
                            model: [
                                { id: "all",     label: "Todos",      n: root.counts.all,     dot: "" },
                                { id: "rec",     label: "Grabando",   n: root.counts.rec,     dot: W.Tokens.accentRecord },
                                { id: "online",  label: "En línea",   n: root.counts.online,  dot: W.Tokens.accentOk },
                                { id: "event",   label: "Con evento", n: root.counts.event,   dot: W.Tokens.accentYellow },
                                { id: "idle",    label: "Inactivos",  n: root.counts.idle,    dot: W.Tokens.accentYellow },
                                { id: "offline", label: "Sin conex.", n: root.counts.offline, dot: "" },
                            ]
                            delegate: Rectangle {
                                property bool active: root.statusFilter === modelData.id
                                height: 28
                                width: chipRow.implicitWidth + 20
                                radius: W.Tokens.rXs
                                color: active ? W.Tokens.primaryDim : "transparent"
                                border.color: active ? Qt.rgba(W.Tokens.accentPrimary.r,
                                                               W.Tokens.accentPrimary.g,
                                                               W.Tokens.accentPrimary.b, 0.4)
                                                     : W.Tokens.borderBase
                                border.width: 1
                                Behavior on color  { ColorAnimation { duration: 120 } }

                                HoverHandler { id: chh }
                                TapHandler   { onTapped: root.statusFilter = modelData.id }

                                RowLayout {
                                    id: chipRow
                                    anchors.centerIn: parent
                                    spacing: 6

                                    Rectangle {
                                        visible: modelData.dot.toString().length > 0
                                        width: 5; height: 5; radius: 3
                                        color: modelData.dot.toString().length > 0 ? modelData.dot : "transparent"
                                        Layout.alignment: Qt.AlignVCenter
                                    }
                                    Text {
                                        text: modelData.label
                                        color: parent.parent.active ? W.Tokens.accentPrimary
                                                                    : W.Tokens.textMuted
                                        font.family: W.Tokens.sans
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    Rectangle {
                                        Layout.alignment: Qt.AlignVCenter
                                        width: nLbl.implicitWidth + 8; height: 14
                                        radius: 2
                                        color: parent.parent.active ? "transparent" : W.Tokens.bgSurface
                                        Text {
                                            id: nLbl; anchors.centerIn: parent
                                            text: modelData.n
                                            color: parent.parent.parent.active ? W.Tokens.accentPrimary
                                                                                : W.Tokens.textDim
                                            font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                        }
                                    }
                                }
                            }
                        }

                        // spacer to push the menus right
                        Item { width: 4; height: 1 }

                        Loader { sourceComponent: menuComp; property var labels: ["ORDEN", root.sortMode, "sort"] }
                        Loader { sourceComponent: menuComp; property var labels: ["GRUPO", root.grouping, "group"] }
                    }
                }
            }

            // ── Groups (scrollable) ───────────────────────────────────────
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ColumnLayout {
                    width: parent.width
                    spacing: 20

                    Item { height: 4 }

                    Repeater {
                        model: root.groupedOps()
                        delegate: ColumnLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: 20
                            Layout.rightMargin: 20
                            spacing: 10

                            // Group header
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                Rectangle {
                                    width: 6; height: 6; radius: 3
                                    color: modelData.tone
                                    Layout.alignment: Qt.AlignVCenter
                                }
                                Text {
                                    text: modelData.title
                                    color: modelData.tone
                                    font.family: W.Tokens.mono
                                    font.pixelSize: 9
                                    font.weight: Font.Bold
                                    font.letterSpacing: 1.4
                                }
                                Text {
                                    text: "· " + modelData.ops.length
                                    color: W.Tokens.textDim
                                    font.family: W.Tokens.mono
                                    font.pixelSize: 9
                                    font.weight: Font.DemiBold
                                }
                                Rectangle {
                                    Layout.fillWidth: true
                                    Layout.alignment: Qt.AlignVCenter
                                    height: 1
                                    color: W.Tokens.borderBase
                                    Layout.leftMargin: 4
                                }
                            }

                            // Cards grid
                            Flow {
                                Layout.fillWidth: true
                                spacing: 8

                                Repeater {
                                    model: modelData.ops
                                    delegate: W.OperatorCard {
                                        width: (parent.width - 5 * 8) / 6   // 6 cols
                                        op: modelData
                                        selected: root.selectedOp
                                                  && root.selectedOp.n === modelData.n
                                        onClicked: {
                                            if (root.selectedOp && root.selectedOp.n === modelData.n)
                                                root.selectedOp = null
                                            else
                                                root.selectedOp = modelData
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Item { height: 24 }   // bottom padding
                }
            }
        }

        // ── Right: form rail ──────────────────────────────────────────────
        Rectangle {
            Layout.preferredWidth: 360
            Layout.fillHeight: true
            color: W.Tokens.bgBase

            Rectangle { anchors.left: parent.left; width: 1; height: parent.height
                        color: W.Tokens.borderBase }

            ColumnLayout {
                anchors { fill: parent; margins: 0 }
                spacing: 0

                // Header
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 64
                    color: "transparent"
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width
                                height: 1; color: W.Tokens.borderBase }

                    ColumnLayout {
                        anchors { fill: parent; leftMargin: 20; rightMargin: 20
                                  topMargin: 14; bottomMargin: 12 }
                        spacing: 4
                        Text {
                            text: "SOLICITAR CLIP"
                            color: W.Tokens.accentPrimary
                            font.family: W.Tokens.mono
                            font.pixelSize: 10
                            font.weight: Font.Bold
                            font.letterSpacing: 1.8
                        }
                        Text {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            text: root.selectedOp
                                  ? "Define la ventana del incidente y un contexto opcional para IT."
                                  : "Selecciona un operador en la izquierda para empezar."
                            color: W.Tokens.textMuted
                            font.family: W.Tokens.sans
                            font.pixelSize: 11
                        }
                    }
                }

                // Form body (scrollable)
                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    ColumnLayout {
                        width: parent.width - 40
                        x: 20
                        spacing: 14
                        Item { height: 4 }

                        // ── Operador chip ─────────────────────────────────
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: "OPERADOR"
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.mono
                                font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.4
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                radius: W.Tokens.rXs + 1
                                color: root.selectedOp ? W.Tokens.bgSurface : "transparent"
                                border.color: root.selectedOp ? Qt.rgba(W.Tokens.accentPrimary.r,
                                                                        W.Tokens.accentPrimary.g,
                                                                        W.Tokens.accentPrimary.b, 0.4)
                                                              : W.Tokens.borderBase
                                border.width: 1

                                Loader {
                                    anchors { fill: parent; leftMargin: 12; rightMargin: 8 }
                                    sourceComponent: root.selectedOp ? selectedOpRow : emptyOpRow
                                }
                            }
                        }

                        // ── Quick presets ─────────────────────────────────
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: "PRE-SET RÁPIDO"
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.mono
                                font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.4
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Repeater {
                                    model: [
                                        { l: "5 min",  m: 5 },
                                        { l: "15 min", m: 15 },
                                        { l: "30 min", m: 30 },
                                        { l: "1 h",    m: 60 },
                                        { l: "2 h",    m: 120 },
                                    ]
                                    delegate: Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 26
                                        radius: W.Tokens.rXs
                                        color: ph.hovered ? W.Tokens.bgElevated : W.Tokens.bgSurface
                                        border.color: W.Tokens.borderBase; border.width: 1
                                        Behavior on color { ColorAnimation { duration: 100 } }
                                        HoverHandler { id: ph }
                                        TapHandler   { onTapped: root.applyPreset(modelData.m) }
                                        Text {
                                            anchors.centerIn: parent
                                            text: modelData.l
                                            color: W.Tokens.textMuted
                                            font.family: W.Tokens.mono
                                            font.pixelSize: 10; font.weight: Font.Bold
                                        }
                                    }
                                }
                            }
                        }

                        // ── Start / End ───────────────────────────────────
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: "INICIO DEL INCIDENTE"
                                    color: W.Tokens.textMuted
                                    font.family: W.Tokens.mono
                                    font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.4
                                }
                                W.TextInput {
                                    id: startInput
                                    Layout.fillWidth: true
                                    value: root.startTime
                                    onValueEdited: root.startTime = v
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 6
                                Text {
                                    text: "FIN DEL INCIDENTE"
                                    color: W.Tokens.textMuted
                                    font.family: W.Tokens.mono
                                    font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.4
                                }
                                W.TextInput {
                                    Layout.fillWidth: true
                                    value: root.endTime
                                    onValueEdited: root.endTime = v
                                }
                            }
                        }

                        // ── Description ───────────────────────────────────
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 6
                            Text {
                                text: "DESCRIPCIÓN DEL INCIDENTE"
                                color: W.Tokens.textMuted
                                font.family: W.Tokens.mono
                                font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.4
                            }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 84
                                radius: W.Tokens.rXs + 1
                                color: W.Tokens.bgSurface
                                border.color: descArea.activeFocus ? W.Tokens.accentPrimary
                                                                   : W.Tokens.borderBase
                                border.width: 1
                                Behavior on border.color { ColorAnimation { duration: 120 } }

                                ScrollView {
                                    anchors { fill: parent; margins: 8 }
                                    TextArea {
                                        id: descArea
                                        text: root.desc
                                        onTextChanged: root.desc = text
                                        placeholderText: "Contexto para IT: tipo de incidente, hora exacta, observaciones…"
                                        placeholderTextColor: W.Tokens.textDim
                                        color: W.Tokens.textPrimary
                                        font.family: W.Tokens.sans
                                        font.pixelSize: 11
                                        wrapMode: TextEdit.Wrap
                                        background: Rectangle { color: "transparent" }
                                    }
                                }
                            }
                        }

                        // ── Submit ────────────────────────────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 40
                            radius: W.Tokens.rSm
                            property bool enabled: root.selectedOp !== null
                            color: enabled ? W.Tokens.accentPrimary : W.Tokens.bgElevated
                            opacity: enabled ? 1.0 : 0.6
                            Behavior on color   { ColorAnimation  { duration: 120 } }
                            Behavior on opacity { NumberAnimation { duration: 120 } }

                            HoverHandler { id: sh; enabled: parent.enabled }
                            TapHandler   { id: st; enabled: parent.enabled
                                           onTapped: root.submitRequest() }

                            scale: st.pressed ? 0.97 : (sh.hovered ? 1.02 : 1.0)
                            Behavior on scale { NumberAnimation { duration: 100 } }

                            Row {
                                anchors.centerIn: parent
                                spacing: 8
                                Text {
                                    text: "➤"
                                    color: parent.parent.enabled ? W.Tokens.bgBase : W.Tokens.textDim
                                    font.pixelSize: 13
                                }
                                Text {
                                    text: "Enviar a IT"
                                    color: parent.parent.enabled ? W.Tokens.bgBase : W.Tokens.textDim
                                    font.family: W.Tokens.sans
                                    font.pixelSize: 12; font.weight: Font.Bold
                                }
                            }
                        }

                        // ── My requests ───────────────────────────────────
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: reqCol.implicitHeight + 24
                            radius: W.Tokens.rXs + 1
                            color: W.Tokens.bgSurface
                            border.color: W.Tokens.borderBase
                            border.width: 1

                            ColumnLayout {
                                id: reqCol
                                anchors { fill: parent; margins: 12 }
                                spacing: 8

                                RowLayout {
                                    Layout.fillWidth: true
                                    Text {
                                        text: "MIS SOLICITUDES · HOY"
                                        color: W.Tokens.textMuted
                                        font.family: W.Tokens.mono
                                        font.pixelSize: 9; font.weight: Font.Bold; font.letterSpacing: 1.4
                                    }
                                    Item { Layout.fillWidth: true }
                                    Text {
                                        text: root.sentRequests.length
                                        color: W.Tokens.textDim
                                        font.family: W.Tokens.mono; font.pixelSize: 9; font.weight: Font.Bold
                                    }
                                }

                                Text {
                                    visible: root.sentRequests.length === 0
                                    text: "No hay solicitudes enviadas todavía."
                                    color: W.Tokens.textDim
                                    font.family: W.Tokens.mono
                                    font.pixelSize: 10
                                }

                                Repeater {
                                    model: root.sentRequests
                                    delegate: RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        Text {
                                            text: modelData.op
                                            color: W.Tokens.textPrimary
                                            font.family: W.Tokens.mono
                                            font.pixelSize: 11; font.weight: Font.Bold
                                            Layout.preferredWidth: 22
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            elide: Text.ElideRight
                                            text: modelData.tag
                                            color: W.Tokens.textPrimary
                                            font.family: W.Tokens.sans
                                            font.pixelSize: 11
                                        }
                                        Text {
                                            text: modelData.t
                                            color: W.Tokens.textDim
                                            font.family: W.Tokens.mono
                                            font.pixelSize: 10
                                        }
                                        Rectangle {
                                            Layout.preferredWidth: stLbl.implicitWidth + 10
                                            Layout.preferredHeight: 16
                                            radius: 2
                                            color: modelData.state === "OK"
                                                ? Qt.rgba(W.Tokens.accentOk.r, W.Tokens.accentOk.g, W.Tokens.accentOk.b, 0.14)
                                                : Qt.rgba(W.Tokens.accentYellow.r, W.Tokens.accentYellow.g, W.Tokens.accentYellow.b, 0.14)
                                            Text {
                                                id: stLbl; anchors.centerIn: parent
                                                text: modelData.state === "OK" ? "LISTO" : "EN IT"
                                                color: modelData.state === "OK" ? W.Tokens.accentOk
                                                                                : W.Tokens.accentYellow
                                                font.family: W.Tokens.mono
                                                font.pixelSize: 8; font.weight: Font.Bold; font.letterSpacing: 0.6
                                            }
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
    }

    // ── Inline components ─────────────────────────────────────────────────
    Component {
        id: selectedOpRow
        RowLayout {
            spacing: 10
            Rectangle {
                width: 6; height: 6; radius: 3
                color: {
                    var s = root.selectedOp ? root.selectedOp.status : "online"
                    if (s === "rec")    return W.Tokens.accentRecord
                    if (s === "online") return W.Tokens.accentOk
                    if (s === "idle")   return W.Tokens.accentYellow
                    return W.Tokens.textDim
                }
                Layout.alignment: Qt.AlignVCenter
            }
            Text {
                text: root.selectedOp ? root.selectedOp.name : ""
                color: W.Tokens.textPrimary
                font.family: W.Tokens.mono; font.pixelSize: 12; font.weight: Font.Bold
            }
            Text {
                text: root.selectedOp ? "· " + root.selectedOp.station : ""
                color: W.Tokens.textMuted
                font.family: W.Tokens.mono; font.pixelSize: 10
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                width: 22; height: 22; radius: W.Tokens.rXs
                color: ch.hovered ? W.Tokens.bgElevated : "transparent"
                border.color: W.Tokens.borderBase; border.width: 1
                HoverHandler { id: ch }
                TapHandler   { onTapped: root.clearSelection() }
                Text { anchors.centerIn: parent; text: "✕"
                       color: W.Tokens.textMuted; font.pixelSize: 9 }
            }
        }
    }

    Component {
        id: emptyOpRow
        Text {
            text: "Sin operador seleccionado"
            color: W.Tokens.textDim
            font.family: W.Tokens.mono; font.pixelSize: 11
            verticalAlignment: Text.AlignVCenter
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    // Sort / Group menu component
    Component {
        id: menuComp
        Rectangle {
            id: menuRoot
            property var labels                       // [labelText, currentValue, kind]
            property bool isSort: labels[2] === "sort"
            height: 28
            implicitWidth: menuRow.implicitWidth + 20
            radius: W.Tokens.rXs
            color: W.Tokens.bgSurface
            border.color: W.Tokens.borderBase; border.width: 1
            HoverHandler { id: mh }
            TapHandler { onTapped: menuRoot.cycle() }

            function cycle() {
                if (isSort) {
                    var s = ["priority", "number", "lastEvent", "station"]
                    var i = s.indexOf(root.sortMode)
                    root.sortMode = s[(i + 1) % s.length]
                } else {
                    var g = ["status", "station", "none"]
                    var j = g.indexOf(root.grouping)
                    root.grouping = g[(j + 1) % g.length]
                }
            }
            function pretty(v) {
                var map = {
                    priority: "Prioridad", number: "Número ↑",
                    lastEvent: "Último evento", station: "Estación",
                    status: "Por estado", none: "Sin grupos"
                }
                if (v === "station" && !isSort) return "Por estación"
                return map[v] || v
            }

            RowLayout {
                id: menuRow
                anchors.centerIn: parent
                spacing: 6
                Text {
                    text: menuRoot.labels[0] + " ·"
                    color: W.Tokens.textDim
                    font.family: W.Tokens.mono; font.pixelSize: 9
                    font.weight: Font.DemiBold; font.letterSpacing: 1.4
                }
                Text {
                    text: menuRoot.pretty(menuRoot.isSort ? root.sortMode : root.grouping)
                    color: W.Tokens.textPrimary
                    font.family: W.Tokens.sans
                    font.pixelSize: 11; font.weight: Font.DemiBold
                }
                Text {
                    text: "▾"
                    color: W.Tokens.textMuted
                    font.pixelSize: 9
                }
            }
        }
    }
}
