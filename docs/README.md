# Documentation map

Read the smallest guide that covers the task. Current instructions live in the
guides below; dated evidence and old proposals are not instructions to rerun.

## Current guides

| Task | Read |
|---|---|
| Start here; run locally; check scraping permission | [Root README](../README.md) |
| Understand the system and its boundaries | [Project overview](../PROJECT_OVERVIEW.md) |
| Use the project's terms | [Glossary](../GLOSSARY.md) |
| Change typed specs, source trust or schema | [Specs](../scraper/specs/README.md) |
| Fetch manufacturer specs | [Manufacturer sources](../scraper/mfr/README.md) |
| Use syndicated spec sheets | [Open Icecat](../scraper/icecat/README.md) |
| Extract quoted facts with a model | [Verified extraction](../scraper/extract/README.md) |
| Develop, test or deploy the frontend | [Site](../site/README.md) |
| Set up or diagnose the home machine | [Nano](../nano/NANO_README.md) |
| Understand snapshot/image storage | [Raw data](../data/raw/RAW_README.md) |
| Configure the console and daily phone report | [Operations](ops-alerts.md) |
| Investigate the paused KSP transport | [KSP stream status](ksp-stream-transport.md) |
| Understand KSP detail ingestion | [KSP detail](ksp-detail-plan.md) |

Local-only `AGENTS.md` gives agent operating instructions; `decisions.md` holds
current binding decisions and open constraints. Both are gitignored. Their
private backup/history must remain local-only.

## Plans and evidence

- [Identity design](merge-identity-plan.md): shipped Nov 6 proposal. Later
  packaging, alias and evidence-connectivity refinements supersede parts of it;
  use the current overview and `scraper/identity.py` for present behaviour.
- [Architecture deepening](architecture-deepening-plan.md): proposed work,
  not permission to implement it during another task.
- [QA automation plan — Nov 23](qa-automation-plan-2026-11-23.md): proposed
  evidence-based parsing, matching and QA automation; not implementation approval.
- [Duplicate audit](duplicate-groups-audit.md): completed Nov 7–8 evidence.
- [Nov 10 audit](audits/2026-11-10/README.md) and
  [Nov 12 re-audit](audits/2026-11-12-reaudit/README.md): pinned findings, not
  live counts; the re-audit is explicitly partial.
- `ops-cleanup/` and `qa-resolution/`: dated changes and remaining findings.
- `prompts/`: instructions for separately authorized audit/QA sessions.
- [Pre-cleanup documentation](archive/2026-11-22/README.md): preserved long
  references and evidence; load only when historical detail matters.

## Keeping docs small

- Give each rule one authoritative home; link instead of repeating it.
- Keep setup steps and current caveats in active guides. Put dated evidence in
  dated reports, and commit history in git rather than growing status logs.
- Look up script names, thresholds and bindings in code/config unless a guide
  needs the value to explain a safety rule or a runnable procedure.
- Split only for a distinct task. A new file should remove a real reading
  burden, not merely move a wall of text elsewhere.
- After moving content, verify the pointers and preserve unique evidence.
