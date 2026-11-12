# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/claude\_models.py                                            |       23 |        0 |    100% |           |
| src/llm\_prompts/cli.py                                                       |      588 |       73 |     88% |92-93, 119-120, 127-140, 246-247, 358-359, 487, 490, 539, 605-617, 648-650, 685-687, 695-698, 727-736, 1040-1042, 1045-1051, 1054-1056, 1059-1073, 1083, 1088, 1100, 1122-1126, 1233-1234, 1239 |
| src/llm\_prompts/collection\_size.py                                          |      115 |        5 |     96% |179, 235-236, 386, 443 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      867 |       11 |     99% |153, 300, 1124, 1149, 1349, 1366-1367, 1457-1459, 1800 |
| src/llm\_prompts/exit\_reason.py                                              |        8 |        0 |    100% |           |
| src/llm\_prompts/extension\_factories.py                                      |       10 |        0 |    100% |           |
| src/llm\_prompts/github\_api.py                                               |       97 |        1 |     99% |        73 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/herdsman.py                                                  |        9 |        0 |    100% |           |
| src/llm\_prompts/home.py                                                      |       20 |        0 |    100% |           |
| src/llm\_prompts/hooks.py                                                     |      228 |       18 |     92% |81, 86, 179-180, 252-253, 280-282, 361, 369-370, 412, 427-428, 447-449 |
| src/llm\_prompts/install.py                                                   |     1855 |      175 |     91% |120, 509-513, 551-553, 556, 587-590, 623, 633, 637-638, 743-744, 757, 865-867, 919, 922-924, 939, 965, 967, 1023-1024, 1170, 1179-1181, 1250, 1259, 1298-1299, 1375-1377, 1493, 1500-1501, 1583-1584, 1586, 1651, 1889-1890, 1958-1960, 1962, 2006, 2093-2095, 2347, 2451, 2510, 2746, 2771, 2873-2875, 2944, 2947, 2966, 3025-3040, 3049-3055, 3060-3069, 3074-3083, 3121, 3258-3259, 3261-3262, 3309, 3313, 3450, 3489-3490, 3628, 3687-3688, 3697-3710, 3715-3719, 3728-3736, 3741-3749, 3754-3762, 3767-3778, 3787-3788, 3846-3849, 3957, 3960, 4120, 4180, 4182, 4432, 4555, 4559, 4570 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      126 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      238 |        5 |     98% |258, 400-401, 419-420 |
| src/llm\_prompts/manifest.py                                                  |       72 |        3 |     96% | 50-51, 86 |
| src/llm\_prompts/mcp.py                                                       |       85 |        1 |     99% |        91 |
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
| src/llm\_prompts/setup.py                                                     |      350 |       44 |     87% |232-261, 303-306, 313-314, 354, 357, 378-379, 418-419, 471, 635-638, 679-682, 712-713, 716, 768-769, 784-786 |
| src/llm\_prompts/size\_guard.py                                               |      354 |       11 |     97% |244-245, 352, 423-425, 460, 482, 486-488 |
| src/llm\_prompts/size\_limits.py                                              |       61 |        1 |     98% |       138 |
| src/llm\_prompts/size\_report.py                                              |      187 |        3 |     98% |144, 198, 200 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| src/llm\_prompts/telemetry.py                                                 |      208 |        3 |     99% |160-161, 417 |
| src/llm\_prompts/watch/\_\_init\_\_.py                                        |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/\_\_init\_\_.py                                   |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/condition.py                                      |       25 |        3 |     88% | 33, 49-50 |
| src/llm\_prompts/watch/core/registry.py                                       |       12 |        0 |    100% |           |
| src/llm\_prompts/watch/core/runner.py                                         |       37 |        1 |     97% |        29 |
| src/llm\_prompts/watch/core/source.py                                         |       21 |        0 |    100% |           |
| src/llm\_prompts/watch/sources/\_\_init\_\_.py                                |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/sources/command.py                                     |       36 |        1 |     97% |        55 |
| src/llm\_prompts/watch/sources/github\_pr.py                                  |       84 |       11 |     87% |29, 44-49, 86-87, 91, 102-103, 115 |
| tests/conftest.py                                                             |      458 |        4 |     99% |159, 799, 886, 925 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      282 |        1 |     99% |       112 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_claude\_models.py                                                 |       25 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      875 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       77 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |     1877 |        0 |    100% |           |
| tests/test\_e2e\_git.py                                                       |      123 |        0 |    100% |           |
| tests/test\_extension\_factories.py                                           |       21 |        0 |    100% |           |
| tests/test\_focus.py                                                          |     1056 |        1 |     99% |        52 |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_handoff\_block.py                                                 |       14 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      422 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1276 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      603 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       62 |        4 |     94% |     20-23 |
| tests/test\_install\_codex.py                                                 |      269 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1392 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      263 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       73 |        0 |    100% |           |
| tests/test\_mcp.py                                                            |       27 |        2 |     93% |     43-44 |
| tests/test\_network.py                                                        |       14 |        0 |    100% |           |
| tests/test\_overlay\_merge.py                                                 |       19 |        0 |    100% |           |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      254 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      640 |        0 |    100% |           |
| tests/test\_removed\_agents\_notice.py                                        |       29 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      135 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      312 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       93 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      206 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       30 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_telemetry.py                                                      |      327 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       88 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      119 |        0 |    100% |           |
| tests/test\_workflows.py                                                      |       25 |        0 |    100% |           |
| tests/watch/sources/test\_github\_pr.py                                       |       64 |        0 |    100% |           |
| tests/watch/test\_watch\_cli.py                                               |       40 |        0 |    100% |           |
| **TOTAL**                                                                     | **20250** |  **552** | **97%** |           |


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