# Changelog

## [0.3.0](https://github.com/alexfayers/llm-prompts/compare/v0.2.0...v0.3.0) (2026-11-17)


### Features

* hide unused skills and tools in an attic, and test dropping rules ([#509](https://github.com/alexfayers/llm-prompts/issues/509)) ([4ae6be8](https://github.com/alexfayers/llm-prompts/commit/4ae6be8f1592d83073fb23ebc7f16b79ecc34ab3))
* **pi:** add a consult tool for a fresh-context, max-effort second opinion ([#516](https://github.com/alexfayers/llm-prompts/issues/516)) ([0257842](https://github.com/alexfayers/llm-prompts/commit/025784237a2bbb85d3566d9d0a744f3081aff06c))
* **pi:** add a reload_now tool ([#498](https://github.com/alexfayers/llm-prompts/issues/498)) ([fd59f72](https://github.com/alexfayers/llm-prompts/commit/fd59f7214870f12dca3ba2547bf5558be3b5d10a))
* **update:** keep local checkouts on the latest release ([#524](https://github.com/alexfayers/llm-prompts/issues/524)) ([ade466b](https://github.com/alexfayers/llm-prompts/commit/ade466bfaa598cea52cb85c2581bc7b3048eed85))


### Bug Fixes

* **benchmark:** judge pi with an inference profile and pin tool sources ([#515](https://github.com/alexfayers/llm-prompts/issues/515)) ([dc16665](https://github.com/alexfayers/llm-prompts/commit/dc16665739b92917393876ea9ac2bda63e41d720))
* **install:** compare the pinned pi with the pi on PATH ([#523](https://github.com/alexfayers/llm-prompts/issues/523)) ([fe22c3b](https://github.com/alexfayers/llm-prompts/commit/fe22c3b455204ceb1304d84f84af2d12de42fb66))
* **setup:** ignore tool.uv.sources for every installed tool ([#527](https://github.com/alexfayers/llm-prompts/issues/527)) ([9be70c5](https://github.com/alexfayers/llm-prompts/commit/9be70c508d9ff855ea49641986d0eda8eb65af9f))
* **setup:** name the file and parse error when config.toml is not valid TOML ([#522](https://github.com/alexfayers/llm-prompts/issues/522)) ([9975934](https://github.com/alexfayers/llm-prompts/commit/9975934f0a7c8b9e812e7710b4915feedf1313a1))
* **tests:** clear an inherited GIT_DIR before session fixtures run ([#518](https://github.com/alexfayers/llm-prompts/issues/518)) ([8cbaeba](https://github.com/alexfayers/llm-prompts/commit/8cbaeba2e2fce8c6ba5af3b8faf046239f728199))
* **tests:** ignore an inherited GIT_DIR ([#514](https://github.com/alexfayers/llm-prompts/issues/514)) ([84508c3](https://github.com/alexfayers/llm-prompts/commit/84508c390b502e9e47fb1c5252c0f1e45e328438))


### Miscellaneous Chores

* **deps:** update pi extensions ([#521](https://github.com/alexfayers/llm-prompts/issues/521)) ([23875d6](https://github.com/alexfayers/llm-prompts/commit/23875d61addf9f00d090226e905ec9f60ac47469))
* **deps:** update pi extensions ([#525](https://github.com/alexfayers/llm-prompts/issues/525)) ([985ab9e](https://github.com/alexfayers/llm-prompts/commit/985ab9e147a2715af6ba9276bb6629c4bd0b649d))
* **deps:** update pi extensions ([#526](https://github.com/alexfayers/llm-prompts/issues/526)) ([88ec716](https://github.com/alexfayers/llm-prompts/commit/88ec71650f6699a34a055268d7fe988ef25ffc2e))
* **deps:** update pi extensions ([#530](https://github.com/alexfayers/llm-prompts/issues/530)) ([4f00297](https://github.com/alexfayers/llm-prompts/commit/4f002978401a3945b25c58651903db9370240c75))
* sync shared files from llm-prompts-ci ([#529](https://github.com/alexfayers/llm-prompts/issues/529)) ([6614fa4](https://github.com/alexfayers/llm-prompts/commit/6614fa405e69142e363a7e10df0bf334ba776b95))

## [0.2.0](https://github.com/alexfayers/llm-prompts/compare/v0.1.0...v0.2.0) (2026-11-16)


### Features

* **prompts:** track gaps found in delivered work as issues ([#490](https://github.com/alexfayers/llm-prompts/issues/490)) ([6e85300](https://github.com/alexfayers/llm-prompts/commit/6e85300bec0c84dd356e9aa1eeed8685e6324ed3))


### Miscellaneous Chores

* **deps:** lock file maintenance ([#512](https://github.com/alexfayers/llm-prompts/issues/512)) ([d99d237](https://github.com/alexfayers/llm-prompts/commit/d99d237503f5d61000a8c750fe3a6642afbc773b))
* **deps:** update all non-major dependencies ([#489](https://github.com/alexfayers/llm-prompts/issues/489)) ([650178f](https://github.com/alexfayers/llm-prompts/commit/650178fd894897cc1eb68fc7de33c6b18257ee92))
* **deps:** update pi extensions ([#491](https://github.com/alexfayers/llm-prompts/issues/491)) ([923df94](https://github.com/alexfayers/llm-prompts/commit/923df9475f3ffb4bfe22462ba612d1bc78508a5e))
* **deps:** update pi extensions ([#494](https://github.com/alexfayers/llm-prompts/issues/494)) ([1bef9b7](https://github.com/alexfayers/llm-prompts/commit/1bef9b7a1c6ba46e907dc8216c550c9d470e2720))
* sync Copilot review rules from llm-prompts-ci ([#492](https://github.com/alexfayers/llm-prompts/issues/492)) ([2426e15](https://github.com/alexfayers/llm-prompts/commit/2426e15b77fd470c1106619198d67a0eb3037cd2))
* sync shared files from llm-prompts-ci ([#496](https://github.com/alexfayers/llm-prompts/issues/496)) ([55e1417](https://github.com/alexfayers/llm-prompts/commit/55e1417665d3ed9ce3f360bd497547da19126497))
* sync shared files from llm-prompts-ci ([#511](https://github.com/alexfayers/llm-prompts/issues/511)) ([03bf6fc](https://github.com/alexfayers/llm-prompts/commit/03bf6fc73e0327ed2b97b8c89c34bec9e8e38884))
