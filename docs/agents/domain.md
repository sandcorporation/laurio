# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (most repos):

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence of `CONTEXT-MAP.md` at the root):

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## ADRs are history — only two files describe the present

**`CONTEXT.md` and the repo root's `CLAUDE.md` are the only documents that describe how
things are *now*.** Everything else — every ADR, `REQUEST.md`, every closed issue and spec
— records a judgement **as of the day it was written**.

Read an ADR for *why a decision was made*, never as a statement of current state. The same
goes for the "Problem Statement" of a spec issue: it describes the world the spec was
written to change, which by the time you read it may already have been changed.

**This bit us.** A session read the Problem Statement of a staging-integration spec —
"only one adapter is actually implemented" — and told the user that as current fact. It had
been true when the spec was written; by then all ten adapters were bound to real
implementations. The spec was still open only because a few execution sub-issues remained.

Every ADR carries a `Status:` line saying whether it still binds:

- `Status: Accepted (YYYY-MM-DD 결정)` — in force.
- `Status: Amended by ADR-XXXX (…)` — **still in force**, but a later ADR builds on or
  narrows part of it.
- `Status: Superseded by ADR-XXXX (…)` — no longer in force.

**Every ADR has one** — CI's `adr-status` job fails the build otherwise. That is what makes
"no marker" mean "nobody has amended this", rather than "nobody got around to it".

When you need to state a present fact — which adapters are real, which ports are used, what
a budget is — read `CLAUDE.md` or the code and config, not a document that was describing
its own moment.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
