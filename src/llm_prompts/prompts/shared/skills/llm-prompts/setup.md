# llm-prompts setup

- MUST use the installed `llm-prompts` (PATH), never `uv run llm-prompts` - it can miss overlays and delete their installed files.
- `llm-prompts setup` is for initial setup only. `llm-prompts update` reinstalls every tool, including local changes, from its sources.
- Config is at `~/.config/llm-prompts/config.toml` - run `llm-prompts setup --init` to create it.

## Adding a tool

- To add an overlay package, mcp-memory or cline-hooks, add a `[[tools]]` entry to the config:

  ```toml
  [[tools]]
  name = "<package-name>"
  source = "<git-url-or-local-path>"
  ```

- `source` MUST be a pip-installable reference: `git+https://github.com/user/repo.git`, `git+ssh://host/path/to/repo` or a local path (`~/path/to/repo`). Given a repository web URL, MUST convert it to a `git+https://` or `git+ssh://` URL.
- Memory: `name = "mcp-memory"`, `source = "git+https://github.com/alexfayers/mcp-memory.git"`.
- Lifecycle hooks: `name = "cline-hooks"`, `source = "git+https://github.com/alexfayers/cline-hooks.git"`.
- Then run `llm-prompts setup` to install it, followed by `llm-prompts install <agent>` to apply its rules, workflows and skills.
