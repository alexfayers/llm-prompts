---
name: todos
description: Find outstanding TODOs across a workspace - scans TODO.md files and TODO/FIXME/HACK/XXX/BUG markers in code, then presents them grouped by file. Use whenever the user asks about TODOs, outstanding work, or "any todos in X".
---

# todos

Surface every outstanding TODO in a workspace: curated `TODO.md` entries and
in-code markers (`TODO`, `FIXME`, `HACK`, `XXX`, `BUG`).

## 1. Scan

Run the co-located scanner against the target directory (default: the current
workspace root):

```bash
python3 "<base-dir>/find_todos.py" [root]
```

It prints JSON:

- `todos`: list of `{file, line, type, task}` marker hits (paths relative to root)
- `todo_files`: paths of any `TODO.md` files found
- `files_scanned`: how many files were read

It walks the tree skipping hidden directories (`.git`, `.venv`, etc.) and a
small vendor-directory denylist (`node_modules`, `build`, `dist`, ...), so
third-party/generated content is excluded without needing `.gitignore`
parsing or a `git` dependency.

## 2. Read TODO.md files

For each path in `todo_files`, read it and pull out the still-open items. The
script only locates these files - you interpret their contents.

## 3. Present

Group by file, one heading per file, one line per item, each on its own line
(separate with `\n\n`):

```
## {file}
- {type}: `{task}` [{line}]
```

For `TODO.md`-sourced items use `TODO` as the type and omit `[{line}]` when
there's no meaningful line. If nothing is found, say so plainly.
