# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/auto\_update.py                                              |      146 |       13 |     91% |32, 118-121, 145-148, 164-165, 182-184 |
| src/llm\_prompts/benchmark/\_\_init\_\_.py                                    |        1 |        0 |    100% |           |
| src/llm\_prompts/benchmark/agents/\_\_init\_\_.py                             |       18 |        2 |     89% |    25, 31 |
| src/llm\_prompts/benchmark/agents/adapter.py                                  |       34 |        0 |    100% |           |
| src/llm\_prompts/benchmark/agents/claude.py                                   |      158 |        3 |     98% |57, 133-134 |
| src/llm\_prompts/benchmark/agents/files.py                                    |       53 |        1 |     98% |        32 |
| src/llm\_prompts/benchmark/agents/pi.py                                       |      225 |        1 |     99% |       227 |
| src/llm\_prompts/benchmark/cell/\_\_init\_\_.py                               |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/cell/audit.py                                      |      100 |        3 |     97% |     62-64 |
| src/llm\_prompts/benchmark/cell/env.py                                        |       26 |        0 |    100% |           |
| src/llm\_prompts/benchmark/cell/home\_dirs.py                                 |       81 |        6 |     93% |60-63, 95, 105 |
| src/llm\_prompts/benchmark/cell/memory.py                                     |      121 |        3 |     98% |   151-153 |
| src/llm\_prompts/benchmark/cell/prepare.py                                    |      111 |        4 |     96% |     66-69 |
| src/llm\_prompts/benchmark/cell/shared.py                                     |       94 |        5 |     95% |64-65, 128-130 |
| src/llm\_prompts/benchmark/cell/variants.py                                   |      252 |       13 |     95% |58-59, 172, 198-199, 228, 382-383, 435-438, 440 |
| src/llm\_prompts/benchmark/command.py                                         |      221 |        1 |     99% |        94 |
| src/llm\_prompts/benchmark/fail\_fast.py                                      |       55 |        0 |    100% |           |
| src/llm\_prompts/benchmark/guard/\_\_init\_\_.py                              |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/guard/claude.py                                    |       26 |        1 |     96% |        64 |
| src/llm\_prompts/benchmark/live\_view.py                                      |      114 |        1 |     99% |       176 |
| src/llm\_prompts/benchmark/paths.py                                           |       52 |        1 |     98% |        69 |
| src/llm\_prompts/benchmark/report/\_\_init\_\_.py                             |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/report/compare.py                                  |      358 |        3 |     99% |144, 346, 701 |
| src/llm\_prompts/benchmark/report/render.py                                   |       98 |        0 |    100% |           |
| src/llm\_prompts/benchmark/report/terminal.py                                 |       49 |        1 |     98% |       144 |
| src/llm\_prompts/benchmark/reuse.py                                           |       69 |        0 |    100% |           |
| src/llm\_prompts/benchmark/runner/\_\_init\_\_.py                             |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/runner/events.py                                   |       64 |        0 |    100% |           |
| src/llm\_prompts/benchmark/runner/process.py                                  |       83 |        3 |     96% | 67-68, 84 |
| src/llm\_prompts/benchmark/runner/sandbox.py                                  |       61 |        2 |     97% |     47-48 |
| src/llm\_prompts/benchmark/saved.py                                           |       34 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scenarios/\_\_init\_\_.py                          |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scenarios/checks/\_\_init\_\_.py                   |      142 |        1 |     99% |        95 |
| src/llm\_prompts/benchmark/scenarios/checks/context.py                        |       44 |        1 |     98% |        92 |
| src/llm\_prompts/benchmark/scenarios/checks/judge.py                          |       91 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scenarios/loader.py                                |      134 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scheduler.py                                       |      347 |        6 |     98% |510, 517, 611, 613, 628, 655 |
| src/llm\_prompts/benchmark/transient.py                                       |       41 |        0 |    100% |           |
| src/llm\_prompts/benchmark/types.py                                           |      218 |        0 |    100% |           |
| src/llm\_prompts/claude\_models.py                                            |       23 |        0 |    100% |           |
| src/llm\_prompts/cli.py                                                       |      913 |       65 |     93% |107-108, 134-135, 142-155, 261-262, 277-282, 424, 702, 705, 728, 755, 793, 824, 956, 1164-1166, 1179-1182, 1253-1262, 1808-1810, 1813-1819, 1831-1833, 1844-1850, 1860, 1865, 1877, 2040, 2068-2069, 2074 |
| src/llm\_prompts/clones.py                                                    |      145 |       12 |     92% |75, 93-94, 127-129, 182-184, 248, 266-267 |
| src/llm\_prompts/collection\_size.py                                          |      133 |        3 |     98% |295-296, 500 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/config\_edit.py                                              |       58 |        1 |     98% |        74 |
| src/llm\_prompts/console.py                                                   |       18 |        1 |     94% |        48 |
| src/llm\_prompts/contribute.py                                                |     1283 |       62 |     95% |116, 220, 247-248, 289-290, 322-323, 472, 616-617, 650, 823, 826, 883, 894, 1004-1005, 1050, 1154, 1200-1201, 1214, 1630-1633, 1821, 1823, 1837-1838, 1847-1848, 1867, 1878-1879, 1950, 2006-2011, 2015, 2135, 2178-2179, 2235, 2240-2241, 2260, 2316-2338, 2441, 2557, 2580 |
| src/llm\_prompts/exit\_reason.py                                              |        9 |        0 |    100% |           |
| src/llm\_prompts/extension\_factories.py                                      |       12 |        0 |    100% |           |
| src/llm\_prompts/git\_snapshot.py                                             |      158 |        7 |     96% |123, 167, 200, 213, 217, 231, 296 |
| src/llm\_prompts/github\_api.py                                               |      100 |        1 |     99% |        77 |
| src/llm\_prompts/guards/\_\_init\_\_.py                                       |        0 |        0 |    100% |           |
| src/llm\_prompts/guards/commit\_guard.py                                      |      243 |        6 |     98% |67-68, 165, 410, 447, 466 |
| src/llm\_prompts/guards/gate.py                                               |        5 |        0 |    100% |           |
| src/llm\_prompts/guards/receipts.py                                           |       74 |        4 |     95% |71, 79, 102-103 |
| src/llm\_prompts/guards/review\_limit.py                                      |       68 |        8 |     88% |42-43, 73-74, 95, 129, 137-138 |
| src/llm\_prompts/guards/shell\_rules.py                                       |       90 |        2 |     98% |   99, 157 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/home.py                                                      |       90 |        4 |     96% |163-164, 179, 184 |
| src/llm\_prompts/hooks.py                                                     |      332 |       20 |     94% |94, 99, 192, 205-206, 356, 416-417, 443-445, 533, 541-542, 604, 619-620, 639-641 |
| src/llm\_prompts/install.py                                                   |     2387 |      151 |     94% |198, 598, 707, 717, 721-722, 1100, 1263-1265, 1317, 1320-1322, 1337, 1363, 1365, 1421-1422, 1586, 1595-1597, 1671, 1683, 1695, 1777-1778, 1860-1862, 1978, 1993-1994, 2076-2077, 2079, 2144, 2381-2382, 2450-2452, 2494, 2581-2583, 2885, 2989, 3048, 3404-3406, 3490, 3493, 3596-3611, 3621-3625, 3644-3651, 3703, 3782, 3791, 3860-3861, 3863-3864, 3911, 3915, 4051, 4244, 4283-4284, 4422, 4548-4561, 4574-4576, 4737-4741, 4751-4757, 4775-4781, 4787-4796, 4816-4817, 4885-4888, 4955-4957, 4989, 5051, 5054, 5160, 5180-5181, 5371, 5433, 5435, 5847, 5851, 5864 |
| src/llm\_prompts/jsonfile.py                                                  |       23 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      529 |       19 |     96% |190-191, 272-273, 358, 591, 666, 693-694, 892, 911-912, 930, 947, 960, 964, 1000, 1065, 1131 |
| src/llm\_prompts/manifest.py                                                  |       89 |        3 |     97% |69-70, 107 |
| src/llm\_prompts/mcp.py                                                       |       85 |        1 |     99% |        91 |
| src/llm\_prompts/network.py                                                   |       50 |        0 |    100% |           |
| src/llm\_prompts/overlay\_merge.py                                            |       52 |        2 |     96% |   71, 109 |
| src/llm\_prompts/path\_migration.py                                           |       94 |        2 |     98% |    24, 54 |
| src/llm\_prompts/plugins.py                                                   |      194 |       14 |     93% |47, 134-135, 139-140, 164-168, 184, 214, 243, 291, 301, 409, 465 |
| src/llm\_prompts/pr.py                                                        |      133 |        9 |     93% |96-112, 139, 277-278 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      689 |       10 |     99% |108, 159, 271, 676, 690, 1214-1217, 1311 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/git-usage/inspect\_range.py            |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-usage/rewrite\_range.py            |       90 |        3 |     97% |61, 64, 201 |
| src/llm\_prompts/prompts/shared/skills/pr-review/filter\_findings.py          |       64 |        3 |     95% | 45-46, 91 |
| src/llm\_prompts/prompts/shared/skills/session-start/checklist.py             |       51 |        1 |     98% |        98 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/removed\_agents\_notice.py                                   |       14 |        0 |    100% |           |
| src/llm\_prompts/render\_template.py                                          |      170 |       14 |     92% |147, 433-434, 443-460, 472-476, 480 |
| src/llm\_prompts/settings.py                                                  |       76 |        1 |     99% |        85 |
| src/llm\_prompts/settings\_app.py                                             |      327 |       16 |     95% |71, 83, 107, 125, 184-185, 215, 243, 274, 300, 305-306, 336, 340, 379, 534 |
| src/llm\_prompts/setup.py                                                     |      525 |       30 |     94% |231, 329-333, 344-348, 353, 362-369, 414, 463, 484-485, 531-532, 815-816, 962-963, 1106-1109, 1139-1140, 1143, 1206-1207 |
| src/llm\_prompts/size\_guard.py                                               |      451 |       10 |     98% |363-364, 599-601, 636, 658, 662-664 |
| src/llm\_prompts/size\_limits.py                                              |       67 |        1 |     99% |       155 |
| src/llm\_prompts/size\_report.py                                              |      207 |        2 |     99% |  207, 209 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| src/llm\_prompts/telemetry.py                                                 |       94 |        2 |     98% |   187-188 |
| src/llm\_prompts/telemetry\_core.py                                           |      224 |        5 |     98% |72-73, 186-187, 423 |
| src/llm\_prompts/tool\_paths.py                                               |       14 |        0 |    100% |           |
| src/llm\_prompts/watch/\_\_init\_\_.py                                        |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/\_\_init\_\_.py                                   |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/condition.py                                      |       36 |        3 |     92% | 51, 67-68 |
| src/llm\_prompts/watch/core/registry.py                                       |       13 |        0 |    100% |           |
| src/llm\_prompts/watch/core/runner.py                                         |       82 |        1 |     99% |        83 |
| src/llm\_prompts/watch/core/source.py                                         |       29 |        0 |    100% |           |
| src/llm\_prompts/watch/core/store.py                                          |       61 |        1 |     98% |        43 |
| src/llm\_prompts/watch/sources/\_\_init\_\_.py                                |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/sources/command.py                                     |       36 |        1 |     97% |        55 |
| src/llm\_prompts/watch/sources/github\_pr.py                                  |      171 |       11 |     94% |83-88, 108, 191-195, 200 |
| src/llm\_prompts/watch/sources/github\_triage.py                              |      104 |        6 |     94% |122, 150, 168, 227, 238-239 |
| src/llm\_prompts/watch/sources/rest.py                                        |       20 |        2 |     90% |     27-28 |
| src/llm\_prompts/worktrees.py                                                 |       89 |        3 |     97% |119, 148-149 |
| tests/benchmark/\_\_init\_\_.py                                               |        0 |        0 |    100% |           |
| tests/benchmark/conftest.py                                                   |      192 |        0 |    100% |           |
| tests/benchmark/test\_bench\_agents.py                                        |       61 |        0 |    100% |           |
| tests/benchmark/test\_bench\_audit.py                                         |       80 |        0 |    100% |           |
| tests/benchmark/test\_bench\_cell.py                                          |      233 |        4 |     98% |169, 292, 297, 409 |
| tests/benchmark/test\_bench\_check\_sandbox.py                                |       59 |        0 |    100% |           |
| tests/benchmark/test\_bench\_checks.py                                        |      191 |        0 |    100% |           |
| tests/benchmark/test\_bench\_command.py                                       |      425 |        0 |    100% |           |
| tests/benchmark/test\_bench\_e2e.py                                           |       56 |       32 |     43% |38-40, 51-57, 61, 69-115 |
| tests/benchmark/test\_bench\_env.py                                           |       58 |        0 |    100% |           |
| tests/benchmark/test\_bench\_fail\_fast.py                                    |       42 |        0 |    100% |           |
| tests/benchmark/test\_bench\_fork\_mode.py                                    |       36 |        0 |    100% |           |
| tests/benchmark/test\_bench\_guard\_pi.py                                     |       41 |        0 |    100% |           |
| tests/benchmark/test\_bench\_guard\_rules.py                                  |       17 |        0 |    100% |           |
| tests/benchmark/test\_bench\_live\_view.py                                    |       83 |        0 |    100% |           |
| tests/benchmark/test\_bench\_memory\_entry.py                                 |       43 |        0 |    100% |           |
| tests/benchmark/test\_bench\_memory\_metrics.py                               |       31 |        0 |    100% |           |
| tests/benchmark/test\_bench\_memory\_server.py                                |       79 |        1 |     99% |        85 |
| tests/benchmark/test\_bench\_paths.py                                         |       13 |        0 |    100% |           |
| tests/benchmark/test\_bench\_process.py                                       |      199 |        0 |    100% |           |
| tests/benchmark/test\_bench\_real\_sandbox.py                                 |       59 |       36 |     39% |40, 72, 75-76, 79, 84-91, 97-111, 117-135 |
| tests/benchmark/test\_bench\_repo\_checks.py                                  |      112 |        0 |    100% |           |
| tests/benchmark/test\_bench\_report.py                                        |      251 |        0 |    100% |           |
| tests/benchmark/test\_bench\_runner\_events.py                                |       87 |        0 |    100% |           |
| tests/benchmark/test\_bench\_sandbox\_policy.py                               |       78 |        0 |    100% |           |
| tests/benchmark/test\_bench\_scenarios.py                                     |      152 |        0 |    100% |           |
| tests/benchmark/test\_bench\_scheduler.py                                     |      332 |        0 |    100% |           |
| tests/benchmark/test\_bench\_tool\_dirs.py                                    |       36 |        0 |    100% |           |
| tests/benchmark/test\_bench\_types.py                                         |       15 |        0 |    100% |           |
| tests/benchmark/test\_bench\_variant.py                                       |      275 |        0 |    100% |           |
| tests/benchmark/traces.py                                                     |        3 |        0 |    100% |           |
| tests/conftest.py                                                             |      475 |       24 |     95% |168, 302-303, 306, 309, 312, 317, 372, 451-462, 467-469, 487-488, 502, 574-578, 670, 858, 898, 906 |
| tests/test\_auto\_update.py                                                   |      216 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      282 |        1 |     99% |       112 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_claude\_models.py                                                 |       25 |        0 |    100% |           |
| tests/test\_cli.py                                                            |     1225 |        1 |     99% |      1549 |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_clones.py                                                         |      251 |        0 |    100% |           |
| tests/test\_commit\_guard.py                                                  |      310 |        2 |     99% |   441-442 |
| tests/test\_config\_edit.py                                                   |       99 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       94 |        4 |     96% |194-196, 209 |
| tests/test\_contribute.py                                                     |      406 |        0 |    100% |           |
| tests/test\_contribute\_worktrees.py                                          |     2377 |        0 |    100% |           |
| tests/test\_e2e\_git.py                                                       |      240 |        0 |    100% |           |
| tests/test\_extension\_factories.py                                           |       29 |        0 |    100% |           |
| tests/test\_filter\_findings\_script.py                                       |       73 |        0 |    100% |           |
| tests/test\_focus.py                                                          |     1056 |        1 |     99% |        52 |
| tests/test\_git\_snapshot.py                                                  |      168 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      128 |        0 |    100% |           |
| tests/test\_handoff\_block.py                                                 |       14 |        0 |    100% |           |
| tests/test\_home.py                                                           |      163 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      705 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1748 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      668 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       62 |        4 |     94% |     20-23 |
| tests/test\_install\_claude.py                                                |      170 |        0 |    100% |           |
| tests/test\_install\_claude\_permissions.py                                   |      267 |        1 |     99% |       312 |
| tests/test\_install\_codex.py                                                 |      273 |        0 |    100% |           |
| tests/test\_install\_opencode.py                                              |       66 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1754 |        1 |     99% |      2479 |
| tests/test\_jsonfile.py                                                       |       23 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      318 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       83 |        0 |    100% |           |
| tests/test\_mcp.py                                                            |       27 |        2 |     93% |     43-44 |
| tests/test\_network.py                                                        |       42 |        0 |    100% |           |
| tests/test\_overlay\_merge.py                                                 |       19 |        0 |    100% |           |
| tests/test\_path\_migration.py                                                |      151 |        0 |    100% |           |
| tests/test\_pi\_context\_rules.py                                             |       19 |        0 |    100% |           |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      383 |        0 |    100% |           |
| tests/test\_pr.py                                                             |      146 |        0 |    100% |           |
| tests/test\_prompt\_checks\_entry\_points.py                                  |       13 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      816 |        0 |    100% |           |
| tests/test\_removed\_agents\_notice.py                                        |       29 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      143 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_review\_limit.py                                                  |       66 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       96 |        0 |    100% |           |
| tests/test\_session\_start\_checklist.py                                      |       38 |        0 |    100% |           |
| tests/test\_settings.py                                                       |       96 |        0 |    100% |           |
| tests/test\_settings\_app.py                                                  |      171 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      432 |        0 |    100% |           |
| tests/test\_shell\_rules.py                                                   |       39 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |      168 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      254 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       36 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_telemetry.py                                                      |      414 |        0 |    100% |           |
| tests/test\_telemetry\_core.py                                                |      164 |        1 |     99% |       126 |
| tests/test\_todos\_script.py                                                  |       88 |        0 |    100% |           |
| tests/test\_tool\_paths.py                                                    |       27 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      119 |        0 |    100% |           |
| tests/test\_worktrees.py                                                      |       82 |        0 |    100% |           |
| tests/watch/sources/test\_github\_pr.py                                       |      235 |        0 |    100% |           |
| tests/watch/sources/test\_github\_triage.py                                   |       92 |        0 |    100% |           |
| tests/watch/test\_runner.py                                                   |       84 |        0 |    100% |           |
| tests/watch/test\_watch\_cli.py                                               |       40 |        0 |    100% |           |
| **TOTAL**                                                                     | **37241** |  **836** | **98%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/alexfayers/llm-prompts/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/alexfayers/llm-prompts/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Falexfayers%2Fllm-prompts%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.