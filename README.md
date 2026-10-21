# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/cli.py                                                       |      544 |       72 |     87% |89-90, 116-117, 124-137, 243-244, 355-356, 484, 487, 536, 602-614, 638-640, 675-677, 685-688, 707-716, 983-985, 988-994, 997-999, 1002-1016, 1026, 1031, 1048-1052, 1138-1139, 1144 |
| src/llm\_prompts/collection\_size.py                                          |      115 |        5 |     96% |178, 238-239, 389, 446 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      875 |       12 |     99% |149, 176, 318, 1141, 1166, 1366, 1383-1384, 1474-1476, 1817 |
| src/llm\_prompts/extension\_factories.py                                      |       10 |        0 |    100% |           |
| src/llm\_prompts/github\_api.py                                               |       96 |        1 |     99% |        71 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/herdsman.py                                                  |        9 |        0 |    100% |           |
| src/llm\_prompts/home.py                                                      |       20 |        0 |    100% |           |
| src/llm\_prompts/hooks.py                                                     |      215 |       18 |     92% |80, 85, 153-154, 226-227, 254-256, 333, 341-342, 384, 399-400, 419-421 |
| src/llm\_prompts/install.py                                                   |     1713 |      196 |     89% |103, 287-288, 330-331, 402-406, 438-440, 443, 468-471, 503, 506-507, 513, 516-517, 634-635, 648, 753-755, 784, 786, 842-843, 959, 969-970, 1043, 1046-1047, 1121-1123, 1157, 1232, 1239-1240, 1356, 1591-1592, 1660-1662, 1664, 1707, 1789-1790, 1794-1796, 1947-1948, 2050, 2154, 2213, 2447, 2471, 2576-2578, 2647, 2650, 2669, 2710-2713, 2716-2717, 2744-2764, 2773-2780, 2785-2795, 2800-2810, 2844, 2974-2975, 2977-2978, 3023, 3027, 3120, 3153-3154, 3292, 3347-3348, 3354-3367, 3372-3376, 3385-3394, 3399-3408, 3413-3422, 3427-3439, 3444-3453, 3508-3509, 3610, 3613, 3745, 3823, 3825, 4138, 4142, 4153 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      126 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      195 |        1 |     99% |       234 |
| src/llm\_prompts/manifest.py                                                  |       72 |        3 |     96% | 50-51, 86 |
| src/llm\_prompts/mcp.py                                                       |       76 |        3 |     96% |82, 157-158 |
| src/llm\_prompts/plugins.py                                                   |      163 |       16 |     90% |45, 132-133, 137-138, 154-166, 182, 212, 241, 288, 298, 379, 383 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      689 |       10 |     99% |108, 159, 271, 676, 690, 1214-1217, 1311 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        4 |     94% |56, 64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/render\_template.py                                          |      184 |       15 |     92% |149, 323, 459-460, 469-487, 499-503, 507 |
| src/llm\_prompts/setup.py                                                     |      326 |       60 |     82% |229-258, 300-303, 310-311, 351, 354, 375-376, 415-416, 565, 591-594, 599-611, 621, 632-638, 668-669, 672, 701-703, 722-723, 735-737 |
| src/llm\_prompts/size\_guard.py                                               |      351 |       11 |     97% |242-243, 350, 421-423, 458, 480, 484-486 |
| src/llm\_prompts/size\_limits.py                                              |       61 |        1 |     98% |       138 |
| src/llm\_prompts/size\_report.py                                              |      172 |        3 |     98% |134, 188, 190 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| src/llm\_prompts/telemetry.py                                                 |      147 |        5 |     97% |89-90, 135-136, 302 |
| tests/conftest.py                                                             |      361 |        3 |     99% |156, 789, 828 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      179 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      819 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       60 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |     1872 |        0 |    100% |           |
| tests/test\_extension\_factories.py                                           |       21 |        0 |    100% |           |
| tests/test\_focus.py                                                          |     1043 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_handoff\_block.py                                                 |       14 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      408 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1110 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      583 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       60 |        4 |     93% |     18-21 |
| tests/test\_install\_codex.py                                                 |      234 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1260 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      243 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       73 |        0 |    100% |           |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      254 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      638 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      135 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      266 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       93 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      190 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       30 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_telemetry.py                                                      |      218 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      114 |        0 |    100% |           |
| **TOTAL**                                                                     | **18361** |  **567** | **97%** |           |


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