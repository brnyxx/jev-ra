<p align="center">
  <img src="../../assets/logo.svg" alt="jev-ra" width="360">
</p>

<p align="center">
  <a href="https://github.com/brnyxx/jev-ra/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/brnyxx/jev-ra/ci.yml?branch=main&label=ci"></a>
  <a href="https://pypi.org/project/jev-ra/"><img alt="PyPI" src="https://img.shields.io/pypi/v/jev-ra"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-111">
  <img alt="Chrome" src="https://img.shields.io/badge/Chrome-CDP-111">
  <a href="../../LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

[![jev-ra：面向编码智能体的浏览器操作，比 browser-use 快 3-5 倍](../../assets/hero.png)](../BENCHMARKS.md)

[English](../../README.md) · [한국어](README.ko.md) · [日本語](README.ja.md) · **简体中文**

# jev-ra

**面向 CLI 编码智能体的高速浏览器操作层。** Claude Code、Codex 或任何 MCP 客户端把目标交给
jev-ra。System One 决策模型 TypeSafe Jev 在一次往返中同时选出每一步的操作和目标元素。制定计划、
提供要输入的文本、读取页面内容、在 jev-ra 上交时接手，这些都由调用方的智能体完成。循环内不会再跑
第二个 LLM。

![jev-ra 在三秒内打开哥德尔不完备定理条目](../../assets/demo/wikipedia.gif)

| 任务 | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra | |
|---|---|---|---|
| Wikipedia：打开哥德尔不完备定理条目 | 23,058 ms | **2,714 ms** | **8.5×** |
| Google Flights ZRH→LON 单程，直到结果出现 | 66,414 ms | **8,888 ms** | **7.5×** |
| Olive Young 分类页：按 신상품순 排序 | 15,071 ms | **3,806 ms** | **4.0×** |

各跑 5 次的中位数。2026-09-18，同一台机器、同一个专用 Chrome，两边都经由 OpenRouter。每一次运行都
对照它留下的页面做了校验，25 次全部通过，文本模型调用为 0 次。
[方法、p90、成本与原始数据](../BENCHMARKS.md)。

## 快速开始

**Claude Code**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install claude
# 然后在 Claude Code 里: "open wikipedia.org and find the Gödel incompleteness article"
```

**Codex**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install codex
# 然后在 Codex 里: "use jev-ra to open wikipedia.org and find the Gödel incompleteness article"
```

**命令行**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra doctor
uvx jev-ra run https://en.wikipedia.org/wiki/Main_Page "Open the Godel incompleteness article." \
  --value "search_query=Godel incompleteness theorems"
```

不想配置 Python？`npx -y jev-ra install claude` 通过 npm 启动器做同样的事。

无论哪种方式都没有安装步骤：`uvx` 直接从 PyPI 运行，并把 `uvx jev-ra mcp` 注册为服务器命令。想要
常驻安装就用 `uv tool install jev-ra`。密钥从你已经 export 的变量中传递，绝不会被打印。

## 工作方式

```
  你的智能体                       jev-ra                              Chrome
 ──────────────              ───────────────                      ─────────────
  目标 + values  ──────────▶  observe ─────────────────────────▶  snapshot.js
                              │   元素、守卫、页面 marker        ◀──── 一次 eval
                              ▼
                              一次请求：操作？目标？
                              值？prev_ok？goal_achieved？   ──▶  Jev  (~300 ms)
                              │
                              ▼
                              新鲜度守卫 ──▶ act ──────────────▶  可信的 CDP 输入
                              │                                    (不是 JS 点击)
                              ▼
                              校验 url/title/text/字段状态
                              │
       Result  ◀──────────────┴── done · blocked · escalate · budget
```

每一步一次决策、一次往返，执行路径上没有模型。进入页面的文本只有你提供的值。

## MCP 工具

| 工具 | 参数 | 作用 |
|---|---|---|
| `browser_open` | url | 在共享会话中打开 URL 并给出页面摘要。 |
| `browser_run` | goal, values?, max_steps? | 完成整个目标。需要输入的值都放进 values。 |
| `browser_search` | query, goal?, max_pages? | 搜索，并行标签页读取最佳结果，按目标排序。 |
| `browser_act` | instruction, values? | 针对一条指令决策并执行一步。 |
| `browser_observe` | max_elements? | 列出观测到的控件和可见文本。 |
| `browser_extract` | mode? | 结构化页面数据：`text`、`elements`、`links`、`tables`、`main`。 |
| `browser_click` | ref | 按 ref 点击一个观测到的元素。 |
| `browser_type` | ref, text | 向观测到的输入框输入文本。 |
| `browser_select` | ref, option | 选择观测到的下拉项。 |
| `browser_scroll` | direction? | 上下滚动一屏。 |
| `browser_press` | key | 按下 Enter、Escape 或 Tab。 |
| `browser_wait` | - | 稍等片刻后重新观测。 |
| `browser_screenshot` | - | 当前视口的 JPEG。 |
| `browser_close` | - | 关闭服务器持有的会话。 |

每个响应都带 `elapsed_ms`；调用了 Jev 时还带 `decisions` 和 `cost`。

## 命令行

```sh
jev-ra run URL "goal" [--value name=text ...] [--max-steps N] [--json]
jev-ra search "query" ["what the page must answer"] [--max-pages 3]
jev-ra open URL | observe | extract [--mode text|elements|links|tables|main]
jev-ra act "instruction" | click REF | type REF TEXT | select REF OPTION
jev-ra scroll down|up | press Enter|Escape|Tab | wait | screenshot [PATH] | close
jev-ra mcp | install claude|codex [--scope user|project|local] | doctor | bench [--live]
```

`open` … `close` 通过 `$XDG_STATE_HOME/jev-ra/session.json` 里的 target id 在多次调用之间共享同一个
浏览器。任何命令加上 `--json` 都会输出原始负载。

## Python

```python
from jev_ra import Agent

with Agent() as agent:
    result = agent.run(
        "Place the order with express shipping.",
        values={"name": "Ada Lovelace", "email": "ada@example.com"},
        url="https://example.com/checkout",
    )
print(result.status, result.elapsed_ms, [step["target_label"] for step in result.steps])
```

## 给值，不猜值

TYPE_TEXT 需要一个字符串，而 jev-ra 不会凭空造一个。在选定字段的同一次往返里，Jev 会挑出*你给的*
值中哪一个属于该字段。如果没有合适的值，也没有配置文本助手，运行就会以 `needs_value` 停下，并给出
字段的 label、role 和当前值。你补上值再调一次即可。默认安装里没有文本模型，这正是设计的要点。

## 交还控制权时

`Result.status` 为 `done`、`blocked`、`escalate` 或 `budget` 之一。escalate 会带上 `reason`
(`needs_value`、`stuck_loop`、`unverified_done`、`stale`、`invalid_decision`、`too_many_controls`)、
按概率排序的前八个操作/目标候选，以及最多 3,000 个字符的页面文本，足够在不重新观测的情况下做判断。

校验是确定性的：每次操作后都会比较 url、title、text 和字段状态，`page_changed` 来自页面的语义
marker，而不是模型的意见。

## 基准测试

五个任务，各跑 5 次，每次运行都对照它留下的页面做了校验：

| 任务 | 中位数 | p90 | 成功 | 决策 | 成本 | 倍率 |
|---|---|---|---|---|---|---|
| Wikipedia 条目 | 2,714 ms | 3,179 ms | 5/5 | 3 | $0.00075 | 8.50× |
| Google Flights 搜索 | 8,888 ms | 10,573 ms | 5/5 | 14 | $0.00317 | 7.47× |
| Olive Young 排序 | 3,806 ms | 4,858 ms | 5/5 | 4 | $0.00204 | 3.96× |
| 带引用的搜索 | 2,416 ms | 2,571 ms | 5/5 | 4 | $0.00035 | 无基线 |
| 本地结账表单 | 2,191 ms | 2,338 ms | 5/5 | 5 | $0.00049 | 无基线 |

倍率是相对同一台机器、同一个 Chrome 上运行的 browser-use 0.13.10 + gemini-3-flash `flash_mode`
(分别为 23,058 ms、66,414 ms、15,071 ms)。25 次运行的文本模型调用总数为 0。
`jev-ra bench --live --runs 5` 可以复现这张表，并对每个有基线的任务给出 v0.1 的 3 倍门槛的
PASS/FAIL。[方法、browser-use 原始数据与复现步骤](../BENCHMARKS.md)。

左边是 jev-ra，右边是 browser-use `flash_mode`。同一任务、同一个 Chrome、实时：

![browser-use 还在打开航程类型菜单时，jev-ra 已经完成了航班搜索](../../assets/demo/flights-side-by-side.gif)

本 README 中没有任何估算数字；没有完成任务就结束的运行计为失败，而不是计入时间。

## 不做的事

Canvas、文件上传、弹出窗口、多标签页工作流、认证流程、CAPTCHA、stealth。可见控件超过 250 个的页面
会报告 `omitted`，并以 `too_many_controls` 上交，而不是去猜。跨源 iframe 会作为一个不透明元素报告；
open 的 shadow root 和同源 iframe **会**被遍历。

## 常见问题

**用 OpenRouter 还是 TypeSafe 密钥？** 都可以。jev-ra 依次查找 `JEV_RA_API_KEY`、
`TYPESAFE_API_KEY`、`OPENROUTER_API_KEY`。以 `sk-or-` 开头的密钥选择 OpenRouter 路径
(`typesafe/jev-1.13`)，其他则走直连路径(`jev-latest`)。`JEV_RA_ENDPOINT` 和 `JEV_RA_MODEL` 会
覆盖两者。OpenRouter 更容易获取；据上游测量，直连每次决策快约 140 ms。

**一个任务多少钱？** 从 **$0.00035**(一次搜索，4 次决策)到 **$0.00317**(完整的 Google Flights
流程，14 次决策)。成本与决策次数成正比，而不是页面大小，因为发送的是元素表和可见文本，不是 HTML。

**需要专用的 Chrome 吗？** 它会自己找到一个，或在专用配置文件
(`$XDG_STATE_HOME/jev-ra/chrome-profile`)中启动并复用。用 `BU_CDP_URL` 可以指向别的 Chrome。不要
指向已登录了你不愿交给智能体的账号的浏览器。

**为什么没有文本模型？** 因为调用方本身就是拥有上下文的 LLM。加第二个模型每个字段要多花
675-938 ms，而且会编造值。需要的话可以用 `JEV_RA_TEXT_MODEL` 接上。

## 配置

| 变量 | 作用 |
|---|---|
| `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | 密钥，按此优先级 |
| `JEV_RA_ENDPOINT`, `JEV_RA_MODEL` | 覆盖路径 |
| `JEV_RA_CHROME` | 要启动的浏览器可执行文件路径 |
| `BU_CDP_URL` | 连接已有的 Chrome，而不是新启动一个 |
| `JEV_RA_VIEWPORT` | 例如 `1280x900`(默认值) |
| `JEV_RA_MAX_STEPS`, `JEV_RA_MAX_DECISIONS`, `JEV_RA_TIMEOUT_S` | 预算 (40 / 80 / 120) |
| `JEV_RA_BLOCK_RESOURCES` | 设为 `0` 可关闭字体与媒体的拦截 |
| `JEV_RA_SEARCH_URL` | 搜索端点模板，`{query}` 会被替换 |
| `JEV_RA_TEXT_MODEL`, `JEV_RA_TEXT_BASE_URL`, `JEV_RA_TEXT_API_KEY` | 可选的文本助手，默认关闭 |

`$XDG_CONFIG_HOME/jev-ra/config.json` 可以写同样的键，环境变量优先。

## 致谢

`jev_ra/browser/snapshot.js` 以及 `NEXT_ACTION` / `TARGET` 指令文本改编自
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT)，那里的文本是经过
测量的。Chrome 通过 [browser-harness](https://github.com/browser-use/browser-harness)(MIT)驱动。
详见 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。

MIT 许可证。[贡献指南](../../CONTRIBUTING.md) · [安全](../../SECURITY.md) ·
[智能体指南](../../AGENTS.md) · [使用参考](../USAGE.md)

[English](../../README.md) · [한국어](README.ko.md) · [日本語](README.ja.md) · **简体中文**
