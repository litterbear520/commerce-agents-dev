# commerce-agents-dev

基于 Claude 的商业 agent：一个商家嵌入自己应用、面向顾客的**购物 agent**。
定义一次（提示词、技能、工具契约、门控），跑在 Messages API 上。

> [!NOTE]
> 这是对照 [anthropics/commerce-agents](https://github.com/anthropics/commerce-agents)
> 按 [`BUILD_ROADMAP.md`](BUILD_ROADMAP.md) 从零重建的学习版，代码是源项目的子集。
> 这里出现的公司、品牌、商品、人物都是虚构的，唯一的公司是 ACME。
> 没有任何操作会真的下单或扣款：`checkout` 只把购物车交给调用方去完成。

## 快速开始

需要 Python 3.11+。克隆、安装：

```bash
git clone https://github.com/litterbear520/commerce-agents-dev.git && cd commerce-agents-dev
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt       # 三个包和它们锁定的依赖
```

用 [uv](https://docs.astral.sh/uv/) 的话，后两行换成：

```bash
uv venv --python 3.12 && source .venv/bin/activate   # uv 的环境没有 pip，安装一律用 uv pip
uv pip install -r requirements.txt
```

## 购物 agent

**购物 agent** 搜索、比较、规划、填购物车、回答订单和政策问题。它的流程是
[`shopping-agent/core/shopping_agent/skills/`](shopping-agent/core/shopping_agent/skills/) 里的技能；
部署方在自己的商品目录、购物车、订单和政策系统之上实现
[`StorefrontBackend`](shopping-agent/core/shopping_agent/backend.py)。

## 目录

| 目录 | 内容 | pip 包名，`import` 名 |
|---|---|---|
| [`commerce-common/`](commerce-common/) | 两个角色共用的部分：围栏、技能、数据锚定、展示、事件 | `commerce-common`，`commerce_common` |
| [`shopping-agent/core/`](shopping-agent/core/) | 购物类型、`StorefrontBackend`、提示词、工具契约、门控、执行器 | `shopping-agent-core`，`shopping_agent` |
| [`shopping-agent/runtime-messages-api/`](shopping-agent/runtime-messages-api/) | `ShoppingAgent`，Messages API 上的轮次循环 | `shopping-agent-runtime`，`shopping_agent_runtime` |
| [`cookbooks/`](cookbooks/) | Stage A 的单文件学习归档，不进默认 `pytest` | — |
| [`scripts/`](scripts/) | `install.sh` | — |

## 运行 agent

**Messages API。** 参考循环；宿主应用围绕它搭建：

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

## 安全

围栏、溯源门控、上限在工具调用内部执行；数据锚定是运行时特性。

## 验证

```bash
ruff check . && ruff format --check . && pytest
```

`requirements-dev.txt` 加上 pytest 和 ruff。CI 用它在两个 Python 版本上安装。
要确认缓存生效，读 `turn_complete` 里的 `cache_read_input_tokens`，或每次模型调用在运行时 logger 上记的那一行：
第二轮为零说明前缀变了。

## 部署到别处

运行时接受任何 `anthropic` 客户端作为 `client=`。
