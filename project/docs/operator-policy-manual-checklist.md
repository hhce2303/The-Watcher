# Manual verification — Operator policy engine + restart watchdog

The Scheduled-Task restart-after-kill behaviour **cannot be unit-tested** (it
depends on the Windows Task Scheduler restarting a real process) and the
scheduled-task settings are easy to misconfigure silently. Run this checklist on
a real Windows operator station before deploying.

Build/run as the **operator** role (set role to operator, relaunch).

## Visual rules
- [ ] On launch the app records, shows only the recording tab, is full screen,
      and the persistent **● GRABANDO** pill is visible at top-center.
- [ ] The pill cannot be dismissed (no close affordance, no click target).
- [ ] `Alt+F4` and the ✕ button do **not** close or hide the window — it stays.
- [ ] There is **no minimise (−) button**; `Win+M` / `Win+D` / taskbar click
      bounce the window back to full screen (it never stays minimised).

## Tray
- [ ] The tray menu has **no "Exit"** item (only "Open Dashboard").

## Inter-role
- [ ] `Ctrl+Alt+Shift+R` + correct IT PIN → role-change UI unlocks.
- [ ] Wrong / no PIN → role change stays blocked.

## Restart watchdog (the part with no automated test)
- [ ] After launch, the scheduled task exists:
      `schtasks /Query /TN TheWatcher-OperatorWatchdog` → present, and its
      settings show *Restart on failure = 1 min* and *If already running: do not
      start a new instance*.
- [ ] **Kill the process** via Task Manager (End task) → the app comes back on
      its own within ~1 minute.
- [ ] **Log off / log on** → the app auto-starts (the task is the sole launcher;
      the HKCU Run key for `The-Watcher` should be absent for the operator).
- [ ] **Role change** IT → operator → IT leaves exactly **one** instance running
      (no second window, no "another instance" dialog).

## Degraded fallback (locked-down box)
- [ ] Simulate a Task Scheduler failure (deny task creation / GPO). On launch the
      app falls back to the HKCU Run key, logs a loud warning, and the tray
      tooltip shows the degraded "auto-reinicio limitado" message. Recording is
      unaffected.

## Other roles (regression)
- [ ] Supervisor: clips tab only, no recording, window closes/minimises normally,
      tray has "Exit", no scheduled task registered.
- [ ] IT: all tabs, autorecord honours the toggle, window behaves normally,
      no operator scheduled task left behind.
