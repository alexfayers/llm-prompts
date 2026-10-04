# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      136 |        1 |     99% |       124 |
| src/llm\_prompts/cli.py                                                       |      445 |       71 |     84% |82-83, 109-122, 182-183, 272-273, 395, 398, 451, 526-528, 564-566, 576-579, 598-607, 775-796, 815-817, 820-826, 829-832, 835-848, 857, 859-864, 867-868, 880-884, 947-948, 953 |
| src/llm\_prompts/collection\_size.py                                          |       56 |        3 |     95% |94, 170, 214 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      856 |       12 |     99% |148, 175, 317, 1092, 1117, 1310, 1327-1328, 1418-1420, 1761 |
| src/llm\_prompts/github\_api.py                                               |       96 |        1 |     99% |        71 |
| src/llm\_prompts/hooks.py                                                     |      182 |       15 |     92% |64, 69, 133-134, 182-183, 278, 286-287, 329, 344-345, 370-372 |
| src/llm\_prompts/install.py                                                   |      934 |      172 |     82% |77, 238-239, 261-262, 288-292, 324-326, 329, 354-357, 389, 392-393, 399, 402-403, 509-510, 523, 570-572, 597, 601, 603, 605, 656-657, 779-780, 853, 856-857, 955, 1030, 1037-1038, 1080, 1140, 1294-1296, 1298, 1328, 1433-1436, 1439-1440, 1467-1487, 1496-1503, 1508-1518, 1523-1533, 1553, 1588-1595, 1600-1613, 1618-1622, 1631-1640, 1645-1654, 1659-1668, 1673-1685, 1690-1699, 1749-1751, 1842, 1845, 1951, 2144-2149, 2182 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      123 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      167 |        0 |    100% |           |
| src/llm\_prompts/manifest.py                                                  |       54 |        3 |     94% | 37-38, 63 |
| src/llm\_prompts/plugins.py                                                   |      161 |       16 |     90% |41, 128-129, 133-134, 150-162, 178, 208, 237, 284, 294, 375, 379 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      473 |       14 |     97% |89, 138, 201-203, 348, 431, 505, 519, 560, 731-732, 843, 879 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        4 |     94% |56, 64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/render\_template.py                                          |      149 |       14 |     91% |113, 342-343, 352-370, 382-386, 390 |
| src/llm\_prompts/setup.py                                                     |      332 |       98 |     70% |212-241, 286, 293-294, 316-317, 322-324, 340, 343, 364-365, 384-388, 434, 436, 439-453, 466, 472-487, 498, 523-535, 562-574, 584, 595-601, 625-627, 633-636, 646-648, 659-663, 671-672, 677-678 |
| src/llm\_prompts/size\_guard.py                                               |      281 |        6 |     98% |221-222, 317, 805-807 |
| src/llm\_prompts/size\_limits.py                                              |       47 |        1 |     98% |       105 |
| tests/conftest.py                                                             |      325 |        2 |     99% |  154, 751 |
| tests/test\_batching.py                                                       |      295 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      730 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       60 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |     1869 |        0 |    100% |           |
| tests/test\_focus.py                                                          |      557 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      387 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |      946 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      506 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       61 |        4 |     93% |     18-21 |
| tests/test\_install\_codex.py                                                 |      227 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |      103 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      207 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       66 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      267 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      491 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      172 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       34 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **13314** |  **557** | **96%** |           |


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