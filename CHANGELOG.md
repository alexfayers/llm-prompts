# Changelog

## [0.11.0](https://github.com/alexfayers/llm-prompts/compare/v0.10.0...v0.11.0) (2026-11-28)


### Features

* **benchmark:** add a scenario for the vote size on a direct user instruction ([#910](https://github.com/alexfayers/llm-prompts/issues/910)) ([a73d271](https://github.com/alexfayers/llm-prompts/commit/a73d271be404e7453523bc4d243a6309e9725a06))
* **benchmark:** add memory scenarios for delegate writes and entity location ([#894](https://github.com/alexfayers/llm-prompts/issues/894)) ([ac65839](https://github.com/alexfayers/llm-prompts/commit/ac65839dc0b46be7e6a56db41e4f944ec3274c96))
* **benchmark:** measure context fold on and off with --feature ([#776](https://github.com/alexfayers/llm-prompts/issues/776)) ([8a50565](https://github.com/alexfayers/llm-prompts/commit/8a50565d70cec48861e737871fc70de6615a8395))
* **benchmark:** measure fork start-up time and MCP server cost ([#922](https://github.com/alexfayers/llm-prompts/issues/922)) ([1890003](https://github.com/alexfayers/llm-prompts/commit/1890003f5b7d9af2d91e0815d9e41b9aab8f38fa))
* **benchmark:** name each check in results.jsonl and report.json ([#912](https://github.com/alexfayers/llm-prompts/issues/912)) ([ecc5850](https://github.com/alexfayers/llm-prompts/commit/ecc58503d2e25465eb12df4e5b299e4ca8e9d81d))
* **cli:** add --version ([#914](https://github.com/alexfayers/llm-prompts/issues/914)) ([1b279cb](https://github.com/alexfayers/llm-prompts/commit/1b279cb0c2da688fa32321c869dd42619f23c50d))
* **contribute:** leave auto-merge PRs to the rebase queue in update ([#908](https://github.com/alexfayers/llm-prompts/issues/908)) ([f70670e](https://github.com/alexfayers/llm-prompts/commit/f70670ebc8ab75d6608ed5ce873287679af66721))
* **guards:** block inline python and node scripts that parse JSON ([#890](https://github.com/alexfayers/llm-prompts/issues/890)) ([b0fa5e4](https://github.com/alexfayers/llm-prompts/commit/b0fa5e48c872bfff333305c7af7e41c7e7f2d7c6))
* **pi-context:** turn the MCP proxy on by default in forks ([#907](https://github.com/alexfayers/llm-prompts/issues/907)) ([7a44c72](https://github.com/alexfayers/llm-prompts/commit/7a44c726c92c36ef94bfdb090f1fd056365985ff))
* **tower-do-slim:** remove open board tasks idle for more than 3 days on session start (+1 more) ([#911](https://github.com/alexfayers/llm-prompts/issues/911)) ([d76c09e](https://github.com/alexfayers/llm-prompts/commit/d76c09e04400f70410fadfcda499d97579cafdfb))
* **uninstall:** remove companion tool hooks and memory service ([#884](https://github.com/alexfayers/llm-prompts/issues/884)) ([13834f0](https://github.com/alexfayers/llm-prompts/commit/13834f0c022bed6fe0ebb8c4895562fe370fceeb))
* **update:** warn when local main holds commits on no open PR ([#902](https://github.com/alexfayers/llm-prompts/issues/902)) ([e66c8e0](https://github.com/alexfayers/llm-prompts/commit/e66c8e086b5af4c206688a465c61cae8029b532b))


### Bug Fixes

* **guards:** count a test run followed by `; echo rc=$?` that prints rc=0 ([#915](https://github.com/alexfayers/llm-prompts/issues/915)) ([07ef7f4](https://github.com/alexfayers/llm-prompts/commit/07ef7f4395e5723d3414277af0ac679ddc07977a))
* **guards:** do not count a test run that left its own fixes unstaged ([#919](https://github.com/alexfayers/llm-prompts/issues/919)) ([85296a9](https://github.com/alexfayers/llm-prompts/commit/85296a9cf045324a4c9f946e5e11df25696f314d))
* **watch:** reject an --until value a field never takes ([#921](https://github.com/alexfayers/llm-prompts/issues/921)) ([d9645ba](https://github.com/alexfayers/llm-prompts/commit/d9645ba90d480ca14c6e55b34e36c2de13d83c4b))


### Miscellaneous Chores

* **deps:** update pi extensions ([#893](https://github.com/alexfayers/llm-prompts/issues/893)) ([ae3c544](https://github.com/alexfayers/llm-prompts/commit/ae3c54491eeb66287c479551878aed38d4e68f1b))

## [0.10.0](https://github.com/alexfayers/llm-prompts/compare/v0.9.0...v0.10.0) (2026-11-27)


### ⚠ BREAKING CHANGES

* remove the lsp feature ([#762](https://github.com/alexfayers/llm-prompts/issues/762))
* treat a "btw" message as side work and remove //btw ([#769](https://github.com/alexfayers/llm-prompts/issues/769))
* remove the attic feature ([#761](https://github.com/alexfayers/llm-prompts/issues/761))

### Features

* add the shared tool path contract and a one-time copy into it ([#756](https://github.com/alexfayers/llm-prompts/issues/756)) ([b8c0cd6](https://github.com/alexfayers/llm-prompts/commit/b8c0cd6a16469ce69dcf65e780446d134197583d))
* **benchmark:** measure a warm fork after the lead read a long handbook ([#886](https://github.com/alexfayers/llm-prompts/issues/886)) ([816abdd](https://github.com/alexfayers/llm-prompts/commit/816abdd2f24e62942343627c85cb70b788701f7c))
* **benchmark:** measure cache warming on and off with --feature ([#779](https://github.com/alexfayers/llm-prompts/issues/779)) ([fdf8391](https://github.com/alexfayers/llm-prompts/commit/fdf8391f3334ddba4bfaaf7fdb8b2f40f641e63a))
* **benchmark:** measure the shared tasks stub on and off with --feature shared-tasks ([#766](https://github.com/alexfayers/llm-prompts/issues/766)) ([fc0d540](https://github.com/alexfayers/llm-prompts/commit/fc0d540dd6747e304cb3cb98068f5b850f5bf361))
* **benchmark:** measure the warm fork against a cold fork with --feature warm-fork ([#767](https://github.com/alexfayers/llm-prompts/issues/767)) ([8c91bcc](https://github.com/alexfayers/llm-prompts/commit/8c91bcc071f06351f8592ca47b1c433188985533))
* **benchmark:** report each fork's own start context in the run summary ([#834](https://github.com/alexfayers/llm-prompts/issues/834)) ([237d725](https://github.com/alexfayers/llm-prompts/commit/237d7252862e38e1ce939716d6876bfe8105e128))
* **claude-code:** seed default permissions into Claude Code settings on install ([#750](https://github.com/alexfayers/llm-prompts/issues/750)) ([c32edac](https://github.com/alexfayers/llm-prompts/commit/c32edacb45da1ac29976cac2cac3a54b1a6db652))
* **contribute:** add sync --only BRANCH to sync one recorded branch ([#864](https://github.com/alexfayers/llm-prompts/issues/864)) ([b76b464](https://github.com/alexfayers/llm-prompts/commit/b76b464d5972fd4966c211684d6176bf99c9ac8c))
* **contribute:** open no new PR at the review limit ([#848](https://github.com/alexfayers/llm-prompts/issues/848)) ([047fa1e](https://github.com/alexfayers/llm-prompts/commit/047fa1eff945921f58f0acc1f2c42257118dfc05))
* formalise how agents file issues and set issue status ([#784](https://github.com/alexfayers/llm-prompts/issues/784)) ([c86ef60](https://github.com/alexfayers/llm-prompts/commit/c86ef6027deb5e94c8571c6094f90424b8cd7e44))
* **install:** substitute the skill directory path at install time ([#743](https://github.com/alexfayers/llm-prompts/issues/743)) ([ff78b1b](https://github.com/alexfayers/llm-prompts/commit/ff78b1b37a6b4b163e8b62efa31bf501b23826d4))
* keep llm-prompts files under the shared root and copy old ones there ([#768](https://github.com/alexfayers/llm-prompts/issues/768)) ([a9b7841](https://github.com/alexfayers/llm-prompts/commit/a9b7841df296776d8a7b643f829a07ee77af5bc2))
* **lead:** add a skill for running a pipeline of PR delegates ([#809](https://github.com/alexfayers/llm-prompts/issues/809)) ([c9bb30d](https://github.com/alexfayers/llm-prompts/commit/c9bb30db9e9b52e823c7469b39a64ffbfc20429e))
* **pi-context:** add a team role that forks members one level deep ([#729](https://github.com/alexfayers/llm-prompts/issues/729)) ([4e92818](https://github.com/alexfayers/llm-prompts/commit/4e92818317dbe67c2693c24f268c1ebe88b27bc6))
* **pi-context:** expose the read-only tools of every MCP server to delegates ([#832](https://github.com/alexfayers/llm-prompts/issues/832)) ([9d288f6](https://github.com/alexfayers/llm-prompts/commit/9d288f60b40b3882d38d3f6ae84b061cfdb171be))
* **pi-context:** keep reused forks small with checkpoint nudges and resume limits ([#878](https://github.com/alexfayers/llm-prompts/issues/878)) ([aa46e2d](https://github.com/alexfayers/llm-prompts/commit/aa46e2db21185a29135091e1752d8aadfe4dd922))
* **pi-context:** let fork_resume give a task to a cancelled fork ([#831](https://github.com/alexfayers/llm-prompts/issues/831)) ([624f06a](https://github.com/alexfayers/llm-prompts/commit/624f06a458bbb91e360c692212d010b05dee778c))
* **pi-context:** make a worktree for a writer fork started in a primary checkout ([#785](https://github.com/alexfayers/llm-prompts/issues/785)) ([e2484f9](https://github.com/alexfayers/llm-prompts/commit/e2484f90af3ed597c23d51a7a0a02e300601cf6c))
* **pi-context:** make shared-tasks children read the stub's cache ([#813](https://github.com/alexfayers/llm-prompts/issues/813)) ([131fd8d](https://github.com/alexfayers/llm-prompts/commit/131fd8d78fba88cf43f7c6fd7d4be74b6dad098e))
* **pi-context:** make the fork widget and result blocks less crowded ([#806](https://github.com/alexfayers/llm-prompts/issues/806)) ([cac316e](https://github.com/alexfayers/llm-prompts/commit/cac316e89972a58feff051cac68708c2a97decbf))
* **pi-context:** note a fork that runs over the check-in interval in the next tool result ([#709](https://github.com/alexfayers/llm-prompts/issues/709)) ([cc770bc](https://github.com/alexfayers/llm-prompts/commit/cc770bca159d0d69e76c9c72b2cd561de0ad9df0))
* **pi-context:** prune old kept fork archives at session start ([#807](https://github.com/alexfayers/llm-prompts/issues/807)) ([d9c031e](https://github.com/alexfayers/llm-prompts/commit/d9c031e20d19b830d6e163098e7adb75af2a6f69))
* **pi-context:** remove a fork's worktree after an escalation when its work is on origin ([#783](https://github.com/alexfayers/llm-prompts/issues/783)) ([9a5958f](https://github.com/alexfayers/llm-prompts/commit/9a5958fb6951d6a33a282aa0de2675f84bb16aaa))
* **pi-context:** resume forks that a reload_now reload ended ([#805](https://github.com/alexfayers/llm-prompts/issues/805)) ([aa2c92e](https://github.com/alexfayers/llm-prompts/commit/aa2c92eeada942831d752029b4de76d8d06e2b4d))
* **pi-context:** show finished forks as one summary row in the widget ([#790](https://github.com/alexfayers/llm-prompts/issues/790)) ([e6f00ea](https://github.com/alexfayers/llm-prompts/commit/e6f00ea9913de3d1df5b854c4dd8e2e476e4ac9d))
* **pi-context:** show free fork slots and ready board tasks in fork results ([#852](https://github.com/alexfayers/llm-prompts/issues/852)) ([0e34377](https://github.com/alexfayers/llm-prompts/commit/0e34377c385bc119aaa4dc3ad9ac815b847f696a))
* **pi-context:** start cold forks from one stub per model and effort level ([#730](https://github.com/alexfayers/llm-prompts/issues/730)) ([86a1997](https://github.com/alexfayers/llm-prompts/commit/86a1997cb82a46892384b29cfa23f54fd97ce189))
* **pi:** end the turn and compact at once in compact_now, keeping later entries ([#812](https://github.com/alexfayers/llm-prompts/issues/812)) ([d765dbc](https://github.com/alexfayers/llm-prompts/commit/d765dbcf628d29f3f0bf8f39f34cef4199f1946e))
* **pi:** fold the output of a test or build run once it has been acted on ([#787](https://github.com/alexfayers/llm-prompts/issues/787)) ([111fb91](https://github.com/alexfayers/llm-prompts/commit/111fb91484288bded88f6166e9b435c2a3c444da))
* **pi:** give reader forks a smaller delegate rule file ([#842](https://github.com/alexfayers/llm-prompts/issues/842)) ([045c6a6](https://github.com/alexfayers/llm-prompts/commit/045c6a64556dbdb1737ca34c9f0946b4b9cda7ab))
* **pi:** group pane-reaper notices and delete merged branches ([#804](https://github.com/alexfayers/llm-prompts/issues/804)) ([ab5600f](https://github.com/alexfayers/llm-prompts/commit/ab5600fa0e1427ec30c6736ed1159a6b2295c48c))
* **pi:** let a writer fork start its own branch from a base ref ([#817](https://github.com/alexfayers/llm-prompts/issues/817)) ([2ed7517](https://github.com/alexfayers/llm-prompts/commit/2ed751729f9be42ef8356941acb76765decd093c))
* **pi:** let fork_resume queue a task for a running fork ([#826](https://github.com/alexfayers/llm-prompts/issues/826)) ([9e36423](https://github.com/alexfayers/llm-prompts/commit/9e36423752a6e957f04dad8e69882529380b3517))
* **pi:** remove finished worktrees in pane-reaper ([#786](https://github.com/alexfayers/llm-prompts/issues/786)) ([28742b7](https://github.com/alexfayers/llm-prompts/commit/28742b74287df4e145c566b70998e04479905cfe))
* **pi:** use the notices settings ([#668](https://github.com/alexfayers/llm-prompts/issues/668)) ([1abda40](https://github.com/alexfayers/llm-prompts/commit/1abda40192d06d030c675d9f22c34df25eebe136))
* **pr-review:** block only on likely findings and narrow late re-reviews ([#788](https://github.com/alexfayers/llm-prompts/issues/788)) ([4573174](https://github.com/alexfayers/llm-prompts/commit/457317431b5578928a2d9cd09e4cc8e178c11041))
* **prompts:** trigger session-end on a "thanks" only when it closes the work ([#858](https://github.com/alexfayers/llm-prompts/issues/858)) ([ce17a53](https://github.com/alexfayers/llm-prompts/commit/ce17a53ba530418be366d96664a78b85ef310968))
* remove the attic feature ([#761](https://github.com/alexfayers/llm-prompts/issues/761)) ([83e89ea](https://github.com/alexfayers/llm-prompts/commit/83e89ea9ef4e20489c52ba2eb10f61751d05cb68))
* remove the lsp feature ([#762](https://github.com/alexfayers/llm-prompts/issues/762)) ([bb42491](https://github.com/alexfayers/llm-prompts/commit/bb424911539b26b20371372e08e43f38d4ff1632))
* **settings:** add a settings command that prints and checks the config ([#757](https://github.com/alexfayers/llm-prompts/issues/757)) ([d4d2105](https://github.com/alexfayers/llm-prompts/commit/d4d2105a52022c7bcbac147e178f1c05ba9d4d44))
* **settings:** add an interactive editor for the config's settings ([#764](https://github.com/alexfayers/llm-prompts/issues/764)) ([fd02594](https://github.com/alexfayers/llm-prompts/commit/fd0259439cd58b7cabd84a9ec111ce4f7f05d2ed))
* **settings:** edit plugin frontmatter_overrides in the settings editor ([#833](https://github.com/alexfayers/llm-prompts/issues/833)) ([d80f6a5](https://github.com/alexfayers/llm-prompts/commit/d80f6a5e2938638c6aee92565b7faeea97781aaa))
* **settings:** edit the tools, plugins and per-repo review limits in the settings editor ([#793](https://github.com/alexfayers/llm-prompts/issues/793)) ([5396b20](https://github.com/alexfayers/llm-prompts/commit/5396b20a33df9a29350f700d5fbfedf09b18bb44))
* **settings:** load, check and save the config file keeping its comments ([#754](https://github.com/alexfayers/llm-prompts/issues/754)) ([6ce0120](https://github.com/alexfayers/llm-prompts/commit/6ce01205b7fdb84a6f536d76f5efc3add6c65910))
* **setup:** clone git-sourced tools locally and point their source at the clone ([#753](https://github.com/alexfayers/llm-prompts/issues/753)) ([b91ced2](https://github.com/alexfayers/llm-prompts/commit/b91ced2297f904f914d47722b91e45f99c829d4e))
* **telemetry:** send cline-hooks and mcp-memory versions on pi_session events ([#874](https://github.com/alexfayers/llm-prompts/issues/874)) ([ed460da](https://github.com/alexfayers/llm-prompts/commit/ed460da6a669a38b1382cedd24af2f1c006a789b))
* **telemetry:** send one anonymous event per pi session ([#818](https://github.com/alexfayers/llm-prompts/issues/818)) ([d1d6d39](https://github.com/alexfayers/llm-prompts/commit/d1d6d39a363246fd35fa34392978d63cfae72b08))
* **telemetry:** send the cause when update stops on a source sync failure ([#877](https://github.com/alexfayers/llm-prompts/issues/877)) ([265ff25](https://github.com/alexfayers/llm-prompts/commit/265ff2596e1304a66f59471aeeef76c7c7dec761))
* **telemetry:** send tool versions on exception events ([#875](https://github.com/alexfayers/llm-prompts/issues/875)) ([11516bc](https://github.com/alexfayers/llm-prompts/commit/11516bcfacdb0b2f14c9c18ed2fb7ad477e75bdb))
* **telemetry:** send workflow time split, review rounds and time to PR ([#885](https://github.com/alexfayers/llm-prompts/issues/885)) ([47cb56a](https://github.com/alexfayers/llm-prompts/commit/47cb56ae347e07999119bc96d4da5bf2a7b5a4ef))
* treat a "btw" message as side work and remove //btw ([#769](https://github.com/alexfayers/llm-prompts/issues/769)) ([1451a0e](https://github.com/alexfayers/llm-prompts/commit/1451a0ec7d09bc1200935ec242496163fe19f382))
* **watch:** stop gh-pr on a PR label with --until label=GLOB ([#839](https://github.com/alexfayers/llm-prompts/issues/839)) ([9692ba5](https://github.com/alexfayers/llm-prompts/commit/9692ba5a5f9d157dc38e930695d15dda6af6c450))
* **watch:** stop gh-pr on merge conflicts with --until conflicts ([#845](https://github.com/alexfayers/llm-prompts/issues/845)) ([8e791aa](https://github.com/alexfayers/llm-prompts/commit/8e791aa69dd1f212c2090924a2f2dc4e46b40d43))


### Bug Fixes

* **benchmark:** keep another run's variant builds while it uses them ([#868](https://github.com/alexfayers/llm-prompts/issues/868)) ([8880d61](https://github.com/alexfayers/llm-prompts/commit/8880d6162d89acdd87477f81fa6328532ff0cd42))
* **benchmark:** leave npm debug logs out of the variant audit ([#797](https://github.com/alexfayers/llm-prompts/issues/797)) ([5e29360](https://github.com/alexfayers/llm-prompts/commit/5e29360f63751c984be1178bb0d5476537f4f4bb))
* **benchmark:** let the audit accept the guard interpreter path ([#811](https://github.com/alexfayers/llm-prompts/issues/811)) ([d48cc81](https://github.com/alexfayers/llm-prompts/commit/d48cc81306eabed26434920b5c19d5fbf1ff70ac))
* **checkpoint:** rewind nudge honours AWS_BEDROCK_FORCE_CACHE ([#739](https://github.com/alexfayers/llm-prompts/issues/739)) ([0640c04](https://github.com/alexfayers/llm-prompts/commit/0640c046cbbd53418bae148dcbbcdfe9b4132d0d))
* **contribute:** report an unreadable PR body file instead of crashing ([#867](https://github.com/alexfayers/llm-prompts/issues/867)) ([be564a8](https://github.com/alexfayers/llm-prompts/commit/be564a8c88d0b3ee6c71246c78a7dfd8fb108847))
* **guards:** count a just run with a uv_run override as the test run ([#860](https://github.com/alexfayers/llm-prompts/issues/860)) ([66b95dd](https://github.com/alexfayers/llm-prompts/commit/66b95dd9535a07f3e4d844a35a005a173805d2da))
* **guards:** let gh and git help calls past the primary checkout guard ([#846](https://github.com/alexfayers/llm-prompts/issues/846)) ([5622e55](https://github.com/alexfayers/llm-prompts/commit/5622e5509a3d312f77d3ff18506dfae6311c0f5a))
* **guards:** say when a test run was not counted because its shell line did not parse ([#879](https://github.com/alexfayers/llm-prompts/issues/879)) ([7341e45](https://github.com/alexfayers/llm-prompts/commit/7341e455f09862df773e893b87fb90aeca3ab392))
* **hooks:** keep update-check stamps in the cline-hooks data dir ([#880](https://github.com/alexfayers/llm-prompts/issues/880)) ([e190da2](https://github.com/alexfayers/llm-prompts/commit/e190da23dc4b1d7fa32807a5e57dc5aa75b2db66))
* **install:** hide npm output from pi package installs unless verbose or failed ([#857](https://github.com/alexfayers/llm-prompts/issues/857)) ([c453750](https://github.com/alexfayers/llm-prompts/commit/c4537507c8bd48d11deac01bad3a0b03bce5532f))
* **install:** keep managed pi packages when update runs outside the installed tool ([#863](https://github.com/alexfayers/llm-prompts/issues/863)) ([c998efb](https://github.com/alexfayers/llm-prompts/commit/c998efb594f0811d86bababae4a07610242fe4fe))
* **install:** name unreplaced variables once per source in the size guard report ([#856](https://github.com/alexfayers/llm-prompts/issues/856)) ([cffcbbe](https://github.com/alexfayers/llm-prompts/commit/cffcbbecab40dd7bf36960819c717695e44086ee))
* **install:** print one short line when another pi shadows the managed pi ([#855](https://github.com/alexfayers/llm-prompts/issues/855)) ([8078f02](https://github.com/alexfayers/llm-prompts/commit/8078f0284132d7c199ffa6bd816b1e83c62672d3))
* **just:** install pnpm dependencies before the TypeScript checks ([#751](https://github.com/alexfayers/llm-prompts/issues/751)) ([45a4784](https://github.com/alexfayers/llm-prompts/commit/45a4784357e629259e2f497ee84a3c744f73df24))
* **lead:** skip manual rebases and landing checkouts for one-PR-per-writer work ([#825](https://github.com/alexfayers/llm-prompts/issues/825)) ([ad61f29](https://github.com/alexfayers/llm-prompts/commit/ad61f2978cafef56b1f948ca5097c8d8fe2c85bd))
* **network:** stop git network calls waiting on a terminal credential prompt ([#847](https://github.com/alexfayers/llm-prompts/issues/847)) ([b32e62b](https://github.com/alexfayers/llm-prompts/commit/b32e62b2541d080d093a8c97ff1c68e48632d5d7))
* **pi-context:** deliver a fork result that ends after main's last turn when main settles ([#851](https://github.com/alexfayers/llm-prompts/issues/851)) ([0a5a23a](https://github.com/alexfayers/llm-prompts/commit/0a5a23a31f42d3376f014c00f80bf697b3eb82f4))
* **pi-context:** deliver fork results at the end of a busy turn and start a cancelled fork once ([#841](https://github.com/alexfayers/llm-prompts/issues/841)) ([4b34c42](https://github.com/alexfayers/llm-prompts/commit/4b34c42023da9175875c49114537efd69327c61a))
* **pi-context:** give read-only forks a shared agent dir so they share a cache prefix ([#778](https://github.com/alexfayers/llm-prompts/issues/778)) ([f67daee](https://github.com/alexfayers/llm-prompts/commit/f67daeebb00b795c98cae9d501a0fb33da49ec89))
* **pi-context:** keep a session without a UI waiting for the children of a cold stub ([#887](https://github.com/alexfayers/llm-prompts/issues/887)) ([f8ee62b](https://github.com/alexfayers/llm-prompts/commit/f8ee62bc9673835983ee86dab49c760d6c8ee8c6))
* **pi-context:** keep the lead's tool loadout in a warm fork's seed after a compaction ([#866](https://github.com/alexfayers/llm-prompts/issues/866)) ([0c08491](https://github.com/alexfayers/llm-prompts/commit/0c0849191f41823c5fdd6fc1011e1cff51baab2b))
* **pi-context:** land a writer that pushed a branch it switched to by that push ([#881](https://github.com/alexfayers/llm-prompts/issues/881)) ([02c3ecd](https://github.com/alexfayers/llm-prompts/commit/02c3ecdd2440403775bfbdef6a90c4b765e039c7))
* **pi-context:** restore only the latest entry of each needed run ([#796](https://github.com/alexfayers/llm-prompts/issues/796)) ([72d296d](https://github.com/alexfayers/llm-prompts/commit/72d296d4b663220cb726b3c9bcfd36fbc94200e0))
* **pi-context:** say cache time left in the warm-fork hint and keep escalation phrases whole ([#850](https://github.com/alexfayers/llm-prompts/issues/850)) ([8a87e06](https://github.com/alexfayers/llm-prompts/commit/8a87e06b2ab43a51c3f921b117388ac59147eeb3))
* **pi-context:** steer fork results into the lead's turn with a live fork count ([#836](https://github.com/alexfayers/llm-prompts/issues/836)) ([6738c58](https://github.com/alexfayers/llm-prompts/commit/6738c5881c4bedb428997abb039c97bb92239e60))
* **pi-context:** summarise large forks through the model registry ([#828](https://github.com/alexfayers/llm-prompts/issues/828)) ([34f1221](https://github.com/alexfayers/llm-prompts/commit/34f12214ee1226926a5d09cda0e816b179386f9e))
* **pi:** read process lists larger than 1 MiB in pane-reaper ([#861](https://github.com/alexfayers/llm-prompts/issues/861)) ([a4b2461](https://github.com/alexfayers/llm-prompts/commit/a4b24615019daa5913704621940a101cd062e934))
* **pi:** read the running pi version from the pi on PATH ([#844](https://github.com/alexfayers/llm-prompts/issues/844)) ([676dd20](https://github.com/alexfayers/llm-prompts/commit/676dd209cbe979aba67c16547e824946f1754d3e))
* quiet two noisy update output lines ([#854](https://github.com/alexfayers/llm-prompts/issues/854)) ([99c34bd](https://github.com/alexfayers/llm-prompts/commit/99c34bdd7427cd218627b5d1e5b28eb12c157958))
* read background git status without taking the index lock ([#882](https://github.com/alexfayers/llm-prompts/issues/882)) ([b38f816](https://github.com/alexfayers/llm-prompts/commit/b38f816e8933f517deb0c8bd82e0f4e93046d983))
* **watch:** report author PRs that merged or closed between polls ([#820](https://github.com/alexfayers/llm-prompts/issues/820)) ([cc3184f](https://github.com/alexfayers/llm-prompts/commit/cc3184f1285ef2100c45339dc440c5002f649845))


### Performance Improvements

* batch git reads and ref writes in contribute sync ([#741](https://github.com/alexfayers/llm-prompts/issues/741)) ([2f3378c](https://github.com/alexfayers/llm-prompts/commit/2f3378c1797d7af0d66e267cbc8fd88b6a918c6d))
* **pi-context:** scan the session for open asks once per branch change in the widget ([#794](https://github.com/alexfayers/llm-prompts/issues/794)) ([685ed75](https://github.com/alexfayers/llm-prompts/commit/685ed75e68dd4dc899962876ba442c125f65ef9d))
* **test:** split pytest workers between concurrent test runs ([#712](https://github.com/alexfayers/llm-prompts/issues/712)) ([a58ecb8](https://github.com/alexfayers/llm-prompts/commit/a58ecb8fdf0a9bff576d7767ec29924c460f6254))


### Miscellaneous Chores

* **deps:** update all non-major dependencies ([#758](https://github.com/alexfayers/llm-prompts/issues/758)) ([089f377](https://github.com/alexfayers/llm-prompts/commit/089f377cfa990f53845aef638c53478d54e90f8c))
* **deps:** update all non-major dependencies ([#760](https://github.com/alexfayers/llm-prompts/issues/760)) ([ae523df](https://github.com/alexfayers/llm-prompts/commit/ae523dff6989aec1921e320e8f0953801aa07b7a))
* **deps:** update all non-major dependencies ([#829](https://github.com/alexfayers/llm-prompts/issues/829)) ([5ab2e77](https://github.com/alexfayers/llm-prompts/commit/5ab2e77298954be29e058a561bc19ac40a54d865))
* **deps:** update all non-major dependencies ([#888](https://github.com/alexfayers/llm-prompts/issues/888)) ([4d45565](https://github.com/alexfayers/llm-prompts/commit/4d45565040814756cc72931b126ea224a39f9491))
* **deps:** update pi extensions ([#830](https://github.com/alexfayers/llm-prompts/issues/830)) ([0c77b8f](https://github.com/alexfayers/llm-prompts/commit/0c77b8f451885e24c00dc515071cb870998fd071))
* **deps:** update pi extensions ([#873](https://github.com/alexfayers/llm-prompts/issues/873)) ([2abc286](https://github.com/alexfayers/llm-prompts/commit/2abc2865b6137cb2ef76fe9d4ace13d01e3a2ed4))
* **deps:** update pi extensions ([#889](https://github.com/alexfayers/llm-prompts/issues/889)) ([0e7cde5](https://github.com/alexfayers/llm-prompts/commit/0e7cde500bd9fa9d3e41aa3e9e0402741aa08f9d))
* **deps:** update pi extensions ([#891](https://github.com/alexfayers/llm-prompts/issues/891)) ([3f0b373](https://github.com/alexfayers/llm-prompts/commit/3f0b3735e37229fcb393f4c3947ba9138795474d))

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
