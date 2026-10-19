# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/alexfayers/llm-prompts/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                          |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| src/llm\_prompts/\_\_init\_\_.py                                              |        0 |        0 |    100% |           |
| src/llm\_prompts/batching.py                                                  |      138 |        1 |     99% |       129 |
| src/llm\_prompts/cli.py                                                       |      525 |       83 |     84% |88-89, 115-116, 123-136, 237-238, 349-350, 478, 481, 530, 596-608, 632-634, 669-671, 679-682, 701-710, 905-925, 947-949, 952-958, 961-963, 966-980, 989, 991-996, 999-1000, 1011-1015, 1099-1100, 1105 |
| src/llm\_prompts/collection\_size.py                                          |      115 |        5 |     96% |178, 238-239, 389, 446 |
| src/llm\_prompts/colors.py                                                    |        6 |        0 |    100% |           |
| src/llm\_prompts/contribute.py                                                |      875 |       12 |     99% |149, 176, 318, 1141, 1166, 1366, 1383-1384, 1474-1476, 1817 |
| src/llm\_prompts/extension\_factories.py                                      |       10 |        0 |    100% |           |
| src/llm\_prompts/github\_api.py                                               |       96 |        1 |     99% |        71 |
| src/llm\_prompts/handoff\_block.py                                            |       13 |        1 |     92% |        20 |
| src/llm\_prompts/herdsman.py                                                  |        9 |        0 |    100% |           |
| src/llm\_prompts/home.py                                                      |       20 |        0 |    100% |           |
| src/llm\_prompts/hooks.py                                                     |      212 |       18 |     92% |79, 84, 152-153, 225-226, 252-254, 326, 334-335, 377, 392-393, 412-414 |
| src/llm\_prompts/install.py                                                   |     1692 |      195 |     88% |95, 279-280, 322-323, 394-398, 430-432, 435, 460-463, 495, 498-499, 505, 508-509, 626-627, 640, 745-747, 776, 778, 834-835, 951, 961-962, 1035, 1038-1039, 1113-1115, 1149, 1224, 1231-1232, 1348, 1583-1584, 1652-1654, 1656, 1699, 1781-1782, 1786-1788, 1939-1940, 2044, 2150, 2380, 2404, 2509-2511, 2580, 2583, 2602, 2643-2646, 2649-2650, 2677-2697, 2706-2713, 2718-2728, 2733-2743, 2777, 2907-2908, 2910-2911, 2956, 2960, 3053, 3086-3087, 3224, 3285-3286, 3292-3305, 3310-3314, 3323-3332, 3337-3346, 3351-3360, 3365-3377, 3382-3391, 3446-3447, 3548, 3551, 3683, 3761, 3763, 4075, 4079, 4090 |
| src/llm\_prompts/links.py                                                     |      132 |        0 |    100% |           |
| src/llm\_prompts/listing.py                                                   |      126 |        0 |    100% |           |
| src/llm\_prompts/main\_sync.py                                                |      195 |        1 |     99% |       234 |
| src/llm\_prompts/manifest.py                                                  |       72 |        3 |     96% | 50-51, 86 |
| src/llm\_prompts/plugins.py                                                   |      163 |       16 |     90% |45, 132-133, 137-138, 154-166, 182, 212, 241, 288, 298, 379, 383 |
| src/llm\_prompts/prompts/claude-code/skills/retrospective/extract\_signals.py |      181 |       97 |     46% |44-49, 54-69, 80-124, 186, 197, 200, 209, 254-264, 269-286, 297-332, 336 |
| src/llm\_prompts/prompts/shared/skills/eagle-vision/focus.py                  |      689 |       10 |     99% |108, 159, 271, 676, 690, 1214-1217, 1311 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/inspect\_range.py             |       57 |        3 |     95% |59-60, 106 |
| src/llm\_prompts/prompts/shared/skills/git-tidy/rewrite\_range.py             |       64 |        4 |     94% |56, 64, 67, 168 |
| src/llm\_prompts/prompts/shared/skills/git-usage/check\_repos.py              |       67 |       12 |     82% |41-42, 44, 63, 73-75, 95-96, 124-125, 159 |
| src/llm\_prompts/prompts/shared/skills/tidy-code/check\_reduction.py          |       42 |        1 |     98% |        97 |
| src/llm\_prompts/prompts/shared/skills/todos/find\_todos.py                   |       44 |        7 |     84% |96-98, 103-105, 109 |
| src/llm\_prompts/render\_template.py                                          |      182 |       15 |     92% |149, 318, 454-455, 464-482, 494-498, 502 |
| src/llm\_prompts/setup.py                                                     |      321 |       56 |     83% |229-258, 300-303, 310-311, 351, 354, 375-376, 415-416, 565, 591-603, 613, 624-630, 660-661, 664, 693-695, 714-715, 727-729 |
| src/llm\_prompts/size\_guard.py                                               |      351 |       11 |     97% |242-243, 350, 421-423, 458, 480, 484-486 |
| src/llm\_prompts/size\_limits.py                                              |       61 |        1 |     98% |       138 |
| src/llm\_prompts/size\_report.py                                              |      172 |        3 |     98% |134, 188, 190 |
| src/llm\_prompts/skill\_injection.py                                          |       37 |        2 |     95% |    33, 36 |
| src/llm\_prompts/squash\_subject.py                                           |        6 |        0 |    100% |           |
| tests/conftest.py                                                             |      343 |        2 |     99% |  155, 788 |
| tests/test\_batching.py                                                       |      314 |        0 |    100% |           |
| tests/test\_build\_wave.py                                                    |      179 |        0 |    100% |           |
| tests/test\_cd.py                                                             |       38 |        0 |    100% |           |
| tests/test\_check\_reduction\_script.py                                       |       61 |        0 |    100% |           |
| tests/test\_check\_repos\_script.py                                           |       67 |        0 |    100% |           |
| tests/test\_cli.py                                                            |      819 |        0 |    100% |           |
| tests/test\_cli\_uninstall.py                                                 |       15 |        0 |    100% |           |
| tests/test\_codemode\_error\_header.py                                        |       54 |        1 |     98% |        28 |
| tests/test\_conftest.py                                                       |       60 |        0 |    100% |           |
| tests/test\_context\_total.py                                                 |      183 |        1 |     99% |        29 |
| tests/test\_contribute.py                                                     |     1872 |        0 |    100% |           |
| tests/test\_diff\_preview.py                                                  |      190 |        1 |     99% |        78 |
| tests/test\_extension\_factories.py                                           |       21 |        0 |    100% |           |
| tests/test\_focus.py                                                          |     1043 |        0 |    100% |           |
| tests/test\_github\_api.py                                                    |      123 |        0 |    100% |           |
| tests/test\_handoff\_block.py                                                 |       14 |        0 |    100% |           |
| tests/test\_herdr\_permission\_blocked.py                                     |       11 |        0 |    100% |           |
| tests/test\_hide\_tools.py                                                    |       20 |        0 |    100% |           |
| tests/test\_hooks.py                                                          |      395 |        0 |    100% |           |
| tests/test\_inspect\_range\_script.py                                         |       89 |        0 |    100% |           |
| tests/test\_install.py                                                        |     1110 |        0 |    100% |           |
| tests/test\_install\_agents.py                                                |      583 |        0 |    100% |           |
| tests/test\_install\_antigravity.py                                           |       60 |        4 |     93% |     18-21 |
| tests/test\_install\_codex.py                                                 |      234 |        0 |    100% |           |
| tests/test\_install\_pi.py                                                    |     1211 |        0 |    100% |           |
| tests/test\_links.py                                                          |      160 |        0 |    100% |           |
| tests/test\_listing.py                                                        |       48 |        0 |    100% |           |
| tests/test\_lsp\_defaults.py                                                  |       65 |        1 |     98% |        29 |
| tests/test\_main\_sync.py                                                     |      243 |        0 |    100% |           |
| tests/test\_manifest.py                                                       |       73 |        0 |    100% |           |
| tests/test\_pane\_reaper.py                                                   |      460 |        1 |     99% |        71 |
| tests/test\_permission\_box.py                                                |      161 |        1 |     99% |        86 |
| tests/test\_pi\_extension\_factories.py                                       |        8 |        0 |    100% |           |
| tests/test\_plugins.py                                                        |      254 |        0 |    100% |           |
| tests/test\_popup\_defer.py                                                   |      127 |        1 |     99% |        31 |
| tests/test\_prompt\_cache\_stabilizer.py                                      |       94 |        2 |     98% |    29, 85 |
| tests/test\_prompt\_sizes.py                                                  |      638 |        0 |    100% |           |
| tests/test\_render\_template.py                                               |      135 |        0 |    100% |           |
| tests/test\_retrospective\_extract.py                                         |       90 |        0 |    100% |           |
| tests/test\_rewrite\_range\_script.py                                         |       68 |        0 |    100% |           |
| tests/test\_role\_switch.py                                                   |       58 |        0 |    100% |           |
| tests/test\_setup.py                                                          |      266 |        0 |    100% |           |
| tests/test\_size\_guard.py                                                    |       93 |        0 |    100% |           |
| tests/test\_size\_report.py                                                   |      190 |        0 |    100% |           |
| tests/test\_skill\_injection.py                                               |       30 |        0 |    100% |           |
| tests/test\_squash\_subject.py                                                |        7 |        0 |    100% |           |
| tests/test\_todos\_script.py                                                  |       87 |        0 |    100% |           |
| tests/test\_tower\_do\_patch.py                                               |       78 |        1 |     99% |        28 |
| tests/test\_uninstall.py                                                      |      114 |        0 |    100% |           |
| **TOTAL**                                                                     | **19329** |  **574** | **97%** |           |


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