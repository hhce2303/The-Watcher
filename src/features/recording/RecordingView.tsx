import { useEffect, useState } from "react";
import { useRecording } from "../../hooks/useRecording";
import { useAppStore } from "../../stores/appStore";
import MonitorSelector from "./MonitorSelector";
import DraggableWorkspace from "./DraggableWorkspace";
import BufferTimeline from "./BufferTimeline";
import ITInboxPanel from "../it/ITInboxPanel";
import { getPreviewServerInfo } from "../../lib/ipc";
import type { PreviewServerInfo } from "../../types/dto";

function fmtTimecode(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = Math.floor(totalSeconds % 60);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

/** Grabación tab — port of qml/Main.qml's tab 0 (recording + preview + events). */
export default function RecordingView() {
  const { state, monitors, busy, error, actions } = useRecording();
  const [inboxOpen, setInboxOpen] = useState(false);
  const isIt = useAppStore((s) => s.settings?.role) === "it";
  const isOperator = useAppStore((s) => s.settings?.role) === "operator";
  const [previewServer, setPreviewServer] = useState<PreviewServerInfo | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOperator) return;
    getPreviewServerInfo().then(setPreviewServer).catch(() => null);
  }, [isOperator]);

  useEffect(() => {
    if (!isIt) return;
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.key.toLowerCase() === "i") {
        e.preventDefault();
        setInboxOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isIt]);

  if (!state) {
    return (
      <div className="placeholder-tab">
        <p>Connecting to backend…</p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: "var(--sp-6)", height: "100%" }}>
      <aside style={{ width: 260, flexShrink: 0, background: "var(--bg-surface)", borderRadius: "var(--r-md)", border: "1px solid var(--border-base)" }}>
        <MonitorSelector monitors={monitors} onToggle={actions.toggleMonitor} />
      </aside>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "var(--sp-6)", minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-5)" }}>
          <div role="status" aria-live="polite" style={{ display: "flex", alignItems: "center", gap: "var(--sp-3)" }}>
            <div
              aria-hidden="true"
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                background: state.is_recording ? "var(--accent-record)" : "var(--text-dim)",
              }}
            />
            <span style={{ fontWeight: 600, fontSize: 15 }}>
              {state.is_recording ? `Grabando — ${fmtTimecode(state.record_seconds)}` : "Inactivo"}
            </span>
          </div>
          <div style={{ flex: 1 }} />
          <button
            type="button"
            onClick={actions.toggleRecording}
            disabled={busy}
            aria-pressed={state.is_recording}
            aria-label={state.is_recording ? "Detener grabación" : "Iniciar grabación"}
            style={{
              padding: "6px 18px",
              borderRadius: "var(--r-sm)",
              border: "none",
              background: state.is_recording ? "var(--record-dim)" : "var(--primary-dim)",
              color: state.is_recording ? "var(--accent-record)" : "var(--accent-primary)",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {state.is_recording ? "Detener" : "Iniciar"}
          </button>
        </div>

        {error && <p style={{ color: "var(--accent-record)", fontSize: 12 }}>{error}</p>}

        {isOperator && previewServer?.active && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--sp-3)",
              padding: "6px 10px",
              borderRadius: "var(--r-sm)",
              background: "var(--bg-surface)",
              border: "1px solid var(--border-base)",
              fontSize: 12,
              color: "var(--text-dim)",
            }}
          >
            <span style={{ fontFamily: "monospace", color: "var(--text-base)" }}>
              {previewServer.base_url}
            </span>
            <button
              type="button"
              aria-label={copied ? "URL copiada al portapapeles" : "Copiar URL de la vista previa"}
              onClick={() => {
                navigator.clipboard.writeText(previewServer.stream_url_template.replace("{index}", "0"));
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
              style={{
                padding: "2px 8px",
                borderRadius: "var(--r-sm)",
                border: "1px solid var(--border-base)",
                background: "transparent",
                color: "var(--accent-primary)",
                fontSize: 11,
                cursor: "pointer",
              }}
            >
              {copied ? "Copiado" : "Copiar URL"}
            </button>
          </div>
        )}

        <DraggableWorkspace monitors={monitors} isRecording={state.is_recording} />

        <BufferTimeline recordSec={state.record_seconds} eventMarkers={[]} />
      </div>

      {isIt && inboxOpen && (
        <aside style={{ width: 320, flexShrink: 0, display: "flex", flexDirection: "column", height: "100%" }}>
          <ITInboxPanel />
        </aside>
      )}
    </div>
  );
}
