# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      136 |        1 |     99% |       124 |
| src/llm\_prompts/cli.py                                                       |      445 |       71 |     84% |80-81, 107-120, 180-181, 278-279, 401, 404, 457, 529-531, 567-569, 579-582, 601-610, 778-799, 818-820, 823-829, 832-835, 838-851, 860, 862-867, 870-871, 883-887, 950-951, 956 |
| src/llm\_prompts/collection\_size.py                                          |       51 |        3 |     94% |92, 163, 207 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      853 |       12 |     99% |148, 175, 317, 1081, 1106, 1299, 1316-1317, 1405-1407, 1748 |
| src/llm\_prompts/github\_api.py                                               |       95 |        1 |     99% |        71 |
| src/llm\_prompts/hooks.py                                                     |      191 |       15 |     92% |64, 69, 152-153, 191-192, 310, 318-319, 361, 376-377, 402-404 |
| src/llm\_prompts/install.py                                                   |      894 |      167 |     81% |76, 237-238, 260-261, 287-291, 323-325, 328, 353-356, 388, 391-392, 398, 401-402, 508-509, 522, 569-571, 596, 600, 602, 604, 655-656, 778-779, 852, 855-856, 954, 1029, 1036-1037, 1079, 1139, 1308-1311, 1314-1315, 1342-1362, 1371-1378, 1383-1393, 1398-1408, 1428, 1463-1470, 1475-1488, 1493-1497, 1506-1515, 1520-1529, 1534-1543, 1548-1560, 1565-1574, 1624-1626, 1717, 1720, 1826, 2014-2019, 2052 |
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
| src/llm\_prompts/setup.py                                                     |      319 |       98 |     69% |178-207, 252, 259-260, 282-283, 288-290, 306, 309, 330-331, 350-354, 400, 402, 405-419, 432, 438-453, 464, 489-501, 528-540, 550, 561-567, 591-593, 599-602, 612-614, 625-629, 637-638, 643-644 |
| src/llm\_prompts/size\_guard.py                                               |      281 |        6 |     98% |221-222, 317, 804-806 |
| src/llm\_prompts/size\_limits.py                                              |       47 |        1 |     98% |       105 |
| tests/conftest.py                                                             |      325 |        2 |     99% |  154, 751 |
| tests/test\_batching.py                                                       |      295 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      723 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       60 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |     1860 |        0 |    100% |           |
| tests/test\_focus.py                                                          |      557 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      373 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |      946 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      360 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       61 |        4 |     93% |     18-21 |
| tests/test\_install\_codex.py                                                 |      227 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |      103 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_main\_sync.py                                                     |      207 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       66 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      267 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      482 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      142 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       34 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **13046** |  **552** | **96%** |           |


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