# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/cli.py                                                       |      479 |       71 |     85% |85-86, 110-123, 217-218, 307-308, 436, 439, 488, 563-565, 601-603, 613-616, 635-644, 828-848, 867-869, 872-878, 881-884, 887-900, 909, 911-916, 919-920, 931-935, 1017-1018, 1023 |
| src/llm\_prompts/collection\_size.py                                          |      115 |        5 |     96% |178, 238-239, 389, 446 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      875 |       12 |     99% |149, 176, 318, 1141, 1166, 1366, 1383-1384, 1474-1476, 1817 |
| src/llm\_prompts/extension\_factories.py                                      |        7 |        0 |    100% |           |
| src/llm\_prompts/github\_api.py                                               |       96 |        1 |     99% |        71 |
| src/llm\_prompts/herdsman.py                                                  |        8 |        0 |    100% |           |
| src/llm\_prompts/hooks.py                                                     |      163 |       15 |     91% |62, 67, 130-131, 165-166, 255, 263-264, 306, 321-322, 341-343 |
| src/llm\_prompts/install.py                                                   |     1493 |      191 |     87% |89, 268-269, 311-312, 383-387, 419-421, 424, 449-452, 484, 487-488, 494, 497-498, 615-616, 629, 734-736, 765, 767, 823-824, 940, 950-951, 1024, 1027-1028, 1102-1104, 1138, 1213, 1220-1221, 1332, 1517-1519, 1521, 1564, 1646-1647, 1651-1653, 1804-1805, 1911, 2063, 2087, 2181-2183, 2249, 2252, 2271, 2312-2315, 2318-2319, 2346-2366, 2375-2382, 2387-2397, 2402-2412, 2446, 2578, 2721, 2780-2787, 2792-2805, 2810-2814, 2823-2832, 2837-2846, 2851-2860, 2865-2877, 2882-2891, 2945-2947, 3048, 3051, 3174, 3252, 3254, 3416, 3532, 3536, 3547 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      126 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      195 |        1 |     99% |       234 |
| src/llm\_prompts/manifest.py                                                  |       63 |        3 |     95% | 40-41, 72 |
| src/llm\_prompts/plugins.py                                                   |      161 |       16 |     90% |41, 128-129, 133-134, 150-162, 178, 208, 237, 284, 294, 375, 379 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      689 |       10 |     99% |108, 159, 271, 676, 690, 1214-1217, 1311 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        4 |     94% |56, 64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/render\_template.py                                          |      182 |       15 |     92% |149, 318, 454-455, 464-482, 494-498, 502 |
| src/llm\_prompts/setup.py                                                     |      319 |       56 |     82% |212-241, 283-286, 293-294, 334, 337, 358-359, 398-399, 548, 574-586, 596, 607-613, 643-644, 647, 676-678, 697-698, 710-712 |
| src/llm\_prompts/size\_guard.py                                               |      351 |       11 |     97% |242-243, 350, 421-423, 458, 480, 484-486 |
| src/llm\_prompts/size\_limits.py                                              |       61 |        1 |     98% |       138 |
| src/llm\_prompts/size\_report.py                                              |      172 |        3 |     98% |134, 188, 190 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| tests/conftest.py                                                             |      347 |        2 |     99% |  155, 798 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      179 |        0 |    100% |           |
| tests/test\_cd.py                                                             |       38 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      790 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_codemode\_error\_header.py                                        |       45 |        1 |     98% |        28 |
| tests/test\_conftest.py                                                       |       60 |        0 |    100% |           |
| tests/test\_context\_total.py                                                 |      183 |        1 |     99% |        29 |
| tests/test\_contribute.py                                                     |     1872 |        0 |    100% |           |
| tests/test\_diff\_preview.py                                                  |      190 |        1 |     99% |        78 |
| tests/test\_extension\_factories.py                                           |       15 |        0 |    100% |           |
| tests/test\_focus.py                                                          |     1043 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      337 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1108 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      575 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       61 |        4 |     93% |     18-21 |
| tests/test\_install\_codex.py                                                 |      237 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |      997 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_lsp\_defaults.py                                                  |       65 |        1 |     98% |        29 |
| tests/test\_main\_sync.py                                                     |      243 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       73 |        0 |    100% |           |
| tests/test\_pane\_reaper.py                                                   |      460 |        1 |     99% |        71 |
| tests/test\_permission\_box.py                                                |      161 |        1 |     99% |        86 |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_pi\_help\_coverage.py                                             |       20 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      267 |        0 |    100% |           |
| tests/test\_popup\_defer.py                                                   |      127 |        1 |     99% |        31 |
| tests/test\_prompt\_cache\_stabilizer.py                                      |       94 |        2 |     98% |    29, 85 |
| tests/test\_prompt\_sizes.py                                                  |      638 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      126 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      269 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       93 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      190 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_tower\_do\_patch.py                                               |       78 |        1 |     99% |        28 |
| tests/test\_uninstall.py                                                      |      118 |        0 |    100% |           |
| **TOTAL**                                                                     | **18528** |  **552** | **97%** |           |


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