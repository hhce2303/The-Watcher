# Backlog — feedback-to-story traceability

This directory is the feature-intake half of this repo's decision governance. It is
deliberately separate from [`docs/architecture/adr/`](../architecture/adr/README.md):
ADRs record *why the system is built this way*; this backlog records *why this
feature exists* — who asked, what they actually need, and how you'll know it's done.
See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the full ID conventions and workflow.

## Structure

- [`feedback-log.md`](feedback-log.md) — every raw `FB-NNN` request, verbatim or a
  faithful paraphrase, before any interpretation.
- [`epics/`](epics/README.md) — one `EPIC-NNN.md` per business objective, each listing
  its stories.
- [`stories/`](stories/README.md) — one `US-NNN.md` per user story, with Gherkin
  acceptance criteria, linked back to its `FB-NNN` origin and `EPIC-NNN`.

## The non-negotiable rule

**No story is marked `done` without a Gherkin criterion that was actually verified**
(manually or by an automated test). **No story exists without an `FB-NNN` origin** —
if there's no real feedback behind it, it's the team's own hypothesis, and its
`feedback-log.md` entry must say so explicitly (`Source: team hypothesis (no external
request)`), never disguised as user-driven.

## Adding a new item

1. Append an `FB-NNN` entry to `feedback-log.md`.
2. Find or create the `EPIC-NNN` it belongs to under `epics/`.
3. Write the `US-NNN` story under `stories/` with Gherkin acceptance criteria.
4. Cross-link all three: `FB` → `Derived story`, `US` → `Epic` + `Feedback origin`,
   `EPIC` → its `Stories` list.

This directory is currently an empty scaffold (bootstrapped alongside
[`glossary.md`](../architecture/glossary.md) and [`nfr.md`](../architecture/nfr.md));
the first real `FB-001`/`EPIC-001`/`US-001` gets created the next time an actual
feature request comes in — not fabricated ahead of time.
