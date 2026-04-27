# Event-Based Pre/Post Recording System

## Overview

This project is a lightweight, event‑driven video recording service designed to run on a workstation that is already busy with other processes. The goal is to capture **2 minutes before and 2 minutes after** an event, then produce a final MP4 clip automatically.

Key constraints:

* Minimal CPU/RAM impact
* Single window / browser capture
* Local processing and storage
* Always-on-top recording source
* Expected events: 2–3 per hour
* Recording duration per event: ~4 minutes
* Output resolution: 1920x1080
* Clip retention: 1–2 hours minimum

The system is built using **Python + FFmpeg** with a pragmatic **Hexagonal (Ports & Adapters) Architecture**.

---

# Architecture

## Why Hexagonal (Pragmatic Version)

We need a scalable and professional architecture but without unnecessary complexity.

This project uses a **minimal hexagonal architecture**:

Core (Business Logic)
→ Ports (Interfaces)
→ Adapters (External tools: FFmpeg, filesystem, UI trigger)

The recording service itself is implemented as its own mini-hexagon inside the application core.

This gives us:

* Testability
* Easy replacement of FFmpeg or UI trigger
* Clear separation of responsibilities
* Scalability for future integrations

---

## High Level Flow

1. System continuously records a rolling buffer (2 minutes).
2. User presses a button → Event triggered.
3. System keeps recording for 2 minutes more.
4. Recording service trims pre/post segments.
5. Final MP4 is produced.
6. Temporary files are cleaned automatically.

---

# Project Structure

```
project/
│
├── app/
│   ├── core/
│   │   ├── event_listener.py
│   │   ├── recording_service/
│   │   │   ├── service.py
│   │   │   ├── buffer_manager.py
│   │   │   ├── clip_builder.py
│   │   │   └── models.py
│   │   │
│   │   └── ports/
│   │       ├── recorder_port.py
│   │       ├── storage_port.py
│   │       └── trigger_port.py
│   │
│   ├── adapters/
│   │   ├── ffmpeg/
│   │   │   ├── recorder_adapter.py
│   │   │   ├── trim_adapter.py
│   │   │   └── thumbnail_adapter.py
│   │   │
│   │   ├── filesystem/
│   │   │   └── storage_adapter.py
│   │   │
│   │   └── ui/
│   │       └── button_trigger.py
│   │
│   └── main.py
│
└── README.md
```

---

# Core Concepts

## 1. Continuous Rolling Buffer

A background FFmpeg process continuously records the target window and splits the stream into short segments (for example 10–15 seconds each).

This creates a **ring buffer** that always contains the last 2 minutes of video.

Why this approach?

* Extremely efficient
* No heavy RAM usage
* Easy trimming
* Used by professional video systems

---

## 2. Event Trigger

The event listener is intentionally simple.

For the first milestone, an event is triggered by a **button press**.

Future adapters could include:

* Websocket listener
* API endpoint
* Hotkey
* External alarm system

The core never knows *how* the event happens.

It only receives:

```
EventTriggered(timestamp)
```

---

## 3. Recording Service (Inner Hexagon)

The recording service is the heart of the system.

Responsibilities:

* Maintain rolling buffer
* Freeze buffer when event occurs
* Continue recording post-event footage
* Build final clip

### Recording Timeline

```
<--- 120s PRE BUFFER ---> [ EVENT ] <--- 120s POST RECORD --->
```

When the event occurs:

1. The buffer is frozen.
2. System records 120 additional seconds.
3. Clip builder merges segments.
4. Final MP4 is generated.

---

## 4. Clip Builder

The clip builder performs:

* Segment selection
* Video concatenation
* Encoding to final MP4

Output format:

* H.264
* 1920x1080
* Optimized for quick playback

---

## 5. Storage Strategy

We separate **temporary files** from **final clips**.

Temporary files:

* Ring buffer segments
* Auto-deleted periodically

Final clips:

* Saved locally
* Stored for 1–2 hours minimum

No retention policy required beyond this.

---

# Ports & Adapters

## Recorder Port

Defines actions the core expects:

* Start continuous recording
* Stop recording
* Get buffer segments

Adapter implementation: FFmpeg

---

## Storage Port

Defines:

* Save clip
* Delete temporary files
* Retrieve segment list

Adapter implementation: Local filesystem

---

## Trigger Port

Defines:

* Subscribe to event

Adapter implementation: UI button

---

# How Python Talks to FFmpeg

Communication strategy:

* Python spawns FFmpeg as a subprocess
* Commands are generated dynamically
* Python orchestrates the pipeline
* FFmpeg performs heavy video work

This keeps Python lightweight and avoids CPU spikes.

---

# Efficiency Strategy

Key design decisions to protect system performance:

* FFmpeg handles encoding (native C performance)
* Segmented recording prevents large files
* Asynchronous queues avoid blocking
* Single recording window only
* No database required

The system is safe to run alongside other heavy software.

---

# Event Workflow (Step by Step)

1. Application starts
2. FFmpeg begins rolling recording
3. User presses event button
4. Core freezes buffer snapshot
5. Post-recording continues 120 seconds
6. Segments are merged
7. Final MP4 is generated
8. Temp files cleaned

---

# Future Scalability

This architecture allows adding later:

* Multiple recording sources
* Websocket event triggers
* Cloud upload
* Thumbnail generation
* AI event detection

Without rewriting the core logic.

---

# Conclusion

This system recreates a professional pre/post event recording workflow using:

* Python orchestration
* FFmpeg processing
* Minimal hexagonal architecture

It is efficient, modular, and ready to scale.

---

# Development Master Plan (Milestones)

This roadmap converts the architecture into an execution plan. Each milestone produces a testable deliverable and reduces technical risk early.

---

## Milestone 0 — Project Bootstrap

**Goal:** Create the foundation and dev environment.

Deliverables:

* Python project scaffold
* Dependency management (Poetry or venv + pip-tools)
* Logging system
* Config management (.env)
* Folder structure aligned with hexagonal architecture

Proposed structure:

```
src/
  core/
    recorder/
    clipper/
    events/
    ports/
  adapters/
    ffmpeg/
    filesystem/
    ui/
  infrastructure/
    scheduler/
    config/
    logging/
main.py
```

Exit criteria:

* App starts
* Logging works
* Config loads

---

## Milestone 1 — Continuous Segment Recorder (Critical Risk Reduction)

**Goal:** Prove continuous low‑resource recording is viable.

Implement:

* FFmpeg adapter
* Segment recording (2s segments)
* Circular buffer deletion policy
* Segment index tracking

Key technical risks addressed:

* CPU usage
* Disk IO impact
* Long‑running process stability

Success metrics:

* 2+ hours continuous recording
* CPU < 5–8%
* No memory leaks
* Disk growth capped

Exit criteria:

* Folder continuously contains last 2 hours of segments

---

## Milestone 2 — Segment Index & Time Mapping

**Goal:** Make segments queryable by time.

Implement:

* In‑memory segment index
* Segment metadata model
* Time‑range lookup API

Core capability:

```
get_segments_between(start, end)
```

Exit criteria:

* Can retrieve segments for any timestamp within buffer

---

## Milestone 3 — Clip Builder (FFmpeg Concat Pipeline)

**Goal:** Produce final MP4 clips.

Implement:

* Concat file generator
* FFmpeg clip assembly
* Error handling & retries
* Clip naming convention

Output example:

```
clips/2026-04-27_13-22-10_event.mp4
```

Exit criteria:

* Build 4‑minute clip from historical segments
* No re‑encoding (stream copy)

---

## Milestone 4 — Event Service + Scheduler

**Goal:** Connect event trigger to delayed clip creation.

Implement:

* Event model
* Cooldown protection (30s)
* Background job scheduler
* Delayed clip creation (+120s post buffer)

Flow:

1. User presses button
2. Event created
3. Clip job scheduled
4. Job executes after post buffer window

Exit criteria:

* Press button → clip appears 2 minutes later

---

## Milestone 5 — Minimal UI (Operator Tool)

**Goal:** Provide basic operator interface.

UI features:

* Recording status indicator
* "Mark Event" button
* Activity log
* System tray icon (recording indicator)

Tech options:

* PySide6 (preferred)
* Tkinter (fallback)

Exit criteria:

* Operator can trigger events reliably

---

## Milestone 6 — Reliability & Hardening

**Goal:** Make the system production‑safe.

Add:

* Crash recovery
* Recorder auto‑restart
* Disk space monitoring
* Clip build retry queue
* Structured logging

Exit criteria:

* Survives FFmpeg crash
* Survives full disk scenario

---

## Milestone 7 — Performance Optimization

**Goal:** Ensure minimal impact on host machine.

Tasks:

* CPU profiling
* IO profiling
* Segment size tuning
* Encoder preset tuning
* Stress testing under load

Exit criteria:

* Stable on busy workstation

---

## Milestone 8 — Packaging & Deployment

**Goal:** Deliver Windows executable.

Tasks:

* PyInstaller packaging
* FFmpeg bundling
* Auto‑start option
* Configurable paths

Exit criteria:

* Single installer
* Runs on clean Windows machine

---

## Milestone 9 — Future Integrations (Post‑MVP)

**Not required for first release**

Planned extensions:

* WebSocket event adapter
* Hotkey trigger
* Clip thumbnails
* Clip viewer
* Upload to server

---

# Development Strategy

Approach:

* Deliver vertical slices
* Validate performance early
* Avoid premature UI work
* Reduce FFmpeg risk first

Priority order:

1. Recorder stability
2. Clip correctness
3. Event workflow
4. UI polish

---

# Estimated Timeline (Solo Developer)

| Milestone    | Duration |
| ------------ | -------- |
| Bootstrap    | 1–2 days |
| Recorder     | 3–5 days |
| Index        | 2 days   |
| Clip builder | 3 days   |
| Event system | 2 days   |
| UI           | 3 days   |
| Hardening    | 4–6 days |
| Optimization | 3–4 days |
| Packaging    | 2 days   |

**Total MVP:** ~3–4 weeks

---

End of development roadmap.
