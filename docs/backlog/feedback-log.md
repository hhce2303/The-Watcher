# Feedback log

Raw, unprocessed requests — written as close to what was actually said as possible.
Interpretation (business objective, acceptance criteria) happens downstream in
[`epics/`](epics/README.md) and [`stories/`](stories/README.md), not here. See
[`README.md`](README.md) for the workflow and [`CONTRIBUTING.md`](../../CONTRIBUTING.md)
for ID conventions.

Template for a new entry:

```markdown
## FB-NNN
- **Date:** YYYY-MM-DD
- **Source:** [specific person/role, "metric: <name>", "incident: <ref>", or
  "team hypothesis (no external request)"]
- **Raw request:** "..."
- **Derived story:** US-NNN  <!-- fill in once the story is written -->
- **Status:** unprocessed | converted | discarded (+ reason)
```

---

## FB-001
- **Date:** 2026-09-13
- **Source:** product owner
- **Raw request:** "supervisores ven heartbeats de PCs Operator y pantallas en tiempo real"
- **Derived story:** US-001
- **Status:** converted

_No entries yet — this is a fresh scaffold. Append the first `FB-001` above this line
the next time a real request comes in._
