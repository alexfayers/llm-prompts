---
applyTo: "**/*.{ts,tsx,js,mjs}"
excludeAgent: "cloud-agent"
---

# TypeScript and JavaScript review

## Tests

- Load a Pi extension in a test with `loadExtension` and the fakes in `tests/ts/helpers.ts`.
- In cline-hooks, test `extension.ts` from `tests/test_pi_extension.py` through `tests/pi_extension_harness.mjs`.
