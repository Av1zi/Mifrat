# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## Status in the GitHub tracker

All five labels exist in `Av1zi/Mifrat` as of 2026-11-02, created with these colors:

| Label              | Color     | Description                                  |
| ------------------ | --------- | -------------------------------------------- |
| `needs-triage`     | `#d4c5f9` | Maintainer needs to evaluate this issue      |
| `needs-info`       | `#fbca04` | Waiting on reporter for more information     |
| `ready-for-agent`  | `#0e8a16` | Fully specified, ready for an AFK agent      |
| `ready-for-human`  | `#1d76db` | Requires human implementation                |
| `wontfix`          | `#ffffff` | This will not be worked on (GitHub default)  |

`wontfix` already existed as a GitHub default label; the other four were created. The repo also carries GitHub's default labels (`bug`, `enhancement`, `documentation`, `question`, `duplicate`, `dependencies`, `python`, `javascript`, …) — those are for human readers and are not part of the triage vocabulary.

