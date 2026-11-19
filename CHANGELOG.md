# Changelog

## [0.5.0](https://github.com/alexfayers/llm-prompts/compare/v0.4.0...v0.5.0) (2026-11-19)


### Features

* **benchmark:** show a live view of running cells on a terminal ([#562](https://github.com/alexfayers/llm-prompts/issues/562)) ([dd19498](https://github.com/alexfayers/llm-prompts/commit/dd19498e75bceaeb87f66bc02364964c484cb2e8))
* **pi-context:** let a setting allow extra MCP tools for delegates ([#555](https://github.com/alexfayers/llm-prompts/issues/555)) ([98a5b63](https://github.com/alexfayers/llm-prompts/commit/98a5b638d24f61dece0be31e07447bb4f9ad98da))
* **prompts:** test real-use states and check rule compressions ([#528](https://github.com/alexfayers/llm-prompts/issues/528)) ([780f692](https://github.com/alexfayers/llm-prompts/commit/780f6922e756da2afc5874c21d9782e00ffd49a2))
* **telemetry:** send each source's release tag in versions ([#559](https://github.com/alexfayers/llm-prompts/issues/559)) ([54b60dc](https://github.com/alexfayers/llm-prompts/commit/54b60dc253df94bdb418ed1179ad142255882dcd))


### Bug Fixes

* **install:** hand the update lock to the install --no-update child ([#552](https://github.com/alexfayers/llm-prompts/issues/552)) ([c7c08f8](https://github.com/alexfayers/llm-prompts/commit/c7c08f879bf40b9eab448f2f81fddb793b3e645c))
* **update:** show git's error when an update check fails ([#551](https://github.com/alexfayers/llm-prompts/issues/551)) ([1f80a99](https://github.com/alexfayers/llm-prompts/commit/1f80a9930cbfbdf6f429809057ab5e6657c466ee))


### Performance Improvements

* **update:** fetch each checkout once per update ([#560](https://github.com/alexfayers/llm-prompts/issues/560)) ([b7a42f5](https://github.com/alexfayers/llm-prompts/commit/b7a42f57154f734d75a44593bb9d54cd8bd64f9c))


### Miscellaneous Chores

* sync shared files from llm-prompts-ci ([#553](https://github.com/alexfayers/llm-prompts/issues/553)) ([5c6c18c](https://github.com/alexfayers/llm-prompts/commit/5c6c18cf39d0f429c845c017eb3ef51bf39a4392))

## [0.4.0](https://github.com/alexfayers/llm-prompts/compare/v0.3.0...v0.4.0) (2026-11-18)


### ⚠ BREAKING CHANGES

* **pi:** delegate to cache-sharing forks and cut token use, retiring herdsman ([#513](https://github.com/alexfayers/llm-prompts/issues/513))

### Features

* **pi:** accept a tier name as a fork's model ([#540](https://github.com/alexfayers/llm-prompts/issues/540)) ([16d5d11](https://github.com/alexfayers/llm-prompts/commit/16d5d1165ac17923081a5352b645a3fbe82fd965))
* **pi:** add checkpoint extension ([#488](https://github.com/alexfayers/llm-prompts/issues/488)) ([dd08350](https://github.com/alexfayers/llm-prompts/commit/dd08350ed907ab38627b295c6d3fcf60e8d75821))
* **pi:** delegate to cache-sharing forks and cut token use, retiring herdsman ([#513](https://github.com/alexfayers/llm-prompts/issues/513)) ([694f04d](https://github.com/alexfayers/llm-prompts/commit/694f04d07ba9efe5c7c2f9bebf116e652263e25c))
* **prompts:** tighten author rules to avoid review rework ([#482](https://github.com/alexfayers/llm-prompts/issues/482)) ([51635ac](https://github.com/alexfayers/llm-prompts/commit/51635ac033e8ba9405c68a26de4763e829603765))
* **update:** hold the background update while a pi fork runs and say to reload ([#542](https://github.com/alexfayers/llm-prompts/issues/542)) ([751f6b4](https://github.com/alexfayers/llm-prompts/commit/751f6b4f6ae0ebc44f31488ebac29d25bc5e5e3c))
* **update:** update automatically at session start ([#533](https://github.com/alexfayers/llm-prompts/issues/533)) ([42eb4eb](https://github.com/alexfayers/llm-prompts/commit/42eb4eb93c00f1299560c2c55354d46a49421da2))


### Bug Fixes

* **pi:** accept an OUTCOME line with text after its ref ([#539](https://github.com/alexfayers/llm-prompts/issues/539)) ([2a7b94a](https://github.com/alexfayers/llm-prompts/commit/2a7b94aa05da25161b86785cd601f53fd7ef73b0))
* **pi:** send a warm fork main's system prompt and tools so it reads main's prompt cache ([#541](https://github.com/alexfayers/llm-prompts/issues/541)) ([51ac511](https://github.com/alexfayers/llm-prompts/commit/51ac511c6c7c0fc0077c53b4b284aa9e81fdbaf8))
* **update:** drop empty copies of merged pull requests from a current main ([#537](https://github.com/alexfayers/llm-prompts/issues/537)) ([6403574](https://github.com/alexfayers/llm-prompts/commit/64035741cc4c8300e6a217022eeac82589d1083a))
* **update:** drop local copies of merged pull requests when syncing main ([#536](https://github.com/alexfayers/llm-prompts/issues/536)) ([2f09b22](https://github.com/alexfayers/llm-prompts/commit/2f09b229aeb4b9a0e337d8efe6e3b5a0ccb894c7))
* **update:** skip closed pull requests when looking for a commit's open copy ([#534](https://github.com/alexfayers/llm-prompts/issues/534)) ([c24f68c](https://github.com/alexfayers/llm-prompts/commit/c24f68cd6adea2034a17b8f41cf97466c56ca7b4))


### Miscellaneous Chores

* **deps:** update pi extensions ([#531](https://github.com/alexfayers/llm-prompts/issues/531)) ([74fe711](https://github.com/alexfayers/llm-prompts/commit/74fe7118d254dc2f316fd32c6fca7d56a07abd34))

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
