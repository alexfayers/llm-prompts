# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/cli.py                                                       |      454 |       71 |     84% |82-83, 109-122, 182-183, 272-273, 401, 404, 453, 528-530, 566-568, 578-581, 600-609, 793-813, 832-834, 837-843, 846-849, 852-865, 874, 876-881, 884-885, 896-900, 972-973, 978 |
| src/llm\_prompts/collection\_size.py                                          |       56 |        3 |     95% |108, 188, 232 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      875 |       12 |     99% |149, 176, 318, 1141, 1166, 1366, 1383-1384, 1474-1476, 1817 |
| src/llm\_prompts/github\_api.py                                               |       96 |        1 |     99% |        71 |
| src/llm\_prompts/hooks.py                                                     |      163 |       15 |     91% |62, 67, 130-131, 165-166, 255, 263-264, 306, 321-322, 341-343 |
| src/llm\_prompts/install.py                                                   |      993 |      167 |     83% |81, 242-243, 265-266, 315-319, 351-353, 356, 381-384, 416, 419-420, 426, 429-430, 547-548, 561, 618-620, 649, 651, 704-705, 831-832, 905, 908-909, 1013, 1088, 1095-1096, 1138, 1198, 1352-1354, 1356, 1386, 1496-1499, 1502-1503, 1530-1550, 1559-1566, 1571-1581, 1586-1596, 1616, 1651-1658, 1663-1676, 1681-1685, 1694-1703, 1708-1717, 1722-1731, 1736-1748, 1753-1762, 1816-1818, 1909, 1912, 2030, 2287, 2291, 2304 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      126 |        0 |    100% |           |
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
| src/llm\_prompts/setup.py                                                     |      285 |       63 |     78% |212-241, 286, 293-294, 316-318, 334, 337, 358-359, 459-471, 498-510, 520, 531-537, 561-563, 569-572, 582-584, 595-599, 607-608, 613-614 |
| src/llm\_prompts/size\_guard.py                                               |      286 |        3 |     99% |228-229, 332 |
| src/llm\_prompts/size\_limits.py                                              |       47 |        1 |     98% |       105 |
| src/llm\_prompts/size\_report.py                                              |      127 |        4 |     97% |107, 161, 163, 165 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| tests/conftest.py                                                             |      331 |        2 |     99% |  154, 764 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      746 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       60 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |     1939 |        0 |    100% |           |
| tests/test\_focus.py                                                          |      557 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      337 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1029 |        0 |    100% |           |
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
| tests/test\_setup.py                                                          |      187 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       85 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      145 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **13934** |  **520** | **96%** |           |


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