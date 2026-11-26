# Changelog

## [0.9.0](https://github.com/alexfayers/llm-prompts/compare/v0.8.0...v0.9.0) (2026-11-26)


### ⚠ BREAKING CHANGES

* **contribute:** stop stacking same-repo PRs and keep hand edits across syncs ([#497](https://github.com/alexfayers/llm-prompts/issues/497))

### Features

* **ask-codex:** review through a GPT fork on pi ([#617](https://github.com/alexfayers/llm-prompts/issues/617)) ([1f02acc](https://github.com/alexfayers/llm-prompts/commit/1f02acc7b2370be45c8d6424e28b682cfb5f03af))
* **benchmark:** measure a pi feature on and off with --feature ([#728](https://github.com/alexfayers/llm-prompts/issues/728)) ([fc42d7c](https://github.com/alexfayers/llm-prompts/commit/fc42d7cd90d269ac2a43111a506450c19dbbf69f))
* **checkpoint:** end a rewind fold with a reminder to keep using checkpoints ([#688](https://github.com/alexfayers/llm-prompts/issues/688)) ([f81fa3c](https://github.com/alexfayers/llm-prompts/commit/f81fa3c5f9dccfd092de208eed0adc548f4e7120))
* **checkpoint:** suggest a rewind when folding a long run costs less than carrying it ([#692](https://github.com/alexfayers/llm-prompts/issues/692)) ([790ecb8](https://github.com/alexfayers/llm-prompts/commit/790ecb85446aa2ac27efc31772cf1a4eaad56217))
* **claude-code:** set CLAUDE_CODE_ENABLE_TODO_TOOLS in Claude Code settings on install ([#740](https://github.com/alexfayers/llm-prompts/issues/740)) ([6ff33ea](https://github.com/alexfayers/llm-prompts/commit/6ff33eab71dba87b0cc26953dbe1d3a0f4048696))
* **commit-guard:** skip a test run when the files and tool versions already passed ([#695](https://github.com/alexfayers/llm-prompts/issues/695)) ([ff8486e](https://github.com/alexfayers/llm-prompts/commit/ff8486e93ed77cf303dc9e6e8fab63724717d533))
* **contribute:** check a PR body against the template before it is pushed ([#711](https://github.com/alexfayers/llm-prompts/issues/711)) ([70303f0](https://github.com/alexfayers/llm-prompts/commit/70303f0ac7c537c4c16058c11287abb754cf3499))
* **contribute:** link a dependency on a PR in any repo with --depends-on ([#545](https://github.com/alexfayers/llm-prompts/issues/545)) ([a61fc61](https://github.com/alexfayers/llm-prompts/commit/a61fc618707e980dfdfebee11ce8d61ead15e5e3))
* **contribute:** mark a PR ready with owner-reviewed and auto-merge in one step ([#725](https://github.com/alexfayers/llm-prompts/issues/725)) ([9eb6f86](https://github.com/alexfayers/llm-prompts/commit/9eb6f86d2a3a3cdc91da56c61f5a69664bef6cc5))
* **contribute:** stop stacking same-repo PRs and keep hand edits across syncs ([#497](https://github.com/alexfayers/llm-prompts/issues/497)) ([c98129b](https://github.com/alexfayers/llm-prompts/commit/c98129b52a9547a703fec6ef40fb5041c50eb352))
* **delegation:** reuse a warm fork before starting a cold one ([#690](https://github.com/alexfayers/llm-prompts/issues/690)) ([d2c3756](https://github.com/alexfayers/llm-prompts/commit/d2c3756a5a9e88d0fdd95a10252703136b55b78a))
* fail prompt sources with a prose line over 200 characters ([#546](https://github.com/alexfayers/llm-prompts/issues/546)) ([9bc318b](https://github.com/alexfayers/llm-prompts/commit/9bc318bfcf1b124bfdd87df7d8a85c1bf77e4144))
* **guards:** drop -e from set calls instead of blocking them ([#752](https://github.com/alexfayers/llm-prompts/issues/752)) ([89ee612](https://github.com/alexfayers/llm-prompts/commit/89ee6124ee7a70834e52797188831b5284cc2b1f))
* **install:** join Claude Code rules into one file in a fixed order ([#745](https://github.com/alexfayers/llm-prompts/issues/745)) ([738a27c](https://github.com/alexfayers/llm-prompts/commit/738a27cab9e2a12d4fbd34b31841cb2aae12c82b))
* keep few reviews in flight at once ([#578](https://github.com/alexfayers/llm-prompts/issues/578)) ([98e5964](https://github.com/alexfayers/llm-prompts/commit/98e5964faaa1c5b817eb7bc64d52562404bc189c))
* let a rule load only when its load_when condition holds or a paths file is read (+1 more) ([#571](https://github.com/alexfayers/llm-prompts/issues/571)) ([a6fa9dc](https://github.com/alexfayers/llm-prompts/commit/a6fa9dcf9a14e9f893b4c429314980a118ef9820))
* **pi-context:** cap each fork's memory and CPU in a systemd scope ([#718](https://github.com/alexfayers/llm-prompts/issues/718)) ([6e562de](https://github.com/alexfayers/llm-prompts/commit/6e562de22a1b927c14824d65b1812201dba9e4b3))
* **pi-context:** copy only history after the last compaction in warm forks ([#705](https://github.com/alexfayers/llm-prompts/issues/705)) ([f23431a](https://github.com/alexfayers/llm-prompts/commit/f23431a2be2104cce7be466eac2958edbb6d9878))
* **pi-context:** fork from a finished fork's session ([#625](https://github.com/alexfayers/llm-prompts/issues/625)) ([a6dff65](https://github.com/alexfayers/llm-prompts/commit/a6dff656a111fbb605e2613380ef7904246bf681))
* **pi-context:** keep 600 characters of a fork's summary in its result ([#666](https://github.com/alexfayers/llm-prompts/issues/666)) ([2e02dcf](https://github.com/alexfayers/llm-prompts/commit/2e02dcf301a1f22fbd23214835ee95d9ac11c251))
* **pi-context:** queue a fork over a configurable live limit ([#674](https://github.com/alexfayers/llm-prompts/issues/674)) ([d271d34](https://github.com/alexfayers/llm-prompts/commit/d271d34d8facec6b75eddc8979c8a96f4ccd0a01))
* **pi-context:** resume a finished fork when fork_steer names it ([#673](https://github.com/alexfayers/llm-prompts/issues/673)) ([1bdff01](https://github.com/alexfayers/llm-prompts/commit/1bdff01d8ad0776a73e9c1b75abeae49345a3fc4))
* **pi-context:** run every fork in the background ([#676](https://github.com/alexfayers/llm-prompts/issues/676)) ([cc2c01d](https://github.com/alexfayers/llm-prompts/commit/cc2c01d9b054b6c0b47c3e859552fcea0d21fd2d))
* **pi-context:** start a fork over 150k tokens of context cold with a summary ([#710](https://github.com/alexfayers/llm-prompts/issues/710)) ([3c35ec5](https://github.com/alexfayers/llm-prompts/commit/3c35ec5731feb40fcf255b27a6030dd83b6e4c0e))
* **pi-context:** start no language server in a read-only fork ([#708](https://github.com/alexfayers/llm-prompts/issues/708)) ([7d620e4](https://github.com/alexfayers/llm-prompts/commit/7d620e4ac6a179fb8348f6975a2ee4d1545f9c0c))
* **pi:** delegates end with a typed reply tool ([#749](https://github.com/alexfayers/llm-prompts/issues/749)) ([1fecdd8](https://github.com/alexfayers/llm-prompts/commit/1fecdd8683063a7ef4c77b88763e971f29237fd7))
* **pi:** move the pi.dev curl install to the npm install on update ([#685](https://github.com/alexfayers/llm-prompts/issues/685)) ([8b4c408](https://github.com/alexfayers/llm-prompts/commit/8b4c40892b8284041391de3431696e130c410a7f))
* **plugins:** install agents shipped by plugin checkouts ([#748](https://github.com/alexfayers/llm-prompts/issues/748)) ([624ac2c](https://github.com/alexfayers/llm-prompts/commit/624ac2cbd17d68071870520af931cf9ae0633106))
* **pr-review:** add a review loop guide with a stop rule ([#626](https://github.com/alexfayers/llm-prompts/issues/626)) ([a2b0b98](https://github.com/alexfayers/llm-prompts/commit/a2b0b98c5188e2d963fd63ab83a85a3bfd92cd96))
* **pr-review:** narrow re-review rounds to the fix and its regressions ([#707](https://github.com/alexfayers/llm-prompts/issues/707)) ([ba41e8e](https://github.com/alexfayers/llm-prompts/commit/ba41e8ec59622c8c92d361cda321392adbb7acec))
* **pr-review:** shrink your own diff before pushing ([#580](https://github.com/alexfayers/llm-prompts/issues/580)) ([3c78ee5](https://github.com/alexfayers/llm-prompts/commit/3c78ee51033525f411f442d29df445f0015a4659))
* **pr:** add a pr command that checks size, rebases and readies a PR ([#727](https://github.com/alexfayers/llm-prompts/issues/727)) ([349d522](https://github.com/alexfayers/llm-prompts/commit/349d5223ad9491656442ac1d2e454a915bb2feca))
* **prompts:** require jq to parse JSON instead of inline scripts ([#747](https://github.com/alexfayers/llm-prompts/issues/747)) ([509a5d6](https://github.com/alexfayers/llm-prompts/commit/509a5d6fbe9534b2f4626e1c40c5208afa461750))
* **pr:** review and fix a PR through pi or claude before marking it ready ([#733](https://github.com/alexfayers/llm-prompts/issues/733)) ([ff0f76c](https://github.com/alexfayers/llm-prompts/commit/ff0f76cecec255a7a363b8c22fe407a9f3dd7151))
* **size-guard:** name the amount to cut in a prompt-size block ([#684](https://github.com/alexfayers/llm-prompts/issues/684)) ([000c088](https://github.com/alexfayers/llm-prompts/commit/000c088683a9ac9bdbcfc4a62fe057f9322c55ae))
* **watch:** gh-pr follows every open PR of an author ([#714](https://github.com/alexfayers/llm-prompts/issues/714)) ([b1fb84d](https://github.com/alexfayers/llm-prompts/commit/b1fb84d5e2fee7dd3af2a70a98f03cbd8978b4db))


### Bug Fixes

* **contribute:** leave merge commits out of the PR What list ([#621](https://github.com/alexfayers/llm-prompts/issues/621)) ([4d3952a](https://github.com/alexfayers/llm-prompts/commit/4d3952a2365e2ce8013bb053d42e90547ff4a138))
* **install:** read the pi that sessions run for the version drift check ([#679](https://github.com/alexfayers/llm-prompts/issues/679)) ([f992295](https://github.com/alexfayers/llm-prompts/commit/f9922951f88ebfcf5c80e572900bfb2194e089dd))
* **pi-context:** accept an OUTCOME line that opens with an emoji ([#627](https://github.com/alexfayers/llm-prompts/issues/627)) ([327afc9](https://github.com/alexfayers/llm-prompts/commit/327afc915d746be769e81f6ead8b54bc72686ce7))
* **pi-context:** clear handled forks from the background forks widget and show their source ([#691](https://github.com/alexfayers/llm-prompts/issues/691)) ([568c172](https://github.com/alexfayers/llm-prompts/commit/568c1728ca4fc9dcfa2a05b996f270259a80b417))
* **pi-context:** keep the bridge socket path short ([#629](https://github.com/alexfayers/llm-prompts/issues/629)) ([080337d](https://github.com/alexfayers/llm-prompts/commit/080337de258dfe539e50671d69afc0ccc5c06cb7))
* **pi-context:** land a writer on the remote branch it already pushed to ([#667](https://github.com/alexfayers/llm-prompts/issues/667)) ([78014af](https://github.com/alexfayers/llm-prompts/commit/78014af8ea109c016a09665a8bd3794f35df07a8))
* **pi-context:** land a writer that folded a fixup into a PR branch commit ([#669](https://github.com/alexfayers/llm-prompts/issues/669)) ([31ffb45](https://github.com/alexfayers/llm-prompts/commit/31ffb4520ae660adf353784ad98f80f57bae802a))
* **pi:** show live fork count and context tokens in the context-total status bar ([#734](https://github.com/alexfayers/llm-prompts/issues/734)) ([e45df99](https://github.com/alexfayers/llm-prompts/commit/e45df99c05441e7f1f23981c622c402917aba544))
* **setup:** reinstall a tool when its configured source changes ([#670](https://github.com/alexfayers/llm-prompts/issues/670)) ([9727749](https://github.com/alexfayers/llm-prompts/commit/97277492e52686769047eec78dbf51f92f8500e1))
* **tower-do-slim:** stop board notes in forks and note each revision once ([#703](https://github.com/alexfayers/llm-prompts/issues/703)) ([a669e2e](https://github.com/alexfayers/llm-prompts/commit/a669e2ebe32133f5ce7a34da72dc65fad1549af1))
* **watch:** gh-pr ignores cancelled checks when deciding ci=fail ([#723](https://github.com/alexfayers/llm-prompts/issues/723)) ([499d9d5](https://github.com/alexfayers/llm-prompts/commit/499d9d5c88226f58e4cdb0a6fbaca2ba6118d618))
* **watch:** gh-pr matches a check across rerun attempts ([#738](https://github.com/alexfayers/llm-prompts/issues/738)) ([03f61d7](https://github.com/alexfayers/llm-prompts/commit/03f61d79c253f7687c0f5d80a785c0096a5a6d31))


### Performance Improvements

* answer contribute sync history reads from one snapshot ([#724](https://github.com/alexfayers/llm-prompts/issues/724)) ([97a4132](https://github.com/alexfayers/llm-prompts/commit/97a41325060cbf000a698789c5a0995a963b6a4c))
* cut git spawns in contribute sync ([#719](https://github.com/alexfayers/llm-prompts/issues/719)) ([107769c](https://github.com/alexfayers/llm-prompts/commit/107769c11ffddb0dd17dade07164ffae20251809))
* **tower-do:** fold the task board file only when it changes ([#726](https://github.com/alexfayers/llm-prompts/issues/726)) ([bdfc08f](https://github.com/alexfayers/llm-prompts/commit/bdfc08ffa739a4f905ee471e2fdb13e0465c244c))


### Miscellaneous Chores

* **deps:** update all non-major dependencies ([#628](https://github.com/alexfayers/llm-prompts/issues/628)) ([df54a9a](https://github.com/alexfayers/llm-prompts/commit/df54a9a2e1a809b56e4c4a88697181b7afac0109))
* sync shared files from llm-prompts-ci ([#624](https://github.com/alexfayers/llm-prompts/issues/624)) ([0202fcb](https://github.com/alexfayers/llm-prompts/commit/0202fcbd1424c14022aa41026e0d10ce19b6ddc1))

## [0.8.0](https://github.com/alexfayers/llm-prompts/compare/v0.7.0...v0.8.0) (2026-11-25)


### Features

* **guards:** let a test gate match its command by pattern ([#583](https://github.com/alexfayers/llm-prompts/issues/583)) ([b2b4193](https://github.com/alexfayers/llm-prompts/commit/b2b41932c768a7e4db38df9e1ad642b7bbf36beb))
* reinstall one pi extension with update --only ([#613](https://github.com/alexfayers/llm-prompts/issues/613)) ([8720bef](https://github.com/alexfayers/llm-prompts/commit/8720bef91a9fe3d68d1d74bdaf5f21372b7c7abc))
* **rules:** pick the cheapest option that fully works ([#535](https://github.com/alexfayers/llm-prompts/issues/535)) ([657f883](https://github.com/alexfayers/llm-prompts/commit/657f883c92518af3b5239a67d4b1b2600fa1df71))
* **size:** credit collection budget for declared overlay files ([#618](https://github.com/alexfayers/llm-prompts/issues/618)) ([7ac9d59](https://github.com/alexfayers/llm-prompts/commit/7ac9d59b62c2e73018ede517f2ddeda5455e6ac7))


### Bug Fixes

* **benchmark:** drop the host's pi-context vars from cell envs (+5 more) ([#563](https://github.com/alexfayers/llm-prompts/issues/563)) ([5d19aa9](https://github.com/alexfayers/llm-prompts/commit/5d19aa9c1888a5767a5ecd1e61ef6cb826e88f46))
* **contribute:** drop a merged worktree's main copy when its local branch differs from the PR head ([#620](https://github.com/alexfayers/llm-prompts/issues/620)) ([a9a0c8b](https://github.com/alexfayers/llm-prompts/commit/a9a0c8ba9c352ca978ec413360e49c788eebd968))
* **guards:** count a redirected test run before a read-only && step and name the counting forms ([#538](https://github.com/alexfayers/llm-prompts/issues/538)) ([1ab5749](https://github.com/alexfayers/llm-prompts/commit/1ab57492173dd5c7e5a466151dbf7b61bd8ecb27))
* **pi-context:** count fork usage without inherited history ([#616](https://github.com/alexfayers/llm-prompts/issues/616)) ([cbf2e4f](https://github.com/alexfayers/llm-prompts/commit/cbf2e4f18c7edc74cffe77d3077f89be55d87e72))
* **rules:** exempt the delegate timer from the coding-shell sleep ban ([#602](https://github.com/alexfayers/llm-prompts/issues/602)) ([86871d1](https://github.com/alexfayers/llm-prompts/commit/86871d1dc07e215e8153615443bf39cc2901849a))
* **update:** give the model the full changelog whenever an update is found or starts ([#543](https://github.com/alexfayers/llm-prompts/issues/543)) ([32cfffd](https://github.com/alexfayers/llm-prompts/commit/32cfffd789d0e492aa9ece33866b6cdabd40c005))


### Performance Improvements

* **update:** refresh the update check in the background ([#561](https://github.com/alexfayers/llm-prompts/issues/561)) ([db2979d](https://github.com/alexfayers/llm-prompts/commit/db2979d74f83c4a86ff3c8a252553a23935ec625))


### Miscellaneous Chores

* **deps:** update github actions ([#595](https://github.com/alexfayers/llm-prompts/issues/595)) ([f3558a7](https://github.com/alexfayers/llm-prompts/commit/f3558a70afd228ad673164c911135d0887cea08d))
* **deps:** update pi extensions ([#597](https://github.com/alexfayers/llm-prompts/issues/597)) ([d2ddfb9](https://github.com/alexfayers/llm-prompts/commit/d2ddfb9d15c3e4f01274f219cc1bde6be267cf26))
* **deps:** update pi extensions ([#615](https://github.com/alexfayers/llm-prompts/issues/615)) ([eaa28ef](https://github.com/alexfayers/llm-prompts/commit/eaa28ef4d6cb458f1ee00181a8d6b8ecde9d44aa))

## [0.7.0](https://github.com/alexfayers/llm-prompts/compare/v0.6.3...v0.7.0) (2026-11-24)


### Features

* add opencode as an install target ([#548](https://github.com/alexfayers/llm-prompts/issues/548)) ([1e4a8a6](https://github.com/alexfayers/llm-prompts/commit/1e4a8a6bd74885da9ce0d68d8b3d077e7f6b62db))
* install cline-hooks for opencode ([#549](https://github.com/alexfayers/llm-prompts/issues/549)) ([1fbbd00](https://github.com/alexfayers/llm-prompts/commit/1fbbd00da42b49fe983167bdc3a9504d8c639aad))


### Bug Fixes

* keep the old file when a managed file write fails ([#611](https://github.com/alexfayers/llm-prompts/issues/611)) ([278998c](https://github.com/alexfayers/llm-prompts/commit/278998c316ba70f3742a7ce7ed1054c07b07b534))
* **pi-context:** send main's prompt cache key from a warm fork ([#586](https://github.com/alexfayers/llm-prompts/issues/586)) ([0d20825](https://github.com/alexfayers/llm-prompts/commit/0d2082580358f66a393f6f5db3a2c6d53e19cffd))
* **pi:** rebuild the board note from visible notes and skip nested tool results ([#610](https://github.com/alexfayers/llm-prompts/issues/610)) ([6f14f9b](https://github.com/alexfayers/llm-prompts/commit/6f14f9bdbedb960d7a67aecbb0b9e627e13e0cb1))
* **update:** run the automatic update while unrelated forks run ([#585](https://github.com/alexfayers/llm-prompts/issues/585)) ([dac3db8](https://github.com/alexfayers/llm-prompts/commit/dac3db883275a5077d79de97e4869ccac3ad49ea))


### Miscellaneous Chores

* **deps:** update all non-major dependencies ([#607](https://github.com/alexfayers/llm-prompts/issues/607)) ([a936ae6](https://github.com/alexfayers/llm-prompts/commit/a936ae6f4cae558278ecbd6b4fca6708b8c381bd))
* run the just checks in parallel ([#612](https://github.com/alexfayers/llm-prompts/issues/612)) ([73c288c](https://github.com/alexfayers/llm-prompts/commit/73c288c2c5e4ea86c93bace3503d6adce389da6a))

## [0.6.3](https://github.com/alexfayers/llm-prompts/compare/v0.6.2...v0.6.3) (2026-11-23)


### Bug Fixes

* **pi:** time out a stuck tower_do_patch board call and stop it holding the nested-call queue ([#570](https://github.com/alexfayers/llm-prompts/issues/570)) ([6bbda79](https://github.com/alexfayers/llm-prompts/commit/6bbda79bf8d5ac386e423ce174430b0deabc98d3))


### Miscellaneous Chores

* **deps:** lock file maintenance ([#605](https://github.com/alexfayers/llm-prompts/issues/605)) ([55cd399](https://github.com/alexfayers/llm-prompts/commit/55cd399fc1187d018809197f18285aa1ed15dca4))

## [0.6.2](https://github.com/alexfayers/llm-prompts/compare/v0.6.1...v0.6.2) (2026-11-22)


### Miscellaneous Chores

* **deps:** update all non-major dependencies to v1.6.0 ([#596](https://github.com/alexfayers/llm-prompts/issues/596)) ([1d020d9](https://github.com/alexfayers/llm-prompts/commit/1d020d9003cdec8edbc27f605b31d0cf006a53d2))
* **deps:** update github actions ([#599](https://github.com/alexfayers/llm-prompts/issues/599)) ([e6891eb](https://github.com/alexfayers/llm-prompts/commit/e6891eb09480fc379c0e3738b6d7ffa8c7add280))

## [0.6.1](https://github.com/alexfayers/llm-prompts/compare/v0.6.0...v0.6.1) (2026-11-21)


### Bug Fixes

* **session-start:** allow running the checklist on Python 3.9 ([#589](https://github.com/alexfayers/llm-prompts/issues/589)) ([7f590d3](https://github.com/alexfayers/llm-prompts/commit/7f590d3376a5be6344c363650fc9f1fe3fbaafaa))
* **watch:** end a --follow watch at a source's terminal state ([#547](https://github.com/alexfayers/llm-prompts/issues/547)) ([8805414](https://github.com/alexfayers/llm-prompts/commit/88054141be5191b3c0e4f237523876b9745ae4f0))


### Miscellaneous Chores

* sync shared files from llm-prompts-ci ([#592](https://github.com/alexfayers/llm-prompts/issues/592)) ([0822389](https://github.com/alexfayers/llm-prompts/commit/082238976ce198ad4841812bc466ce6253ba915e))

## [0.6.0](https://github.com/alexfayers/llm-prompts/compare/v0.5.0...v0.6.0) (2026-11-20)


### Features

* **mcp-hints:** shorten the MCP tool list ([#564](https://github.com/alexfayers/llm-prompts/issues/564)) ([196ac1e](https://github.com/alexfayers/llm-prompts/commit/196ac1e8637162fbce2263a2f175337d456653ca))
* **pi:** tell agents to pass taskKey to tower_do_status ([#565](https://github.com/alexfayers/llm-prompts/issues/565)) ([8bfaa3d](https://github.com/alexfayers/llm-prompts/commit/8bfaa3d6b52cc1e67bfefd9d0e1b70520de3e7ba))
* **prompts:** require the simplest shell command without default-only flags ([#568](https://github.com/alexfayers/llm-prompts/issues/568)) ([23d84f6](https://github.com/alexfayers/llm-prompts/commit/23d84f6f4cc69a6008b22af9132a96976f676a6d))
* **update:** show users the version and changelog link, give agents the full changelog ([#557](https://github.com/alexfayers/llm-prompts/issues/557)) ([8c93e72](https://github.com/alexfayers/llm-prompts/commit/8c93e72ba20d86303e5ee89817e8821490b40fc8))


### Bug Fixes

* **auto-update:** ignore untracked files when checking for local changes (+2 more) ([#558](https://github.com/alexfayers/llm-prompts/issues/558)) ([485eba2](https://github.com/alexfayers/llm-prompts/commit/485eba27f7c2ecc610e6b0ade3aea705644d01f8))
* **benchmark:** run each variant's hooks from its own build ([#574](https://github.com/alexfayers/llm-prompts/issues/574)) ([16c63e2](https://github.com/alexfayers/llm-prompts/commit/16c63e27930a0a55d684b54624483e28989a454d))
* **checkpoint:** give the checkpoint advice only in the first nudge after a reset ([#567](https://github.com/alexfayers/llm-prompts/issues/567)) ([cabcd0d](https://github.com/alexfayers/llm-prompts/commit/cabcd0d3ba1ddda232f2289994d102912a4fd4ff))
* **install:** keep pi's managed manifest records across a frozen install ([#569](https://github.com/alexfayers/llm-prompts/issues/569)) ([984dd8f](https://github.com/alexfayers/llm-prompts/commit/984dd8f1281c5f98d187d2bf04d4c3a50761175e))
* **pi-context:** accept an empty ref at the end of an outcome line ([#566](https://github.com/alexfayers/llm-prompts/issues/566)) ([ad12c50](https://github.com/alexfayers/llm-prompts/commit/ad12c50772b29aaa9fd666db176a3b3cb854fb3c))
* **update:** update moved release tags instead of failing the fetch ([#556](https://github.com/alexfayers/llm-prompts/issues/556)) ([cc96d66](https://github.com/alexfayers/llm-prompts/commit/cc96d662938ffddf82828a369b2ad6a17bcc6e20))


### Performance Improvements

* **hooks:** load telemetry only when the plugin sends it (+1 more) ([#579](https://github.com/alexfayers/llm-prompts/issues/579)) ([a50c5c3](https://github.com/alexfayers/llm-prompts/commit/a50c5c33b6e5b0c958c32bdec9e4e57ae6513daf))


### Miscellaneous Chores

* **deps:** update github actions ([#588](https://github.com/alexfayers/llm-prompts/issues/588)) ([3ab8ad4](https://github.com/alexfayers/llm-prompts/commit/3ab8ad439901ef01e08a5cf2845b6c20ddc4c757))
* **deps:** update pi extensions ([#572](https://github.com/alexfayers/llm-prompts/issues/572)) ([8b69d84](https://github.com/alexfayers/llm-prompts/commit/8b69d8470b5570451944a971dfa2df43a2408557))
* **deps:** update pi extensions ([#576](https://github.com/alexfayers/llm-prompts/issues/576)) ([0e8b16f](https://github.com/alexfayers/llm-prompts/commit/0e8b16fe35d680b2dd1eb1debca4d670d88b6d9a))
* **deps:** update pi extensions ([#584](https://github.com/alexfayers/llm-prompts/issues/584)) ([3aaef29](https://github.com/alexfayers/llm-prompts/commit/3aaef29a80c0ef3144f2fa12c0dfaf52da2a2585))

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
