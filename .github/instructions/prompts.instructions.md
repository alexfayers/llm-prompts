---
applyTo: "**/prompts/**/*.md"
excludeAgent: "cloud-agent"
---

# Prompt source review

## Wording

- Write terse RFC 2119 bullets. Flag filler, justification and restatement.
- Use MUST or MUST NOT for an absolute requirement, SHOULD or SHOULD NOT for a default with valid exceptions, and MAY for a free choice.
- Flag content specific to one person, repo or task. It belongs in memory.

## Placement

- A rule always applies. A skill is one process for one task. Flag content placed in the wrong one.
- Flag a new mandatory skill or skill part without a trigger line in `002-skill-usage`.
- Flag a directive that overlaps an existing rule or skill. Sharpen the most specific match in place instead.
- Flag a change that conflicts with another rule or skill, `CONTRIBUTING.md` or `.github/instructions/*`. Name the other file.
- Flag a new file where one sentence in an existing file would do.

## Skills

- A skill is a directory with `SKILL.md` and optional scripts. Its frontmatter `description` says what it does and when to use it.
- Add a task that fits an existing skill as a part: a sibling `<part>.md` listed in that skill's index, never named `SKILL.md`. Parts are rendered with the same variables as `SKILL.md`.
- A skill that a hook or an agent definition's skill list names keeps its own `SKILL.md`.
- Flag a skill step written as prose that a script could check or compute exactly. Put the script in the skill directory.

## Hooks

- Flag a new or changed rule, skill or agent directive that a hook could enforce deterministically. Name the hook event (before or after a tool, prompt submit, session start or stop, compaction) and the mechanism (a Claude Code hook that runs a cline-hooks plugin, or a Pi extension).
- Where the natural event fires only after the change lands, check whether an earlier event can predict the outcome from the tool's input. Only then accept that no hook can enforce it.

## Size

- Compression keeps every directive. Flag a dropped one.
- In llm-prompts, check sizes against `src/llm_prompts/size_limits.py` and the allowances declared in the repo. `llm-prompts check` and the CI size report measure them.
- Reject a file split or a ceiling raise made only to stay under a budget.

## Example

Avoid:

```markdown
- Always try to run the tests before you commit, because otherwise broken code might end up on main.
```

Prefer:

```markdown
- MUST run the full test suite before each commit.
```
