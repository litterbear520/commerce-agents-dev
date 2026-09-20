# commerce-agents-dev

对照 [anthropics/commerce-agents](https://github.com/anthropics/commerce-agents) 从零逐步重建的学习项目：
一个嵌入商家应用、面向顾客的**购物 agent**，定义一次（提示词、技能、工具契约、门控），
跑在 Messages API 上。代码是源项目的子集，按 [`BUILD_ROADMAP.md`](BUILD_ROADMAP.md) 的步骤只增不改，
模块名、函数名、变量名与源项目一致。

> [!NOTE]
> 这里出现的公司、品牌、商品、人物都是虚构的，唯一的公司是 ACME。
> 没有任何操作会真的下单或扣款：`checkout` 只把购物车交给调用方去完成。

## 快速开始：安装

需要 Python 3.11+。克隆、建虚拟环境、安装：

```bash
git clone https://github.com/litterbear520/commerce-agents-dev.git && cd commerce-agents-dev
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # 三个包（可编辑安装）+ 运行时依赖 + pytest 和 ruff
```

`scripts/install.sh dev` 跑的就是最后一行；不带参数时只装 `requirements.txt`（不含 pytest 和 ruff）。
没有激活虚拟环境时脚本会给出警告。

装了 [uv](https://docs.astral.sh/uv/) 的话，后两行换成它的等价命令，锁定文件不变：

```bash
uv venv --python 3.12 && source .venv/bin/activate   # 没有 3.12 时 uv 会自动下载
uv pip install -r requirements-dev.txt
```

uv 建的环境里没有 pip，安装一律走 `uv pip`，不要跑 `scripts/install.sh`。测试不需要 API key；
[`.env.example`](.env.example) 列出的是后续原型（路线图 Step 15.5）要读的变量。

装完验证：

```bash
ruff check . && ruff format --check . && pytest
```

## 目录

| 目录 | 内容 | pip 包名，`import` 名 |
|---|---|---|
| [`commerce-common/`](commerce-common/) | 两个角色共用的部分：围栏、技能、数据锚定、展示、流式事件、轮次循环零件、缓存断点 | `commerce-common`，`commerce_common` |
| [`shopping-agent/core/`](shopping-agent/core/) | 购物类型、`StorefrontBackend`、提示词、工具契约、门控、执行器 | `shopping-agent-core`，`shopping_agent` |
| [`shopping-agent/runtime-messages-api/`](shopping-agent/runtime-messages-api/) | `ShoppingAgent`，Messages API 上的轮次循环 | `shopping-agent-runtime`，`shopping_agent_runtime` |
| [`shopping-agent/core/shopping_agent/skills/`](shopping-agent/core/shopping_agent/skills/) | 购物 agent 的流程，每个一份 `SKILL.md` | — |
| [`cookbooks/`](cookbooks/) | Stage A 的单文件学习归档，不和主线共享代码，不在默认 `pytest` 里 | — |
| [`scripts/`](scripts/) | `install.sh` | — |

每个包都有自己的 `tests/`，`pytest.ini` 的 `testpaths` 列出了它们。

## 运行 agent

Messages API 上的参考循环；调用方是围绕它的宿主应用：

```python
from pathlib import Path

from shopping_agent import ShoppingAgentConfig
from shopping_agent_runtime import ShoppingAgent

agent = ShoppingAgent(
    backend=your_backend,
    skills_dir=Path("shopping-agent/core/shopping_agent/skills"),
    config=ShoppingAgentConfig(brand_name="你的店"),
)
async for event in agent.stream_turn(messages, session, state):
    ...  # text_delta, tool_call, ui, cart_update, turn_complete
```

## 验证

```bash
ruff check . && ruff format --check . && pytest
```

`requirements-dev.txt` 在 `requirements.txt` 之上加 pytest 和 ruff；CI 用它在两个 Python 版本上安装并跑同一条命令。
