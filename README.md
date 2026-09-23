# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/cli.py                                                       |      416 |       85 |     80% |78-79, 105-118, 178-179, 276-277, 398, 401, 416, 469, 541-543, 579-581, 591-594, 607-616, 741-815, 821, 823-828, 831-832, 844-848, 910-911, 916 |
| src/llm\_prompts/collection\_size.py                                          |       51 |        3 |     94% |91, 162, 204 |
| src/llm\_prompts/contribute.py                                                |      313 |       37 |     88% |181, 280, 293-294, 298, 326, 331-333, 411, 419, 422, 447, 453, 458-461, 467-471, 500-503, 512, 516-520, 551-554 |
| src/llm\_prompts/hooks.py                                                     |      191 |       15 |     92% |64, 69, 152-153, 191-192, 310, 318-319, 361, 376-377, 402-404 |
| src/llm\_prompts/install.py                                                   |      832 |      192 |     77% |75, 89, 92, 94, 249-250, 272-273, 299-303, 335-337, 340, 357, 365-368, 397-400, 403-404, 410, 413-414, 497-498, 502, 548-550, 575, 579, 581, 634-635, 744-745, 818, 821-822, 898, 965, 972-973, 1015, 1075, 1206-1219, 1246-1266, 1275-1282, 1287-1297, 1302-1312, 1332, 1367-1374, 1379-1392, 1397-1401, 1410-1419, 1424-1433, 1438-1447, 1452-1464, 1469-1478, 1503-1505, 1595, 1598, 1668, 1680-1694, 1768-1771, 1828-1833, 1866 |
| src/llm\_prompts/manifest.py                                                  |       37 |        3 |     92% | 35-36, 61 |
| src/llm\_prompts/plugins.py                                                   |      153 |       16 |     90% |39, 126-127, 131-132, 148-160, 176, 206, 235, 282, 292, 355, 359 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        4 |     94% |56, 64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/render\_template.py                                          |      149 |       14 |     91% |113, 342-343, 352-370, 382-386, 390 |
| src/llm\_prompts/setup.py                                                     |      318 |       98 |     69% |168-197, 242, 249-250, 272-273, 278-280, 296, 299, 320-321, 340-344, 390, 392, 395-409, 422, 428-443, 454, 479-491, 518-530, 540, 551-557, 581-583, 589-592, 602-604, 615-619, 627-628, 633-634 |
| src/llm\_prompts/size\_guard.py                                               |      260 |        6 |     98% |220-221, 316, 732-734 |
| src/llm\_prompts/size\_limits.py                                              |       47 |        1 |     98% |       105 |
| tests/conftest.py                                                             |       96 |        1 |     99% |       143 |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      557 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_conftest.py                                                       |       36 |        0 |    100% |           |
| tests/test\_contribute.py                                                     |      508 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      373 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |      600 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      353 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       65 |        4 |     94% |     18-21 |
| tests/test\_install\_codex.py                                                 |      168 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |      107 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       32 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      249 |        0 |    100% |           |
| tests/test\_prompt\_sizes.py                                                  |      482 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      142 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **7585** |  **599** | **92%** |           |


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