# Rule Sources - Copilot-specific

**Mechanical trip-wire:** if the file you are about to edit lives under `~/.copilot/`, stop. That path is an installed artifact, not a source file. Locate the real source with `llm-prompts source copilot`, edit the source repository instead, then reinstall with `llm-prompts update`.