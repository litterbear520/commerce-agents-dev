# cookbooks

学习过程中的单文件脚本归档。每个主题一个目录，各自独立，不和主线包共享代码，
也不进根目录 `pytest.ini` 的 `testpaths`。测试要用 `python3 -m pytest` 跑，这样仓库根目录才在 sys.path 里。

| 目录 | 内容 | 测试 |
| --- | --- | --- |
| `stage_a/` | Stage A：从一次 LLM 请求开始，逐步加上搜索工具、购物车、来源门控、围栏、异步、选项门控（`s00`–`s05`） | `python3 -m pytest cookbooks/stage_a/tests/` |

运行脚本前在仓库根目录放好 `.env`（`ANTHROPIC_API_KEY` 等），然后 `python cookbooks/stage_a/s00_llm_request.py`。
