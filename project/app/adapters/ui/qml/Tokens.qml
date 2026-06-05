pragma Singleton
import QtQuick

// Tokens.qml — design tokens singleton
// Register in qmldir as: singleton Tokens 1.0 Tokens.qml
// Usage: import "qml" as W   →   color: W.Tokens.bgBase

QtObject {
    // ── Surfaces ──────────────────────────────────────────────
    readonly property color bgBase:        "#07090F"
    readonly property color bgSurface:     "#0D1220"
    readonly property color bgElevated:    "#141E30"

    // ── Accents ───────────────────────────────────────────────
    readonly property color accentPrimary: "#38BDF8"  // electric blue
    readonly property color accentRecord:  "#F43F5E"  // vivid rose
    readonly property color accentMonitor: "#818CF8"  // soft indigo
    readonly property color accentYellow:  "#FACC15"
    readonly property color accentOk:      "#34D399"

    // Tinted variants (use directly instead of Qt.rgba() at call site)
    readonly property color primaryDim:    Qt.rgba(0.22, 0.74, 0.97, 0.12)
    readonly property color recordDim:     Qt.rgba(0.96, 0.25, 0.37, 0.12)
    readonly property color monitorDim:    Qt.rgba(0.51, 0.55, 0.97, 0.10)

    // ── Text ──────────────────────────────────────────────────
    readonly property color textPrimary:   "#F8FAFC"
    readonly property color textMuted:     "#64748B"
    readonly property color textDim:       "#475569"

    // ── Borders ───────────────────────────────────────────────
    readonly property color borderBase:    "#1E293B"
    readonly property color borderSubtle:  "#334155"

    // ── Radii ─────────────────────────────────────────────────
    readonly property int rXs:   4
    readonly property int rSm:   6
    readonly property int rMd:   10
    readonly property int rLg:   14
    readonly property int rPill: 999

    // ── Spacing ───────────────────────────────────────────────
    readonly property int sp2:  4
    readonly property int sp3:  8
    readonly property int sp4:  12
    readonly property int sp5:  16
    readonly property int sp6:  20
    readonly property int sp7:  28

    // ── Type ──────────────────────────────────────────────────
    readonly property string sans: "Segoe UI"
    readonly property string mono: "Consolas"

    // Standard transition duration
    readonly property int durFast:  120
    readonly property int durMed:   180
    readonly property int durSlow:  240
}
