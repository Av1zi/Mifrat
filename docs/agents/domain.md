# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root, or
- **`GLOSSARY-MAP.md`** at the repo root if it exists: it points at one `GLOSSARY.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (most repos):

```
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

Multi-context repo (presence of `GLOSSARY-MAP.md` at the root):

```
/
├── GLOSSARY-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── GLOSSARY.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── GLOSSARY.md
        └── docs/adr/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

## Repo-specific notes

- **Layout: single-context.** This repo has no `pnpm-workspace.yaml`, no `workspaces` field, and no `packages/*` — `site/` is a nested npm project driven by the root `package.json` scripts, not a workspace member. One root `GLOSSARY.md` plus `docs/adr/` is the layout.
- **Neither `GLOSSARY.md` nor `docs/adr/` exists yet.** That is expected: `/domain-modeling` creates them when terms or decisions actually get resolved. Don't scaffold them upfront.
- **`decisions.md` is the de-facto decision log today.** It is local and gitignored, and the repo rule is that every important change gets an entry there. Read it before proposing changes to the pipeline, spec tiers, image rules, or site behaviour, and add a one-line entry for any important change. When a decision is big enough to deserve an ADR, record it in `docs/adr/` as well and keep the `decisions.md` line as the index entry.
- **Language lives in `PROJECT_OVERVIEW.md` and `decisions.md`, not a glossary.** Until `GLOSSARY.md` exists, take existing vocabulary (vendor, spec tier, normalize, catalog, …) from those two files rather than inventing new terms.
- `docs/agents/` holds agent-tooling configuration (issue tracker, triage labels, this file). It is agent setup, not domain documentation — don't put pipeline knowledge in it.
