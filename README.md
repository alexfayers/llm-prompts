# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/cli.py                                                       |      454 |       71 |     84% |82-83, 109-122, 182-183, 272-273, 401, 404, 453, 528-530, 566-568, 578-581, 600-609, 793-813, 832-834, 837-843, 846-849, 852-865, 874, 876-881, 884-885, 896-900, 972-973, 978 |
| src/llm\_prompts/collection\_size.py                                          |       67 |        3 |     96% |113, 199, 243 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      875 |       12 |     99% |149, 176, 318, 1141, 1166, 1366, 1383-1384, 1474-1476, 1817 |
| src/llm\_prompts/github\_api.py                                               |       96 |        1 |     99% |        71 |
| src/llm\_prompts/hooks.py                                                     |      163 |       15 |     91% |62, 67, 130-131, 165-166, 255, 263-264, 306, 321-322, 341-343 |
| src/llm\_prompts/install.py                                                   |      998 |      170 |     83% |83, 244-245, 267-268, 317-321, 353-355, 358, 383-386, 418, 421-422, 428, 431-432, 549-550, 563, 620-622, 651, 653, 706-707, 833-834, 907, 910-911, 983-985, 1019, 1094, 1101-1102, 1144, 1204, 1358-1360, 1362, 1392, 1502-1505, 1508-1509, 1536-1556, 1565-1572, 1577-1587, 1592-1602, 1622, 1657-1664, 1669-1682, 1687-1691, 1700-1709, 1714-1723, 1728-1737, 1742-1754, 1759-1768, 1822-1824, 1915, 1918, 2036, 2293, 2297, 2310 |
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
| src/llm\_prompts/render\_template.py                                          |      151 |       15 |     90% |115, 254, 361-362, 371-389, 401-405, 409 |
| src/llm\_prompts/setup.py                                                     |      319 |       56 |     82% |212-241, 283-286, 293-294, 334, 337, 358-359, 398-399, 548, 574-586, 596, 607-613, 643-644, 647, 676-678, 697-698, 710-712 |
| src/llm\_prompts/size\_guard.py                                               |      295 |        3 |     99% |231-232, 339 |
| src/llm\_prompts/size\_limits.py                                              |       48 |        1 |     98% |       106 |
| src/llm\_prompts/size\_report.py                                              |      127 |        4 |     97% |107, 161, 163, 165 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| tests/conftest.py                                                             |      331 |        2 |     99% |  154, 764 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      744 |        0 |    100% |           |
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
| tests/test\_prompt\_sizes.py                                                  |      505 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |       16 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      264 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       85 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      145 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **14095** |  **516** | **96%** |           |


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