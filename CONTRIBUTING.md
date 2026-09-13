# Contributing

This file records the decision-governance and feature-intake conventions this repo
already follows in practice ([ADRs](docs/architecture/adr/), `TODOS.md`, this PR
history), made explicit so new contributors and AI sessions don't have to reconstruct
them from git log archaeology.

## Core principles

1. **Decision-first.** No structural decision ships without an accepted ADR; no
   feature ships without a story that traces back to a real request (see
   [`docs/backlog/`](docs/backlog/README.md)). If something doesn't fit an existing decision or
   an existing epic, propose a new one — don't adjust silently.
2. **Records are append-only.** ADR and story lifecycle is
   `proposed → accepted → superseded` / `done`. Never delete one. Mark it and keep
   the historical record — the abandoned reasoning (e.g. [ADR-0007](docs/architecture/adr/ADR-0007-dxgi-capture-deferred.md),
   deferred, later resolved by [ADR-0017](docs/architecture/adr/ADR-0017-adr0007-sla-verdict-confirmed.md))
   is often more valuable than the path taken.
3. **Clarify before drafting.** When scope, naming, or a decision is ambiguous, ask.
4. **Cross-artifact consistency is mandatory.** Renaming a term, closing an ADR, or
   converting feedback into a story propagates to every affected document
   ([`glossary.md`](docs/architecture/glossary.md), [`nfr.md`](docs/architecture/nfr.md),
   `AGENTS.md`, `TODOS.md`) in the same change.
5. **Stable IDs everywhere.** `ADR-0001`, `NFR-Perf-1`, `R-1`, `TD-1`, `EPIC-001`,
   `US-001`, `FB-001`. See the ID conventions table below.
6. **Confirm scope before cascading changes.** Renames and restructurings that touch
   multiple files get explicit approval first.
7. **Write for machine consumption too.** Structured tables, explicit invariants, one
   source of truth per fact — a human skimming and an AI agent parsing should reach
   the same conclusion. See `AGENTS.md`.

## ADR template and lifecycle

One structural decision per file, under `docs/architecture/adr/`, numbered
`ADR-NNNN` (zero-padded, sequential, permanent — a superseded ADR keeps its number).
Registered in [`adr/README.md`](docs/architecture/adr/README.md).

```markdown
# ADR-NNNN — [Short decision title]

- **Estado**: Propuesto | Aceptado | Diferido | superseded by ADR-NNNN
- **Fecha**: YYYY-MM-DD
- **Requisitos**: [R-N / NFR-<área>-N this decision serves, if any]

## Contexto
## Decisión
## Consecuencias
## Opciones no elegidas
```

This is the format every existing ADR in the repo actually uses (`Estado`/`Fecha`/
`Requisitos` fields, em-dash title, no `Deciders` field) — match it exactly rather
than the more generic MADR template, so the 19 existing ADRs and any new one read as
one consistent series. Existing ADRs are written in Spanish (the project's
documentation language for architecture artifacts); keep new ones consistent with
that unless the team decides otherwise. One decision per ADR — if the title needs an
"and," it's probably two.
Consequences must include the negatives: an ADR listing only benefits hasn't
evaluated a trade-off. Deferred decisions are legitimate accepted ADRs
(see [ADR-0007](docs/architecture/adr/ADR-0007-dxgi-capture-deferred.md),
[ADR-0018](docs/architecture/adr/ADR-0018-go-liveview-relay-escalation-deferred.md)).

## ID conventions

| Prefix | Scope | Lives in |
|---|---|---|
| `ADR-NNNN` | Structural/architectural decision | `docs/architecture/adr/` |
| `R-N`, `R-NFN` | Functional/non-functional requirement scoped to the editor tab | `docs/architecture/goals.md` |
| `NFR-<área>-N` | Project-wide non-functional requirement | `docs/architecture/nfr.md` |
| `TD-N` | Technical-debt / risk register entry (Tauri migration) | `docs/migration/tech-debt-and-best-practices.md` |
| `EPIC-NNN` | Business objective grouping one or more stories | `docs/backlog/epics/` |
| `US-NNN` | User story with Gherkin acceptance criteria | `docs/backlog/stories/` |
| `FB-NNN` | Raw feedback-log entry (who asked, what, when) | `docs/backlog/feedback-log.md` |

## Feature intake (feedback-to-backlog)

Any time someone reports an external request — "a user asked for X," a support
ticket, an incident — it goes through `docs/backlog/` before it becomes code, not
straight into an implementation PR:

1. Log the raw ask as an `FB-NNN` entry in [`docs/backlog/feedback-log.md`](docs/backlog/feedback-log.md) —
   who asked, in their own words, not your interpretation of it yet.
2. Place it under an existing `EPIC-NNN` or open a new one
   ([`docs/backlog/epics/`](docs/backlog/epics/README.md)) with a concrete business objective.
3. Write the `US-NNN` story ([`docs/backlog/stories/README.md`](docs/backlog/stories/README.md))
   with Gherkin acceptance criteria. No story is marked `done` without a Gherkin
   criterion that was actually verified.
4. Cross-link all three (`FB` → `US`, `US` → `EPIC`, `EPIC` → its `US-*` list).

A feature with no real request behind it is a legitimate hypothesis, but it must be
labeled `team hypothesis (no external request)` in its `FB-NNN` entry, never disguised
as user-driven.

## Where things live (don't duplicate — link)

- Architecture decisions: [`docs/architecture/adr/`](docs/architecture/adr/README.md)
- Domain terms: [`docs/architecture/glossary.md`](docs/architecture/glossary.md)
- Non-functional requirements: [`docs/architecture/nfr.md`](docs/architecture/nfr.md)
  (project-wide) and [`docs/architecture/goals.md`](docs/architecture/goals.md) (editor tab)
- Open decisions / known risks: [`TODOS.md`](TODOS.md)
- Feature backlog: [`docs/backlog/`](docs/backlog/README.md)
- AI-agent entry point: [`AGENTS.md`](AGENTS.md)
- Tauri migration deep-dives: [`docs/migration/`](docs/migration/README.md)

If you're about to write a fact that already lives in one of these, link to it
instead of restating it — a copied fact is a fact that will drift.
