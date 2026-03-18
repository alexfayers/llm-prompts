# Coding guidelines

- Keep any resulting code concise but readable
- Any changes to code must be minimal
- Code must be self-documenting with minimal comments
  - NEVER add comments that refer to the changes you are making. Comments must only refer to the code and implementation itself.
  - Variable/function/method names must be descriptive
  - Comments should not be necessary in general
- Add new imports at THE SAME TIME as making code changes
- All produced code MUST follow the existing style within the package (variable names, documentation, etc.)
- NEVER use the `attempt_completion` tool until all tasks in the focus chain are completed.
- In ACT mode, never narrate or describe what you are about to do - just do it. If you need to plan, use `ask_followup_question` to ask the user to switch to PLAN mode.
- Code should be written with reusability and maintainability in mind at all times. If multiple functions do similar things, merge them into one or create an interface
- It is extremely important that you NEVER write comments explaining the reasoning for a specific change. Comments should only be used to explain complex code. If comments are required, consider a different approach.
- Avoid unnecessary variable assignment unless it improves the clarity of the code. If a variable is used once, it probably doesn't need to be a variable.
- Leave code better than you found it. If you notice an issue with something that you are already editing, fix it!
- Before adding a parameter to a function signature, verify it is actually used in the function body. Remove unused parameters.
- If you write code that contains an error and subsequently fix it, record the mistake and fix as a memory observation so the same error is not repeated in future sessions.
- When writing any text, NEVER use non-ascii characters such as emdash (`—`). Always use equivalent ascii characters, like `-`.

## Python

Unless otherwise specified:

- Type hints must be used for functions/methods, and for the initialization of empty collections (lists, sets, etc)
- Google style docstrings must be used to give a brief summary of functions and methods
- ruff for linting and formatting; always run with `--fix` first before manual edits
- mypy for type checking
- pytest for testing
- object oriented approach, one class per file unless classes are closely related (a small type stub is allowed in a file with another class, for example)
- follow SOLID principles
- keep code loosely decoupled - don't over engineer with middleware unless it makes sense, but follow single responsibility where possible
- within tests, pytest fixtures should be used to refactor out repeated code
- argparse should be used for command line argument parsing, with a function for building the parser and a function for doing the parsing and starting the program. This makes integrating testing easier later.
- Never catch an exception and do nothing with it
- When catching exceptions, only put the code that could raise the exception(s) in the try block.
- Imports **must** always be at the top of the file.
- Avoid using the `Any` type wherever possible. Use it only as a last resort or if explicitly told otherwise.

## Shell

- NEVER use the `-f` flag with the `rm` command. It is too high risk.
- NEVER use `rm -rf`. Use `rm -r` instead.

# Testing guidelines

- Before running tests, always ensure that there are tests that check for the expected behavior
- Tests should only cover our code. Do not test the functionality of built-in or external libraries.
- Test behavior, not syntax. For example, do not test that a config has specific defaults set.
- Never duplicate behavior in the test definition - always test the live code.
