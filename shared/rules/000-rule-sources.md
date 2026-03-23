# Rule Sources

When editing rules, workflows, prompts, or skills, always edit the **source files** in the repository - never edit the installed copies.

Source locations:
- Rules: `{{REPO_ROOT}}/shared/rules/` and `{{REPO_ROOT}}/cline/rules/`
- Workflows: `{{REPO_ROOT}}/shared/workflows/` and `{{REPO_ROOT}}/cline/workflows/`
- Skills: `{{REPO_ROOT}}/cline/skills/`
- Overlay (if configured): `{{REPO_ROOT}}/<overlay>/shared/rules/`, `{{REPO_ROOT}}/<overlay>/shared/workflows/`, `{{REPO_ROOT}}/<overlay>/cline/skills/`

After editing any source file, run `python3 {{REPO_ROOT}}/scripts/install.py` to reinstall.
