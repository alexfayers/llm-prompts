# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/attic/\_\_init\_\_.py                                        |        0 |        0 |    100% |           |
| src/llm\_prompts/attic/cli.py                                                 |       41 |        9 |     78% |58, 65-66, 69, 79-81, 84-85 |
| src/llm\_prompts/attic/manifest.py                                            |       53 |        4 |     92% |81, 92-93, 129 |
| src/llm\_prompts/attic/pinned.py                                              |        7 |        0 |    100% |           |
| src/llm\_prompts/auto\_update.py                                              |      146 |       12 |     92% |115-118, 142-145, 161-162, 179-181 |
| src/llm\_prompts/benchmark/\_\_init\_\_.py                                    |        1 |        0 |    100% |           |
| src/llm\_prompts/benchmark/agents/\_\_init\_\_.py                             |       18 |        2 |     89% |    25, 31 |
| src/llm\_prompts/benchmark/agents/adapter.py                                  |       34 |        0 |    100% |           |
| src/llm\_prompts/benchmark/agents/claude.py                                   |      158 |        3 |     98% |57, 133-134 |
| src/llm\_prompts/benchmark/agents/files.py                                    |       53 |        1 |     98% |        32 |
| src/llm\_prompts/benchmark/agents/pi.py                                       |      193 |        1 |     99% |       187 |
| src/llm\_prompts/benchmark/cell/\_\_init\_\_.py                               |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/cell/audit.py                                      |       97 |        3 |     97% |     59-61 |
| src/llm\_prompts/benchmark/cell/env.py                                        |       24 |        0 |    100% |           |
| src/llm\_prompts/benchmark/cell/home\_dirs.py                                 |       81 |        6 |     93% |60-63, 95, 105 |
| src/llm\_prompts/benchmark/cell/memory.py                                     |      121 |        3 |     98% |   151-153 |
| src/llm\_prompts/benchmark/cell/prepare.py                                    |      111 |        4 |     96% |     66-69 |
| src/llm\_prompts/benchmark/cell/shared.py                                     |       94 |        5 |     95% |64-65, 128-130 |
| src/llm\_prompts/benchmark/cell/variants.py                                   |      252 |       13 |     95% |58-59, 172, 198-199, 228, 382-383, 435-438, 440 |
| src/llm\_prompts/benchmark/command.py                                         |      221 |        1 |     99% |        91 |
| src/llm\_prompts/benchmark/fail\_fast.py                                      |       55 |        0 |    100% |           |
| src/llm\_prompts/benchmark/guard/\_\_init\_\_.py                              |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/guard/claude.py                                    |       26 |        1 |     96% |        64 |
| src/llm\_prompts/benchmark/live\_view.py                                      |      114 |        1 |     99% |       176 |
| src/llm\_prompts/benchmark/paths.py                                           |       51 |        2 |     96% |    26, 67 |
| src/llm\_prompts/benchmark/report/\_\_init\_\_.py                             |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/report/compare.py                                  |      357 |        3 |     99% |143, 342, 697 |
| src/llm\_prompts/benchmark/report/render.py                                   |       98 |        0 |    100% |           |
| src/llm\_prompts/benchmark/report/terminal.py                                 |       48 |        1 |     98% |       138 |
| src/llm\_prompts/benchmark/reuse.py                                           |       69 |        0 |    100% |           |
| src/llm\_prompts/benchmark/runner/\_\_init\_\_.py                             |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/runner/events.py                                   |       64 |        0 |    100% |           |
| src/llm\_prompts/benchmark/runner/process.py                                  |       83 |        3 |     96% | 67-68, 84 |
| src/llm\_prompts/benchmark/runner/sandbox.py                                  |       61 |        2 |     97% |     47-48 |
| src/llm\_prompts/benchmark/saved.py                                           |       34 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scenarios/\_\_init\_\_.py                          |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scenarios/checks/\_\_init\_\_.py                   |      138 |        1 |     99% |        95 |
| src/llm\_prompts/benchmark/scenarios/checks/context.py                        |       44 |        1 |     98% |        92 |
| src/llm\_prompts/benchmark/scenarios/checks/judge.py                          |       91 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scenarios/loader.py                                |      134 |        0 |    100% |           |
| src/llm\_prompts/benchmark/scheduler.py                                       |      347 |        6 |     98% |509, 516, 610, 612, 627, 654 |
| src/llm\_prompts/benchmark/transient.py                                       |       41 |        0 |    100% |           |
| src/llm\_prompts/benchmark/types.py                                           |      206 |        0 |    100% |           |
| src/llm\_prompts/claude\_models.py                                            |       23 |        0 |    100% |           |
| src/llm\_prompts/cli.py                                                       |      905 |       65 |     93% |109-110, 136-137, 144-157, 263-264, 279-284, 426, 704, 707, 730, 757, 795, 826, 958, 1166-1168, 1181-1184, 1254-1263, 1776-1778, 1781-1787, 1799-1801, 1812-1818, 1828, 1833, 1845, 2006, 2034-2035, 2040 |
| src/llm\_prompts/collection\_size.py                                          |      133 |        3 |     98% |295-296, 500 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/config\_edit.py                                              |       58 |        1 |     98% |        74 |
| src/llm\_prompts/console.py                                                   |       18 |        1 |     94% |        48 |
| src/llm\_prompts/contribute.py                                                |     1220 |       61 |     95% |108, 175, 202-203, 244-245, 277-278, 422, 566-567, 600, 772, 775, 832, 843, 953-954, 999, 1145-1146, 1183, 1571-1574, 1752, 1754, 1768-1769, 1778-1779, 1798, 1809-1810, 1881, 1937-1942, 1946, 2062, 2089-2090, 2142, 2147-2148, 2167, 2223-2245, 2347, 2463, 2486 |
| src/llm\_prompts/exit\_reason.py                                              |        9 |        0 |    100% |           |
| src/llm\_prompts/extension\_factories.py                                      |       12 |        0 |    100% |           |
| src/llm\_prompts/git\_snapshot.py                                             |      102 |        5 |     95% |114, 134, 147, 151, 165 |
| src/llm\_prompts/github\_api.py                                               |      100 |        1 |     99% |        77 |
| src/llm\_prompts/guards/\_\_init\_\_.py                                       |        0 |        0 |    100% |           |
| src/llm\_prompts/guards/commit\_guard.py                                      |      232 |        6 |     97% |66-67, 162, 396, 428, 447 |
| src/llm\_prompts/guards/gate.py                                               |        5 |        0 |    100% |           |
| src/llm\_prompts/guards/receipts.py                                           |       74 |        4 |     95% |71, 79, 102-103 |
| src/llm\_prompts/guards/review\_limit.py                                      |       57 |        8 |     86% |42-43, 53, 100, 108-109, 128-129 |
| src/llm\_prompts/guards/shell\_rules.py                                       |       90 |        2 |     98% |   99, 157 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/home.py                                                      |       20 |        0 |    100% |           |
| src/llm\_prompts/hooks.py                                                     |      332 |       20 |     94% |94, 99, 192, 205-206, 356, 416-417, 443-445, 533, 541-542, 604, 619-620, 639-641 |
| src/llm\_prompts/install.py                                                   |     2269 |      152 |     93% |190, 595, 642, 707, 717, 721-722, 882, 1099, 1259-1261, 1313, 1316-1318, 1333, 1359, 1361, 1417-1418, 1582, 1591-1593, 1667, 1679, 1691, 1773-1774, 1856-1858, 1976, 1991-1992, 2074-2075, 2077, 2142, 2379-2380, 2448-2450, 2452, 2496, 2583-2585, 2881, 2985, 3044, 3400-3402, 3486, 3489, 3517, 3584-3599, 3609-3613, 3632-3639, 3687, 3766, 3775, 3844-3845, 3847-3848, 3895, 3899, 4015, 4207, 4246-4247, 4385, 4511-4524, 4537-4539, 4553-4557, 4567-4573, 4591-4597, 4603-4612, 4632-4633, 4691-4694, 4801, 4804, 4903, 4923-4924, 5114, 5176, 5178, 5443, 5566, 5570, 5583 |
| src/llm\_prompts/jsonfile.py                                                  |       23 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      529 |       19 |     96% |201-202, 281-282, 353, 586, 661, 688-689, 875, 894-895, 913, 930, 943, 947, 983, 1048, 1123 |
| src/llm\_prompts/manifest.py                                                  |       72 |        3 |     96% | 50-51, 86 |
| src/llm\_prompts/mcp.py                                                       |       85 |        1 |     99% |        91 |
| src/llm\_prompts/network.py                                                   |       46 |        0 |    100% |           |
| src/llm\_prompts/overlay\_merge.py                                            |       52 |        2 |     96% |   71, 109 |
| src/llm\_prompts/plugins.py                                                   |      194 |       15 |     92% |46, 133-134, 138-139, 163-167, 183, 213, 242, 290, 300, 408, 464, 468 |
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
| src/llm\_prompts/setup.py                                                     |      512 |       30 |     94% |230, 328-332, 343-347, 352, 361-368, 413, 464, 485-486, 532-533, 815-816, 957-958, 1089-1092, 1122-1123, 1126, 1183-1184 |
| src/llm\_prompts/size\_guard.py                                               |      435 |       10 |     98% |353-354, 595-597, 632, 654, 658-660 |
| src/llm\_prompts/size\_limits.py                                              |       67 |        1 |     99% |       155 |
| src/llm\_prompts/size\_report.py                                              |      207 |        2 |     99% |  207, 209 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| src/llm\_prompts/telemetry.py                                                 |       82 |        2 |     98% |   152-153 |
| src/llm\_prompts/telemetry\_core.py                                           |      224 |        5 |     98% |72-73, 186-187, 423 |
| src/llm\_prompts/watch/\_\_init\_\_.py                                        |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/\_\_init\_\_.py                                   |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/condition.py                                      |       25 |        3 |     88% | 33, 49-50 |
| src/llm\_prompts/watch/core/registry.py                                       |       13 |        0 |    100% |           |
| src/llm\_prompts/watch/core/runner.py                                         |       81 |        1 |     99% |        83 |
| src/llm\_prompts/watch/core/source.py                                         |       29 |        0 |    100% |           |
| src/llm\_prompts/watch/core/store.py                                          |       60 |        1 |     98% |        48 |
| src/llm\_prompts/watch/sources/\_\_init\_\_.py                                |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/sources/command.py                                     |       36 |        1 |     97% |        55 |
| src/llm\_prompts/watch/sources/github\_pr.py                                  |      164 |       11 |     93% |78-83, 102, 173-177, 182 |
| src/llm\_prompts/watch/sources/github\_triage.py                              |      104 |        6 |     94% |122, 150, 168, 227, 238-239 |
| src/llm\_prompts/watch/sources/rest.py                                        |       20 |        2 |     90% |     27-28 |
| src/llm\_prompts/worktrees.py                                                 |       89 |        3 |     97% |121, 150-151 |
| tests/benchmark/\_\_init\_\_.py                                               |        0 |        0 |    100% |           |
| tests/benchmark/conftest.py                                                   |      192 |        0 |    100% |           |
| tests/benchmark/test\_bench\_agents.py                                        |       54 |        0 |    100% |           |
| tests/benchmark/test\_bench\_audit.py                                         |       63 |        0 |    100% |           |
| tests/benchmark/test\_bench\_cell.py                                          |      233 |        4 |     98% |169, 292, 297, 409 |
| tests/benchmark/test\_bench\_check\_sandbox.py                                |       59 |        0 |    100% |           |
| tests/benchmark/test\_bench\_checks.py                                        |      186 |        0 |    100% |           |
| tests/benchmark/test\_bench\_command.py                                       |      419 |        0 |    100% |           |
| tests/benchmark/test\_bench\_e2e.py                                           |       54 |       31 |     43% |39-40, 49-55, 59, 67-113 |
| tests/benchmark/test\_bench\_env.py                                           |       54 |        0 |    100% |           |
| tests/benchmark/test\_bench\_fail\_fast.py                                    |       42 |        0 |    100% |           |
| tests/benchmark/test\_bench\_guard\_pi.py                                     |       41 |        0 |    100% |           |
| tests/benchmark/test\_bench\_guard\_rules.py                                  |       17 |        0 |    100% |           |
| tests/benchmark/test\_bench\_live\_view.py                                    |       83 |        0 |    100% |           |
| tests/benchmark/test\_bench\_memory\_entry.py                                 |       43 |        0 |    100% |           |
| tests/benchmark/test\_bench\_memory\_metrics.py                               |       31 |        0 |    100% |           |
| tests/benchmark/test\_bench\_memory\_server.py                                |       79 |        1 |     99% |        85 |
| tests/benchmark/test\_bench\_paths.py                                         |       13 |        0 |    100% |           |
| tests/benchmark/test\_bench\_process.py                                       |      175 |        0 |    100% |           |
| tests/benchmark/test\_bench\_real\_sandbox.py                                 |       59 |       36 |     39% |40, 72, 75-76, 79, 84-91, 97-111, 117-135 |
| tests/benchmark/test\_bench\_repo\_checks.py                                  |      112 |        0 |    100% |           |
| tests/benchmark/test\_bench\_report.py                                        |      243 |        0 |    100% |           |
| tests/benchmark/test\_bench\_runner\_events.py                                |       87 |        0 |    100% |           |
| tests/benchmark/test\_bench\_sandbox\_policy.py                               |       78 |        0 |    100% |           |
| tests/benchmark/test\_bench\_scenarios.py                                     |      143 |        0 |    100% |           |
| tests/benchmark/test\_bench\_scheduler.py                                     |      332 |        0 |    100% |           |
| tests/benchmark/test\_bench\_tool\_dirs.py                                    |       36 |        0 |    100% |           |
| tests/benchmark/test\_bench\_types.py                                         |        5 |        0 |    100% |           |
| tests/benchmark/test\_bench\_variant.py                                       |      275 |        0 |    100% |           |
| tests/benchmark/traces.py                                                     |        3 |        0 |    100% |           |
| tests/conftest.py                                                             |      462 |       24 |     95% |161, 295-296, 299, 302, 305, 310, 365, 444-455, 460-462, 480-481, 495, 567-571, 661, 824, 864, 872 |
| tests/test\_attic.py                                                          |       36 |        0 |    100% |           |
| tests/test\_auto\_update.py                                                   |      216 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      282 |        1 |     99% |       112 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_claude\_models.py                                                 |       25 |        0 |    100% |           |
| tests/test\_cli.py                                                            |     1219 |        1 |     99% |      1551 |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_commit\_guard.py                                                  |      288 |        2 |     99% |   420-421 |
| tests/test\_config\_edit.py                                                   |       99 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       94 |        4 |     96% |194-196, 209 |
| tests/test\_contribute.py                                                     |      401 |        0 |    100% |           |
| tests/test\_contribute\_worktrees.py                                          |     2178 |        0 |    100% |           |
| tests/test\_e2e\_git.py                                                       |      240 |        0 |    100% |           |
| tests/test\_extension\_factories.py                                           |       29 |        0 |    100% |           |
| tests/test\_filter\_findings\_script.py                                       |       73 |        0 |    100% |           |
| tests/test\_focus.py                                                          |     1056 |        1 |     99% |        52 |
| tests/test\_git\_snapshot.py                                                  |      127 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      128 |        0 |    100% |           |
| tests/test\_handoff\_block.py                                                 |       14 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      705 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1712 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      668 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       62 |        4 |     94% |     20-23 |
| tests/test\_install\_claude.py                                                |      170 |        0 |    100% |           |
| tests/test\_install\_codex.py                                                 |      273 |        0 |    100% |           |
| tests/test\_install\_opencode.py                                              |       66 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1653 |        1 |     99% |      2334 |
| tests/test\_jsonfile.py                                                       |       23 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      318 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       73 |        0 |    100% |           |
| tests/test\_mcp.py                                                            |       27 |        2 |     93% |     43-44 |
| tests/test\_network.py                                                        |       33 |        0 |    100% |           |
| tests/test\_overlay\_merge.py                                                 |       19 |        0 |    100% |           |
| tests/test\_pi\_context\_rules.py                                             |       19 |        0 |    100% |           |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      377 |        0 |    100% |           |
| tests/test\_pr.py                                                             |      146 |        0 |    100% |           |
| tests/test\_prompt\_checks\_entry\_points.py                                  |       13 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      803 |        0 |    100% |           |
| tests/test\_removed\_agents\_notice.py                                        |       29 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      143 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_review\_limit.py                                                  |       66 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       96 |        0 |    100% |           |
| tests/test\_session\_start\_checklist.py                                      |       38 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      432 |        0 |    100% |           |
| tests/test\_shell\_rules.py                                                   |       39 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |      168 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      254 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       36 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_telemetry.py                                                      |      384 |        0 |    100% |           |
| tests/test\_telemetry\_core.py                                                |      164 |        1 |     99% |       126 |
| tests/test\_todos\_script.py                                                  |       88 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      119 |        0 |    100% |           |
| tests/test\_worktrees.py                                                      |       82 |        0 |    100% |           |
| tests/watch/sources/test\_github\_pr.py                                       |      201 |        0 |    100% |           |
| tests/watch/sources/test\_github\_triage.py                                   |       92 |        0 |    100% |           |
| tests/watch/test\_runner.py                                                   |       70 |        0 |    100% |           |
| tests/watch/test\_watch\_cli.py                                               |       40 |        0 |    100% |           |
| **TOTAL**                                                                     | **34454** |  **811** | **98%** |           |


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