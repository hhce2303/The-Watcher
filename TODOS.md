# TODOS

## Operator policy engine — deferred follow-ups
Captured during `/plan-eng-review` of `feat/operator-policy-engine` (2026-06-23).
All three were consciously deferred to keep this PR right-sized; each has a clear
trigger to pick it up.

### 1. Hang / liveness detection for the operator process
- **What:** Detect and recover a *hung-but-alive* operator process (frozen Qt
  loop) — add a heartbeat (the app writes a timestamp; a checker relaunches if
  stale) or a watchdog execution-time-limit.
- **Why:** The current restart watchdog is a Windows Scheduled Task with
  *restart-on-failure*. It only fires when the process *exits* with a non-zero
  result (kill / crash). A process that is alive but wedged never exits, so the
  scheduler never restarts it and recording silently stops.
- **Pros:** Closes the last always-on gap.
- **Cons:** Reintroduces the polling/heartbeat machinery the native-scheduler
  approach deliberately avoided; risk of false-positive relaunches during heavy
  disk I/O or FFmpeg stalls.
- **Context:** The common hang (FFmpeg stall) is already handled in-process by
  `RecorderSupervisor` (`app/core/recording_service/supervisor.py`) plus
  `recording_health`. This TODO is only for a *full-app* freeze, which is rarer.
- **Depends on:** the scheduled-task watchdog (`app/infrastructure/scheduled_task.py`).

### 2. Report degraded watchdog state to IT (remote)
- **What:** When the scheduled-task registration fails (corporate group policy /
  permissions) and the app falls back to the HKCU Run key, push that degraded
  state to IT over the existing request WebSocket / inbox — not just the local
  tray tooltip.
- **Why:** On a locked-down box the operator has no settings tab and may never
  notice the tray tooltip. IT should know which stations lack restart-after-kill
  protection (fleet health).
- **Pros:** IT visibility into degraded stations.
- **Cons:** Couples a log/status concern to the WS/inbox plumbing for a rare case.
- **Context:** `enforce_role` returns `"runkey"` in this case (see
  `app/core/role.py`); `main.py` already surfaces it to the tray tooltip
  (`app/adapters/ui/tray_icon.py`). The WS server/client live in `app/adapters/ws/`.
- **Depends on:** the request system (IT server / Supervisor client).

### 3. Audit log for IT unlocks and role changes
- **What:** Persist an audit trail (who / when / which machine) for IT-PIN
  unlocks (`Ctrl+Alt+Shift+R`) and role changes (`setRole`).
- **Why:** The IT PIN is the *sole* gate — anyone holding it can unlock on any
  machine. For a security/monitoring tool, traceability of privilege use matters.
- **Pros:** Accountability for a sensitive action.
- **Cons:** Small logging + persistence cost; decide retention/location.
- **Context:** `SettingsBridge.unlockIT` / `setRole`
  (`app/adapters/ui/settings_bridge.py`) already log to Loguru; this would add a
  dedicated, queryable audit channel. The threat model (PIN-as-sole-gate) is
  documented inline in `setRole`.
- **Depends on:** —
