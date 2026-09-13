# Stories

One `US-NNN.md` per user story, with Gherkin acceptance criteria. See
[`../README.md`](../README.md) for the full workflow.

Template for `US-NNN.md`:

```markdown
# US-NNN: [Short title]
- **Epic:** EPIC-NNN
- **Feedback origin:** FB-NNN
- **Related ADR:** ADR-NNNN  <!-- omit this field entirely if none applies -->
- **As a** [role — Operator | IT | Supervisor], **I want** [goal], **so that** [benefit]

## Acceptance criteria

​```gherkin
Scenario: [name]
  Given ...
  When ...
  Then ...
​```

- **Priority:** [whatever scheme the project adopts — RICE, ICE, MoSCoW; ask once if
  none exists yet, then use it consistently]
- **Status:** proposed | accepted | in-progress | done | superseded by US-NNN
```

Write acceptance criteria in Gherkin even when no automated test will ever run
against them — Given/When/Then forces a concrete, checkable definition instead of a
vague "works well" nobody can close out with confidence. **No story is marked `done`
without a Gherkin criterion that was actually verified.**

_No stories yet — this is a fresh scaffold._
