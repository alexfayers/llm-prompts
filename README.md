# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/cli.py                                                       |      424 |       72 |     83% |79-80, 106-119, 179-180, 277-278, 399, 402, 417, 470, 542-544, 580-582, 592-595, 608-617, 743-764, 783-785, 788-794, 797-800, 803-816, 825, 827-832, 835-836, 848-852, 923-924, 929 |
| src/llm\_prompts/collection\_size.py                                          |       51 |        3 |     94% |92, 163, 207 |
| src/llm\_prompts/contribute.py                                                |      339 |       30 |     91% |182, 316, 371, 468, 476-477, 507, 518-521, 531-535, 570-573, 583, 587-591, 622-625 |
| src/llm\_prompts/hooks.py                                                     |      191 |       15 |     92% |64, 69, 152-153, 191-192, 310, 318-319, 361, 376-377, 402-404 |
| src/llm\_prompts/install.py                                                   |      893 |      167 |     81% |75, 236-237, 259-260, 286-290, 322-324, 327, 352-355, 387, 390-391, 397, 400-401, 507-508, 521, 568-570, 595, 599, 601, 603, 654-655, 777-778, 851, 854-855, 953, 1028, 1035-1036, 1078, 1138, 1307-1310, 1313-1314, 1341-1361, 1370-1377, 1382-1392, 1397-1407, 1427, 1462-1469, 1474-1487, 1492-1496, 1505-1514, 1519-1528, 1533-1542, 1547-1559, 1564-1573, 1623-1625, 1716, 1719, 1825, 2013-2018, 2051 |
| src/llm\_prompts/manifest.py                                                  |       54 |        3 |     94% | 37-38, 63 |
| src/llm\_prompts/plugins.py                                                   |      153 |       16 |     90% |39, 126-127, 131-132, 148-160, 176, 206, 235, 282, 292, 355, 359 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      391 |       20 |     95% |91, 140, 168, 174, 182, 196, 199-201, 205-207, 211, 352, 382, 396, 443, 581-582, 704 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        4 |     94% |56, 64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/render\_template.py                                          |      149 |       14 |     91% |113, 342-343, 352-370, 382-386, 390 |
| src/llm\_prompts/setup.py                                                     |      318 |       98 |     69% |168-197, 242, 249-250, 272-273, 278-280, 296, 299, 320-321, 340-344, 390, 392, 395-409, 422, 428-443, 454, 479-491, 518-530, 540, 551-557, 581-583, 589-592, 602-604, 615-619, 627-628, 633-634 |
| src/llm\_prompts/size\_guard.py                                               |      281 |        6 |     98% |221-222, 317, 804-806 |
| src/llm\_prompts/size\_limits.py                                              |       47 |        1 |     98% |       105 |
| tests/conftest.py                                                             |      101 |        1 |     99% |       143 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      610 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       36 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |      583 |        0 |    100% |           |
| tests/test\_focus.py                                                          |      412 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      373 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |      946 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      353 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       61 |        4 |     93% |     18-21 |
| tests/test\_install\_codex.py                                                 |      227 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |      103 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       66 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      249 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      482 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      142 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       34 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **9119** |  **574** | **94%** |           |


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