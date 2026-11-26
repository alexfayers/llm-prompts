---
roles: lead, worker, reviewer
---

# Git

- A logical change is one change that you could revert on its own, and the code would still work.
- Each logical change MUST be one commit. If one commit describes what another does, they are the SAME logical change and MUST be one commit, even across unrelated files.
- A PR SHOULD be one self-contained feature or fix, with its tests. Each commit MUST build and pass on its own.
- ~100 changed lines is usually fine and ~1000 usually too large. This is a guideline, not a target, and the reviewer decides.
- Many files make a change bigger. A deleted file or a trusted tool-generated refactor counts as small.
- Refactors SHOULD go in a separate PR.
- One logical change stays one commit.
