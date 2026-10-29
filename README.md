# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/cli.py                                                       |      568 |       73 |     87% |92-93, 119-120, 127-140, 246-247, 358-359, 487, 490, 539, 605-617, 641-643, 678-680, 688-691, 721-730, 997-999, 1002-1008, 1011-1013, 1016-1030, 1040, 1045, 1057, 1079-1083, 1177-1178, 1183 |
| src/llm\_prompts/collection\_size.py                                          |      115 |        5 |     96% |179, 235-236, 386, 443 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      867 |       11 |     99% |153, 300, 1124, 1149, 1349, 1366-1367, 1457-1459, 1800 |
| src/llm\_prompts/exit\_reason.py                                              |        8 |        0 |    100% |           |
| src/llm\_prompts/extension\_factories.py                                      |       10 |        0 |    100% |           |
| src/llm\_prompts/github\_api.py                                               |       97 |        1 |     99% |        73 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/herdsman.py                                                  |        9 |        0 |    100% |           |
| src/llm\_prompts/home.py                                                      |       20 |        0 |    100% |           |
| src/llm\_prompts/hooks.py                                                     |      215 |       18 |     92% |80, 85, 153-154, 226-227, 254-256, 333, 341-342, 384, 399-400, 419-421 |
| src/llm\_prompts/install.py                                                   |     1760 |      179 |     90% |117, 440-444, 476-478, 481, 506-509, 541, 551, 554-555, 660-661, 674, 781-783, 812, 814, 870-871, 1012, 1022-1023, 1080, 1089, 1122-1123, 1199-1201, 1317, 1324-1325, 1442, 1682-1683, 1751-1753, 1755, 1799, 1886-1888, 2140, 2244, 2303, 2537, 2561, 2663-2665, 2734, 2737, 2756, 2813-2828, 2837-2844, 2849-2859, 2864-2874, 2912, 3049-3050, 3052-3053, 3100, 3104, 3241, 3280-3281, 3419, 3478-3479, 3490-3503, 3508-3512, 3521-3530, 3535-3544, 3549-3558, 3563-3575, 3580-3589, 3643-3645, 3745, 3748, 3906, 3962, 3964, 4186, 4308, 4312, 4323 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      126 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      238 |        5 |     98% |258, 400-401, 419-420 |
| src/llm\_prompts/manifest.py                                                  |       72 |        3 |     96% | 50-51, 86 |
| src/llm\_prompts/mcp.py                                                       |       79 |        1 |     99% |        83 |
| src/llm\_prompts/network.py                                                   |       25 |        1 |     96% |        30 |
| src/llm\_prompts/overlay\_merge.py                                            |       49 |        2 |     96% |    54, 92 |
| src/llm\_prompts/plugins.py                                                   |      164 |       16 |     90% |46, 133-134, 138-139, 155-167, 183, 213, 242, 289, 299, 380, 384 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      689 |       10 |     99% |108, 159, 271, 676, 690, 1214-1217, 1311 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        3 |     95% |64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/removed\_agents\_notice.py                                   |       14 |        0 |    100% |           |
| src/llm\_prompts/render\_template.py                                          |      166 |       14 |     92% |149, 417-418, 427-443, 455-459, 463 |
| src/llm\_prompts/setup.py                                                     |      350 |       44 |     87% |232-261, 303-306, 313-314, 354, 357, 378-379, 418-419, 471, 635-638, 679-682, 712-713, 716, 768-769, 781-783 |
| src/llm\_prompts/size\_guard.py                                               |      354 |       11 |     97% |244-245, 352, 423-425, 460, 482, 486-488 |
| src/llm\_prompts/size\_limits.py                                              |       61 |        1 |     98% |       138 |
| src/llm\_prompts/size\_report.py                                              |      187 |        3 |     98% |144, 198, 200 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| src/llm\_prompts/telemetry.py                                                 |      208 |        3 |     99% |160-161, 417 |
| tests/conftest.py                                                             |      441 |        3 |     99% |158, 875, 914 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      282 |        1 |     99% |       112 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      847 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       77 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |     1877 |        0 |    100% |           |
| tests/test\_e2e\_git.py                                                       |      123 |        0 |    100% |           |
| tests/test\_extension\_factories.py                                           |       21 |        0 |    100% |           |
| tests/test\_focus.py                                                          |     1056 |        1 |     99% |        52 |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_handoff\_block.py                                                 |       14 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      409 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1201 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      602 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       62 |        4 |     94% |     20-23 |
| tests/test\_install\_codex.py                                                 |      237 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1356 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      263 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       73 |        0 |    100% |           |
| tests/test\_mcp.py                                                            |       19 |        0 |    100% |           |
| tests/test\_network.py                                                        |       14 |        0 |    100% |           |
| tests/test\_overlay\_merge.py                                                 |       19 |        0 |    100% |           |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      254 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      640 |        0 |    100% |           |
| tests/test\_removed\_agents\_notice.py                                        |       29 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      135 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      308 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       93 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      206 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       30 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_telemetry.py                                                      |      327 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       88 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      119 |        0 |    100% |           |
| **TOTAL**                                                                     | **19510** |  **537** | **97%** |           |


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