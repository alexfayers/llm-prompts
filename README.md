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
| src/llm\_prompts/benchmark/agents/pi.py                                       |      187 |        1 |     99% |       169 |
| src/llm\_prompts/benchmark/cell/\_\_init\_\_.py                               |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/cell/audit.py                                      |       98 |        3 |     97% |     60-62 |
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
| src/llm\_prompts/cli.py                                                       |      905 |       65 |     93% |107-108, 134-135, 142-155, 261-262, 277-282, 424, 702, 705, 728, 755, 793, 824, 956, 1164-1166, 1179-1182, 1252-1261, 1782-1784, 1787-1793, 1805-1807, 1818-1824, 1834, 1839, 1851, 2014, 2042-2043, 2048 |
| src/llm\_prompts/clones.py                                                    |      150 |       14 |     91% |44-45, 83, 101-102, 135-137, 190-192, 256, 274-275 |
| src/llm\_prompts/collection\_size.py                                          |      133 |        3 |     98% |295-296, 500 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/config\_edit.py                                              |       58 |        1 |     98% |        74 |
| src/llm\_prompts/console.py                                                   |       18 |        1 |     94% |        48 |
| src/llm\_prompts/contribute.py                                                |     1253 |       62 |     95% |116, 220, 247-248, 289-290, 322-323, 467, 611-612, 645, 817, 820, 877, 888, 998-999, 1044, 1148, 1194-1195, 1208, 1614-1617, 1795, 1797, 1811-1812, 1821-1822, 1841, 1852-1853, 1924, 1980-1985, 1989, 2105, 2132-2133, 2185, 2190-2191, 2210, 2266-2288, 2390, 2506, 2529 |
| src/llm\_prompts/exit\_reason.py                                              |        9 |        0 |    100% |           |
| src/llm\_prompts/extension\_factories.py                                      |       12 |        0 |    100% |           |
| src/llm\_prompts/git\_snapshot.py                                             |      158 |        7 |     96% |123, 167, 200, 213, 217, 231, 296 |
| src/llm\_prompts/github\_api.py                                               |      100 |        1 |     99% |        77 |
| src/llm\_prompts/guards/\_\_init\_\_.py                                       |        0 |        0 |    100% |           |
| src/llm\_prompts/guards/commit\_guard.py                                      |      232 |        6 |     97% |66-67, 162, 396, 428, 447 |
| src/llm\_prompts/guards/gate.py                                               |        5 |        0 |    100% |           |
| src/llm\_prompts/guards/receipts.py                                           |       74 |        4 |     95% |71, 79, 102-103 |
| src/llm\_prompts/guards/review\_limit.py                                      |       57 |        8 |     86% |42-43, 53, 100, 108-109, 128-129 |
| src/llm\_prompts/guards/shell\_rules.py                                       |       90 |        2 |     98% |   99, 157 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/home.py                                                      |       85 |        2 |     98% |  171, 176 |
| src/llm\_prompts/hooks.py                                                     |      332 |       20 |     94% |94, 99, 192, 205-206, 356, 416-417, 443-445, 533, 541-542, 604, 619-620, 639-641 |
| src/llm\_prompts/install.py                                                   |     2370 |      156 |     93% |192, 592, 639, 704, 714, 718-719, 879, 1096, 1256-1258, 1310, 1313-1315, 1330, 1356, 1358, 1414-1415, 1579, 1588-1590, 1664, 1676, 1688, 1770-1771, 1853-1855, 1973, 1988-1989, 2071-2072, 2074, 2139, 2376-2377, 2445-2447, 2449, 2493, 2580-2582, 2878, 2982, 3041, 3397-3399, 3483, 3486, 3514, 3581-3596, 3606-3610, 3629-3636, 3684, 3763, 3772, 3841-3842, 3844-3845, 3892, 3896, 4013, 4205, 4244-4245, 4383, 4509-4522, 4535-4537, 4698-4702, 4712-4718, 4736-4742, 4748-4757, 4777-4778, 4836-4839, 4906-4908, 4940, 5002, 5005, 5111, 5131-5132, 5322, 5384, 5386, 5659, 5785, 5789, 5802 |
| src/llm\_prompts/jsonfile.py                                                  |       23 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      529 |       19 |     96% |190-191, 272-273, 358, 591, 666, 693-694, 892, 911-912, 930, 947, 960, 964, 1000, 1065, 1131 |
| src/llm\_prompts/manifest.py                                                  |       89 |        3 |     97% |69-70, 107 |
| src/llm\_prompts/mcp.py                                                       |       85 |        1 |     99% |        91 |
| src/llm\_prompts/network.py                                                   |       46 |        0 |    100% |           |
| src/llm\_prompts/overlay\_merge.py                                            |       52 |        2 |     96% |   71, 109 |
| src/llm\_prompts/path\_migration.py                                           |       94 |        2 |     98% |    24, 54 |
| src/llm\_prompts/plugins.py                                                   |      194 |       15 |     92% |47, 134-135, 139-140, 164-168, 184, 214, 243, 291, 301, 409, 465, 469 |
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
| src/llm\_prompts/settings.py                                                  |       65 |        1 |     98% |        84 |
| src/llm\_prompts/settings\_app.py                                             |      165 |        9 |     95% |46, 73, 78-79, 109, 113, 153, 159, 267 |
| src/llm\_prompts/setup.py                                                     |      525 |       30 |     94% |231, 329-333, 344-348, 353, 362-369, 414, 463, 484-485, 531-532, 815-816, 962-963, 1106-1109, 1139-1140, 1143, 1206-1207 |
| src/llm\_prompts/size\_guard.py                                               |      435 |       10 |     98% |353-354, 595-597, 632, 654, 658-660 |
| src/llm\_prompts/size\_limits.py                                              |       67 |        1 |     99% |       155 |
| src/llm\_prompts/size\_report.py                                              |      207 |        2 |     99% |  207, 209 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| src/llm\_prompts/telemetry.py                                                 |       82 |        2 |     98% |   152-153 |
| src/llm\_prompts/telemetry\_core.py                                           |      224 |        5 |     98% |72-73, 186-187, 423 |
| src/llm\_prompts/tool\_paths.py                                               |       14 |        0 |    100% |           |
| src/llm\_prompts/watch/\_\_init\_\_.py                                        |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/\_\_init\_\_.py                                   |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/condition.py                                      |       25 |        3 |     88% | 33, 49-50 |
| src/llm\_prompts/watch/core/registry.py                                       |       13 |        0 |    100% |           |
| src/llm\_prompts/watch/core/runner.py                                         |       81 |        1 |     99% |        83 |
| src/llm\_prompts/watch/core/source.py                                         |       29 |        0 |    100% |           |
| src/llm\_prompts/watch/core/store.py                                          |       61 |        1 |     98% |        43 |
| src/llm\_prompts/watch/sources/\_\_init\_\_.py                                |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/sources/command.py                                     |       36 |        1 |     97% |        55 |
| src/llm\_prompts/watch/sources/github\_pr.py                                  |      164 |       11 |     93% |78-83, 102, 173-177, 182 |
| src/llm\_prompts/watch/sources/github\_triage.py                              |      104 |        6 |     94% |122, 150, 168, 227, 238-239 |
| src/llm\_prompts/watch/sources/rest.py                                        |       20 |        2 |     90% |     27-28 |
| src/llm\_prompts/worktrees.py                                                 |       89 |        3 |     97% |119, 148-149 |
| tests/benchmark/\_\_init\_\_.py                                               |        0 |        0 |    100% |           |
| tests/benchmark/conftest.py                                                   |      192 |        0 |    100% |           |
| tests/benchmark/test\_bench\_agents.py                                        |       43 |        0 |    100% |           |
| tests/benchmark/test\_bench\_audit.py                                         |       67 |        0 |    100% |           |
| tests/benchmark/test\_bench\_cell.py                                          |      233 |        4 |     98% |169, 292, 297, 409 |
| tests/benchmark/test\_bench\_check\_sandbox.py                                |       59 |        0 |    100% |           |
| tests/benchmark/test\_bench\_checks.py                                        |      186 |        0 |    100% |           |
| tests/benchmark/test\_bench\_command.py                                       |      419 |        0 |    100% |           |
| tests/benchmark/test\_bench\_e2e.py                                           |       56 |       32 |     43% |38-40, 51-57, 61, 69-115 |
| tests/benchmark/test\_bench\_env.py                                           |       58 |        0 |    100% |           |
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
| tests/conftest.py                                                             |      475 |       24 |     95% |168, 302-303, 306, 309, 312, 317, 372, 451-462, 467-469, 487-488, 502, 574-578, 670, 858, 898, 906 |
| tests/test\_auto\_update.py                                                   |      216 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      282 |        1 |     99% |       112 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_claude\_models.py                                                 |       25 |        0 |    100% |           |
| tests/test\_cli.py                                                            |     1219 |        1 |     99% |      1549 |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_clones.py                                                         |      251 |        0 |    100% |           |
| tests/test\_commit\_guard.py                                                  |      288 |        2 |     99% |   420-421 |
| tests/test\_config\_edit.py                                                   |       99 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       94 |        4 |     96% |194-196, 209 |
| tests/test\_contribute.py                                                     |      401 |        0 |    100% |           |
| tests/test\_contribute\_worktrees.py                                          |     2237 |        0 |    100% |           |
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
| tests/test\_install.py                                                        |     1713 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      668 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       62 |        4 |     94% |     20-23 |
| tests/test\_install\_claude.py                                                |      170 |        0 |    100% |           |
| tests/test\_install\_claude\_permissions.py                                   |      267 |        1 |     99% |       312 |
| tests/test\_install\_codex.py                                                 |      273 |        0 |    100% |           |
| tests/test\_install\_opencode.py                                              |       66 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1657 |        1 |     99% |      2337 |
| tests/test\_jsonfile.py                                                       |       23 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      318 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       83 |        0 |    100% |           |
| tests/test\_mcp.py                                                            |       27 |        2 |     93% |     43-44 |
| tests/test\_network.py                                                        |       33 |        0 |    100% |           |
| tests/test\_overlay\_merge.py                                                 |       19 |        0 |    100% |           |
| tests/test\_path\_migration.py                                                |      151 |        0 |    100% |           |
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
| tests/test\_settings.py                                                       |       73 |        0 |    100% |           |
| tests/test\_settings\_app.py                                                  |       98 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      432 |        0 |    100% |           |
| tests/test\_shell\_rules.py                                                   |       39 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |      168 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      254 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       36 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_telemetry.py                                                      |      384 |        0 |    100% |           |
| tests/test\_telemetry\_core.py                                                |      164 |        1 |     99% |       126 |
| tests/test\_todos\_script.py                                                  |       88 |        0 |    100% |           |
| tests/test\_tool\_paths.py                                                    |       27 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      119 |        0 |    100% |           |
| tests/test\_worktrees.py                                                      |       82 |        0 |    100% |           |
| tests/watch/sources/test\_github\_pr.py                                       |      207 |        0 |    100% |           |
| tests/watch/sources/test\_github\_triage.py                                   |       92 |        0 |    100% |           |
| tests/watch/test\_runner.py                                                   |       70 |        0 |    100% |           |
| tests/watch/test\_watch\_cli.py                                               |       40 |        0 |    100% |           |
| **TOTAL**                                                                     | **36252** |  **835** | **98%** |           |


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