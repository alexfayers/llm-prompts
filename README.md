# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      136 |        1 |     99% |       124 |
| src/llm\_prompts/cli.py                                                       |      455 |       71 |     84% |83-84, 110-123, 183-184, 273-274, 402, 405, 454, 529-531, 567-569, 579-582, 601-610, 794-815, 834-836, 839-845, 848-851, 854-867, 876, 878-883, 886-887, 899-903, 975-976, 981 |
| src/llm\_prompts/collection\_size.py                                          |       56 |        3 |     95% |108, 188, 232 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      861 |       12 |     99% |148, 175, 317, 1105, 1130, 1323, 1340-1341, 1431-1433, 1774 |
| src/llm\_prompts/github\_api.py                                               |       96 |        1 |     99% |        71 |
| src/llm\_prompts/hooks.py                                                     |      164 |       15 |     91% |63, 68, 131-132, 166-167, 256, 264-265, 307, 322-323, 342-344 |
| src/llm\_prompts/install.py                                                   |      977 |      167 |     83% |77, 238-239, 261-262, 288-292, 324-326, 329, 354-357, 389, 392-393, 399, 402-403, 520-521, 534, 591-593, 622, 624, 677-678, 804-805, 878, 881-882, 986, 1061, 1068-1069, 1111, 1171, 1325-1327, 1329, 1359, 1469-1472, 1475-1476, 1503-1523, 1532-1539, 1544-1554, 1559-1569, 1589, 1624-1631, 1636-1649, 1654-1658, 1667-1676, 1681-1690, 1695-1704, 1709-1721, 1726-1735, 1789-1791, 1882, 1885, 2003, 2260, 2264, 2277 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      123 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      195 |        1 |     99% |       234 |
| src/llm\_prompts/manifest.py                                                  |       54 |        3 |     94% | 37-38, 63 |
| src/llm\_prompts/plugins.py                                                   |      161 |       16 |     90% |41, 128-129, 133-134, 150-162, 178, 208, 237, 284, 294, 375, 379 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      473 |       14 |     97% |89, 138, 201-203, 348, 431, 505, 519, 560, 731-732, 843, 879 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        4 |     94% |56, 64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/render\_template.py                                          |      149 |       15 |     90% |113, 235, 342-343, 352-370, 382-386, 390 |
| src/llm\_prompts/setup.py                                                     |      331 |       98 |     70% |212-241, 286, 293-294, 316-317, 322-324, 340, 343, 364-365, 384-388, 434, 436, 439-453, 466, 472-487, 498, 523-535, 562-574, 584, 595-601, 625-627, 633-636, 646-648, 659-663, 671-672, 677-678 |
| src/llm\_prompts/size\_guard.py                                               |      287 |        3 |     99% |228-229, 332 |
| src/llm\_prompts/size\_limits.py                                              |       47 |        1 |     98% |       105 |
| src/llm\_prompts/size\_report.py                                              |      127 |        4 |     97% |107, 161, 163, 165 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| tests/conftest.py                                                             |      325 |        2 |     99% |  154, 751 |
| tests/test\_batching.py                                                       |      295 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      745 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       60 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |     1883 |        0 |    100% |           |
| tests/test\_focus.py                                                          |      557 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      337 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1014 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      520 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       61 |        4 |     93% |     18-21 |
| tests/test\_install\_codex.py                                                 |      237 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |      103 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      243 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       66 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      267 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      497 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      172 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       85 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      145 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **13836** |  **555** | **96%** |           |


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