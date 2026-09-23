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

[![jev-ra：面向编码智能体的浏览器操作，比 browser-use 快 4-8.5×](../../assets/hero.png)](../BENCHMARKS.md)

[English](../../README.md) · [한국어](README.ko.md) · [日本語](README.ja.md) · **简体中文**

**网站:** [brnyxx.github.io/jev-ra](https://brnyxx.github.io/jev-ra/?lang=zh-CN) 回放一次真实记录的运行并说明流水线。

# jev-ra

**面向 CLI 编码智能体的高速浏览器操作层。** Claude Code、Codex 或任何 MCP 客户端把目标交给
jev-ra。System One 决策模型 TypeSafe Jev 在一次往返中同时选出每一步的操作和目标元素。制定计划、
提供要输入的文本、读取页面内容、在 jev-ra 上交时接手，这些都由调用方的智能体完成。循环内不会再跑
第二个 LLM。

![jev-ra 打开哥德尔不完备定理条目,录像里的计时停在 3.79 s](../../assets/demo/wikipedia.gif)

| 任务 | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra | |
|---|---|---|---|
| Wikipedia：打开哥德尔不完备定理条目 | 23,058 ms | **2,714 ms** | **8.50×** |
| Google Flights ZRH→LON 单程，直到结果出现 | 66,414 ms | **8,888 ms** | **7.47×** |
| Olive Young 分类页：按 신상품순 排序 | 15,071 ms | **3,806 ms** | **3.96×** |

2026-09-18 在同一台机器、同一个专用 Chrome 上测得，两款工具都经由 OpenRouter。jev-ra 是 5 次运行的
中位数，browser-use 是它记录下的单次运行，而这次单次运行在每个任务上都比 browser-use 自己的 5 次中位数
更快。jev-ra 的每一次运行都对照它留下的页面做了校验，25 次全部通过，文本模型调用为 0 次。
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

不想配置 Python？`npx -y jev-ra install claude` 可通过 npm 启动器做同样的事。npm 包只是一个
启动器：它查找 `uv`，缺失时提议安装，然后运行与自身版本一致的 PyPI 包。

无论哪种方式都没有安装步骤：`uvx` 直接从 PyPI 运行，并把 `uvx jev-ra mcp` 注册为服务器命令。想要
常驻安装就用 `uv tool install jev-ra`。密钥从你已经 export 的变量中传递，绝不会被打印。

## 工作方式

![单步流程:观察、决策、执行、验证、结束或返回,以及与 browser-use 相比的每步耗时](https://raw.githubusercontent.com/brnyxx/jev-ra/main/assets/readme-step.svg)

![架构:你的代理通过 MCP 与 jev-ra 通信;jev-ra 通过 DevTools Protocol 驱动 Chrome,每步向 TypeSafe Jev 询问一次](https://raw.githubusercontent.com/brnyxx/jev-ra/main/assets/readme-architecture.svg)

每一步一次决策。输入到页面的文本只有你提供的值。

## MCP 工具

| 工具 | 参数 | 作用 |
|---|---|---|
| `browser_open` | url | 在共享会话中打开 URL 并给出页面摘要。 |
| `browser_run` | goal, values?, max_steps?, resume? | 完成整个目标。需要输入的值都放进 values。`resume` 接着执行以 `needs_human` 停下的运行。 |
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

| 命令 | 作用 |
|---|---|
| `run URL "goal" [--value name=text ...] [--max-steps N]`, `run --resume RUN_ID` | 从 URL 开始完成目标，直到完成或升级 |
| `search "query" ["what the page must answer"] [--max-pages 3]` | 搜索网络并读取最佳结果 |
| `open URL` | 打开 URL 并为后续命令保留会话 |
| `observe` | 列出打开页面的控件和文本 |
| `extract [--mode text\|elements\|links\|tables\|main]` | 从打开的页面中提取结构化数据 |
| `act "instruction" [--value name=text ...]` | 在打开的页面上执行一步决策 |
| `click REF` | 点击一个观测到的元素 |
| `type REF TEXT` | 向一个观测到的字段输入文本 |
| `select REF OPTION` | 选择一个观测到的下拉项 |
| `scroll down\|up` | 滚动打开的页面 |
| `press Enter\|Escape\|Tab` | 按下 Enter、Escape 或 Tab |
| `wait` | 稍等片刻后重新观测 |
| `screenshot [PATH]` | 将视口保存为 JPEG |
| `close` | 关闭 `open` 保留的会话 |
| `mcp` | 运行 MCP stdio 服务器 |
| `skill` | 打印智能体指南，可保存为技能文件 |
| `install claude\|codex [--scope user\|project\|local]` | 将 jev-ra 注册为编码智能体的 MCP 服务器 |
| `doctor` | 检查密钥、端点、Chrome 和一次实时决策 |
| `bench [--live]` | 为离线测试页计时，加 `--live` 也为实时任务计时 |
| `corpus run` | 运行真实网站语料 |

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

## 值

TYPE_TEXT 需要一个字符串，而 jev-ra 不会凭空造一个。在选定字段的同一次往返里，Jev 会挑出*你给的*
值中哪一个属于该字段。如果没有合适的值，也没有配置文本助手，运行就会以 `needs_value` 停下，并给出
字段的 label、role 和当前值。你补上值再调一次即可。默认安装里没有文本模型。

## 交还控制权时

`Result.status` 为 `done`、`blocked`、`escalate` 或 `budget` 之一。运行中途停下时，`reason` 是
`needs_value`、`stuck_loop`、`unverified_done`、`stale`、`invalid_decision`、`too_many_controls`、
`provider_error`、`blocked`、`blocked_by_site` 或 `needs_human` 之一。以 `budget` 结束的运行会把被耗尽的预算（步数、决策数、时间）
放进 `reason`；`provider_error` 是提供方根本拒绝作答，应检查密钥与路径，而不是重试目标。
escalate 还会带上按概率排序的前八个
操作/目标候选，以及最多 3,000 个字符的页面文本，足够在不重新观测的情况下做判断。

校验是确定性的：每次操作后都会比较 url、title、text 和字段状态，`page_changed` 来自页面的语义
marker，而不是来自模型。

以错误页应答的站点(HTTP 5xx、429，或自称出错的短页面)，在做出任何决定之前先等待 2 秒并重新加载一次；
若仍是错误，运行以 `blocked_by_site` 停止，并在 `detail.wall` 中写明状态(`"http 502"`)。站点短暂的故障
不会被当作可以操作的页面。

## 基准测试

五个任务，各跑 5 次，每次运行都对照它留下的页面做了校验。2026-09-18 经由 OpenRouter，在与
browser-use 记录相同的机器和 Chrome 上测得：

| 任务 | 中位数 | p90 | 成功 | 决策 | 成本 | 倍率 |
|---|---|---|---|---|---|---|
| Wikipedia 条目 | 2,714 ms | 3,179 ms | 5/5 | 3 | $0.00075 | 8.50× |
| Google Flights 搜索 | 8,888 ms | 10,573 ms | 5/5 | 14 | $0.00317 | 7.47× |
| Olive Young 排序 | 3,806 ms | 4,858 ms | 5/5 | 4 | $0.00204 | 3.96× |
| 带引用的搜索 | 2,416 ms | 2,571 ms | 5/5 | 4 | $0.00035 | 无基线 |
| 本地结账表单 | 2,191 ms | 2,338 ms | 5/5 | 5 | $0.00049 | 无基线 |

倍率相对的是 browser-use 0.13.10 + gemini-3-flash `flash_mode` 在同一天、同一台机器、同一个
Chrome 上同样经由 OpenRouter 记录的每个任务的单次运行(分别为 23,058 ms、66,414 ms、15,071 ms)。
25 次运行的文本模型调用总数为 0。同一天用同一套测试框架让 browser-use 每个任务重跑 5 次，结果更慢：
9.07×、8.31×、7.26×。用我们的中位数对比 browser-use 每个任务六次运行中最快的一次(15,759 ms、
49,914 ms、15,071 ms),得到 5.8×、5.6×、3.96×;当天测得的倍率没有一个低于 3.96×。
`jev-ra bench --live --runs 5` 可以复现这张表，并对每个有基线的任务给出 v0.1 的 3× 门槛的
PASS/FAIL。0.2.5 经 TypeSafe 直连路径(2026-09-23)时，前三个任务分别用了 4,681 ms、11,603 ms、
5,675 ms;那天没有重跑 browser-use,所以这些时间不构成同等条件下的倍率。
[方法、browser-use 原始数据与复现步骤](../BENCHMARKS.md)。

左边是 jev-ra，右边是 browser-use `flash_mode`。同一任务、同一个 Chrome、实时：

![browser-use 还在打开航程类型菜单时，jev-ra 已经完成了航班搜索](../../assets/demo/flights-side-by-side.gif)

没有完成任务就结束的运行计为失败，而不是计入时间。

### 真实站点上的准确率

语料库是十个类别(搜索、电商、预订、表单、文档、新闻、门户、登录墙、日文与中文站点)中的 83 个真实站点任务，
每个任务都有检查运行结束页面的规格。0.2.4 于 2026-09-23 经 TypeSafe 直连路径每个任务 3 次：
**213 / 249 = 85.5 %**。在两款工具都拿到的 40 个任务上，browser-use 0.13.10 `flash_mode` 于
2026-09-22 各跑 1 次，通过 **29 / 40 = 72 %**，通过的运行中位数 **19.4 s**；jev-ra 0.1 于
2026-09-18 各跑 3 次，通过 **102 / 120 = 85 %**，中位数 **3.1 s**。这两行的日期、运行次数和
jev-ra 版本都不同，不是同等条件下的比较。一轮 3 次的测量仅因站点状况就会浮动约 5 个任务，
因此只有逐任务重跑结果一致时，变更才算得失。[逐任务数据与波动测量](https://github.com/brnyxx/jev-ra/blob/main/docs/BENCHMARKS.md)。

## 不做的事

| 限制 | 会发生什么 |
|---|---|
| 画布绘图、游戏等绘制而非标记的内容 | `blocked`：没有任何观测到的控件能推进目标 |
| 文件上传 | `blocked`：文件输入既不提供，也不输入 |
| CAPTCHA、机器人墙、隐身 | 返回 `blocked` 并附上页面文本，由你判断 |
| 认证流程 | 返回 `needs_value` 并指明字段；jev-ra 从不猜测凭据 |
| 弹出窗口、多标签页工作流 | 运行始终停留在自己的目标上 |
| 跨源 iframe | 报告为一个不透明元素；开放的 shadow root 与同源 iframe **会**被遍历 |
| 可见控件超过 250 个 | 报告 `omitted`，卡住的运行升级为 `too_many_controls` 而不是猜测 |

以上每一种都会返回带页面文本和候选排名的上报。
## 常见问题

**用 OpenRouter 还是 TypeSafe 密钥？** 都可以。jev-ra 依次查找 `JEV_RA_API_KEY`、
`TYPESAFE_API_KEY`、`OPENROUTER_API_KEY`。以 `sk-or-` 开头的密钥选择 OpenRouter 路径
(`typesafe/jev-1.13`)，其他则走直连路径(`jev-latest`)。`JEV_RA_ENDPOINT` 和 `JEV_RA_MODEL` 会
覆盖两者。OpenRouter 更容易获取。哪条路径决策更快，还没有在同等条件下测过：
[上游 jev-ultrafast 的记录](https://github.com/browser-use/jev-ultrafast/blob/main/docs/performance.md)
在直连路径上的决策中位数为 178 ms,jev-ra 记录的 Flights 运行经由 OpenRouter 的中位数为 296 ms
(2026-09-18),机器和日期都不同。

**一个任务多少钱？** 2026-09-18 经由 OpenRouter,从 **$0.00035**(一次搜索，4 次决策)到
**$0.00317**(完整的 Google Flights 流程，14 次决策)。成本与决策次数成正比，而不是页面大小，
因为发送的是元素表和可见文本，不是 HTML。

**需要专用的 Chrome 吗？** 它会自己找到一个，或在专用配置文件
(`$XDG_STATE_HOME/jev-ra/chrome-profile`)中启动并复用。用 `BU_CDP_URL` 可以指向别的 Chrome。不要
指向已登录了你不愿交给智能体的账号的浏览器。

**为什么没有文本模型？** 调用方代理已经拥有上下文。加第二个模型，每个字段要多一次调用(设计时于
2026-09-18 经由 OpenRouter 测了五次 mercury-2.5 调用，为 675-938 ms,见
[设计文档](https://github.com/brnyxx/jev-ra/blob/main/docs/DESIGN.md)),而且会写入没有人提供的值。
需要的话可以用 `JEV_RA_TEXT_MODEL` 接上。

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
| `JEV_RA_PROXY` | jev-ra 启动的 Chrome 的出口代理，例如 `http://host:8080` |
| `JEV_RA_PACE_S` | 一次运行对同一主机发起的两次导航之间的最短秒数；默认 `1`，`0` 为关闭，本机不受限 |
| `JEV_RA_NOTIFY` | `0` 关闭人工验证触发的桌面通知 |
| `JEV_RA_HUMAN_WAIT_S` | 等待人完成人工验证的时长；默认 `120`，`0` 为立即交还 |
| `JEV_RA_ALLOW_FILE_URLS` | 设为 `1` 可让会话打开 `file:` URL |
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

[变更记录](../../CHANGELOG.md) · [发布](https://github.com/brnyxx/jev-ra/releases)
