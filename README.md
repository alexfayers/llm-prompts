# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/benchmark/\_\_init\_\_.py                                    |        1 |        0 |    100% |           |
| src/llm\_prompts/benchmark/cell/\_\_init\_\_.py                               |        0 |        0 |    100% |           |
| src/llm\_prompts/benchmark/cell/env.py                                        |       24 |        1 |     96% |        61 |
| src/llm\_prompts/benchmark/paths.py                                           |       51 |       13 |     75% |26, 36, 41, 46, 51, 56, 61, 67, 92, 99, 106-108 |
| src/llm\_prompts/benchmark/types.py                                           |      204 |        8 |     96% |71, 76, 107, 112, 115, 126, 157, 170 |
| src/llm\_prompts/claude\_models.py                                            |       23 |        0 |    100% |           |
| src/llm\_prompts/cli.py                                                       |      622 |       70 |     89% |96-97, 123-124, 131-144, 250-251, 363-364, 522, 525, 577, 644-656, 734-736, 744-747, 799-808, 1112-1114, 1117-1123, 1126-1128, 1131-1145, 1155, 1160, 1172, 1194-1198, 1306-1307, 1312 |
| src/llm\_prompts/collection\_size.py                                          |      117 |        4 |     97% |245-246, 396, 453 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      867 |       11 |     99% |153, 300, 1124, 1149, 1349, 1366-1367, 1457-1459, 1800 |
| src/llm\_prompts/exit\_reason.py                                              |        8 |        0 |    100% |           |
| src/llm\_prompts/extension\_factories.py                                      |       10 |        0 |    100% |           |
| src/llm\_prompts/github\_api.py                                               |       97 |        1 |     99% |        73 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/herdsman.py                                                  |        9 |        0 |    100% |           |
| src/llm\_prompts/home.py                                                      |       20 |        0 |    100% |           |
| src/llm\_prompts/hooks.py                                                     |      228 |       18 |     92% |81, 86, 179-180, 252-253, 280-282, 361, 369-370, 412, 427-428, 447-449 |
| src/llm\_prompts/install.py                                                   |     1881 |      155 |     92% |119, 221, 538-542, 580-582, 585, 616-619, 652, 662, 666-667, 772-773, 786, 894-896, 948, 951-953, 968, 994, 996, 1052-1053, 1199, 1208-1210, 1279, 1288, 1361-1362, 1443-1445, 1556, 1563-1564, 1646-1647, 1649, 1714, 1952-1953, 2021-2023, 2025, 2069, 2156-2158, 2410, 2514, 2573, 2809, 2834, 2936-2938, 3007, 3010, 3029, 3088-3103, 3113-3117, 3136-3143, 3181, 3318-3319, 3321-3322, 3369, 3373, 3510, 3549-3550, 3688, 3814-3827, 3832-3836, 3846-3852, 3870-3876, 3882-3891, 3899-3900, 3958-3961, 4069, 4072, 4232, 4292, 4294, 4551, 4674, 4678, 4689 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      126 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      230 |        3 |     99% |252, 395-396 |
| src/llm\_prompts/manifest.py                                                  |       72 |        3 |     96% | 50-51, 86 |
| src/llm\_prompts/mcp.py                                                       |       85 |        1 |     99% |        91 |
| src/llm\_prompts/network.py                                                   |       27 |        0 |    100% |           |
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
| src/llm\_prompts/setup.py                                                     |      355 |       44 |     88% |236-265, 307-310, 317-318, 358, 361, 382-383, 422-423, 475, 663-666, 707-710, 740-741, 744, 797-798, 810-812 |
| src/llm\_prompts/size\_guard.py                                               |      367 |       10 |     97% |246-247, 472-474, 509, 531, 535-537 |
| src/llm\_prompts/size\_limits.py                                              |       61 |        1 |     98% |       138 |
| src/llm\_prompts/size\_report.py                                              |      196 |        2 |     99% |  198, 200 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| src/llm\_prompts/telemetry.py                                                 |       79 |        2 |     97% |   140-141 |
| src/llm\_prompts/telemetry\_core.py                                           |      216 |        5 |     98% |66-67, 76-77, 398 |
| src/llm\_prompts/watch/\_\_init\_\_.py                                        |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/\_\_init\_\_.py                                   |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/core/condition.py                                      |       25 |        3 |     88% | 33, 49-50 |
| src/llm\_prompts/watch/core/registry.py                                       |       12 |        0 |    100% |           |
| src/llm\_prompts/watch/core/runner.py                                         |       37 |        1 |     97% |        29 |
| src/llm\_prompts/watch/core/source.py                                         |       21 |        0 |    100% |           |
| src/llm\_prompts/watch/sources/\_\_init\_\_.py                                |        0 |        0 |    100% |           |
| src/llm\_prompts/watch/sources/command.py                                     |       36 |        1 |     97% |        55 |
| src/llm\_prompts/watch/sources/github\_pr.py                                  |       84 |       11 |     87% |29, 44-49, 86-87, 91, 102-103, 115 |
| tests/benchmark/\_\_init\_\_.py                                               |        0 |        0 |    100% |           |
| tests/benchmark/test\_bench\_env.py                                           |       54 |        0 |    100% |           |
| tests/benchmark/test\_bench\_paths.py                                         |       13 |        0 |    100% |           |
| tests/benchmark/test\_bench\_types.py                                         |        5 |        0 |    100% |           |
| tests/conftest.py                                                             |      473 |        4 |     99% |159, 799, 905, 944 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      282 |        1 |     99% |       112 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_claude\_models.py                                                 |       25 |        0 |    100% |           |
| tests/test\_cli.py                                                            |     1005 |        1 |     99% |      1038 |
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
| tests/test\_install.py                                                        |     1345 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      603 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       62 |        4 |     94% |     20-23 |
| tests/test\_install\_codex.py                                                 |      269 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1441 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      270 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       73 |        0 |    100% |           |
| tests/test\_mcp.py                                                            |       27 |        2 |     93% |     43-44 |
| tests/test\_network.py                                                        |       26 |        0 |    100% |           |
| tests/test\_overlay\_merge.py                                                 |       19 |        0 |    100% |           |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      254 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      664 |        0 |    100% |           |
| tests/test\_removed\_agents\_notice.py                                        |       29 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      135 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      319 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |      156 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      223 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       30 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_telemetry.py                                                      |      342 |        0 |    100% |           |
| tests/test\_telemetry\_core.py                                                |      153 |        1 |     99% |       126 |
| tests/test\_todos\_script.py                                                  |       88 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      119 |        0 |    100% |           |
| tests/test\_workflows.py                                                      |       25 |        0 |    100% |           |
| tests/watch/sources/test\_github\_pr.py                                       |       64 |        0 |    100% |           |
| tests/watch/test\_watch\_cli.py                                               |       40 |        0 |    100% |           |
| **TOTAL**                                                                     | **21333** |  **551** | **97%** |           |


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