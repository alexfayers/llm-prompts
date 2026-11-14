---
roles: lead, reasoner, worker, reviewer
paths: '**/prompts/**/*, **/.claude/rules/*.md, **/.claude/skills/**/*, **/llm-prompts/config.toml'
kiro_inclusion: manual
---

# Rule Sources

When editing rules, workflows, prompts, or skills, always edit the **source files** in the repository - never edit the installed copies.

Rules and skills must be as terse as possible - short bullets only. Explain only where the rule would otherwise be ambiguous; prose that justifies or restates a rule is deleted, not shortened.
Where a document's reader is a MODEL (a prompt-injected context blob, an instruction file), MUST write RFC 2119 directives, not explanatory prose - cut justification and background, keep every identifier. Reduce words, never coverage.

These files are distributed and always loaded, so content MUST be generic - useful to MULTIPLE different people in MULTIPLE different situations.
Anything specific to one person, one incident, one repo, or one past conversation MUST NOT go here; it belongs in memory or in local unmanaged rules.
Before adding a rule, MUST check it would still read correctly in an unrelated repo for a different person.

{% if AGENT == "pi" %}
After changing pi extensions, packages, settings, agent definitions or AGENTS.md, MUST tell the user to run `/reload`. `/reload` refreshes the current session only. New sessions and delegates pick up changes on their own. The user MAY `/reload` while delegates are running.
A new pi extension MUST start with a `// <one-sentence summary>` header, optionally followed by `// Commands:`, `// Config:` and `// Env:` lines.
Changes that invalidate a hand-written `pi-help` fact MUST update that fact.
{% endif %}
