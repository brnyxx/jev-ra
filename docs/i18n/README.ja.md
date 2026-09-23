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

[![jev-ra: コーディングエージェントのためのブラウザ操作、browser-use より 4-8.5× 速い](../../assets/hero.png)](../BENCHMARKS.md)

[English](../../README.md) · [한국어](README.ko.md) · **日本語** · [简体中文](README.zh-CN.md)

**サイト:** [brnyxx.github.io/jev-ra](https://brnyxx.github.io/jev-ra/?lang=ja) で実際に記録した実行を再生し、パイプラインを説明している。

# jev-ra

**CLI コーディングエージェントのための高速なブラウザ操作レイヤー。** Claude Code、Codex、あるいは
任意の MCP クライアントが jev-ra にゴールを渡す。System One 判断モデルである TypeSafe Jev が、
1 往復で各ステップの操作と対象要素を同時に選ぶ。計画を立て、入力すべき文字列を渡し、ページの内容を
読み、jev-ra がエスカレートしたら引き継ぐ。それは呼び出し側のエージェントの仕事だ。ループの中で
2 つ目の LLM が動くことはない。

![ゲーデルの不完全性定理の記事を開く jev-ra。録画の時計は 3.79 s で止まる](../../assets/demo/wikipedia.gif)

| タスク | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra | |
|---|---|---|---|
| Wikipedia: ゲーデルの不完全性定理の記事を開く | 23,058 ms | **2,714 ms** | **8.50×** |
| Google Flights ZRH→LON 片道、結果が表示されるまで | 66,414 ms | **8,888 ms** | **7.47×** |
| Olive Young カテゴリ: 신상품순 で並べ替え | 15,071 ms | **3,806 ms** | **3.96×** |

2026-09-18 に 1 台のマシン、1 つの専用 Chrome で計測し、両ツールとも OpenRouter 経由。jev-ra は
5 回実行の中央値、browser-use は記録された単発の実行で、その単発はどのタスクでも browser-use 自身の
5 回中央値より速かった。jev-ra の各実行は最終ページに対して検証し、25 回中 25 回が成功、テキスト
モデルの呼び出しは 0 回だった。[測定方法、p90、コスト、生データ](../BENCHMARKS.md)。

## クイックスタート

**Claude Code**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install claude
# その後 Claude Code で: "open wikipedia.org and find the Gödel incompleteness article"
```

**Codex**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install codex
# その後 Codex で: "use jev-ra to open wikipedia.org and find the Gödel incompleteness article"
```

**シェル**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra doctor
uvx jev-ra run https://en.wikipedia.org/wiki/Main_Page "Open the Godel incompleteness article." \
  --value "search_query=Godel incompleteness theorems"
```

Python を用意したくない場合は、`npx -y jev-ra install claude` でも npm ランチャー経由で同じことが
できる。npm パッケージはランチャーにすぎない。`uv` を探し、なければインストールを提案し、自分の
バージョンに固定した PyPI パッケージを実行する。

どちらにせよインストール手順はない。`uvx` が PyPI から直接実行し、サーバーコマンドとして
`uvx jev-ra mcp` を登録する。恒久的に入れるなら `uv tool install jev-ra`。鍵はすでに export して
ある変数から渡され、出力されることはない。

## 仕組み

![1 ステップの流れ: 観察、判断、実行、検証、終了または返却、そして browser-use と比べたステップあたりの時間](https://raw.githubusercontent.com/brnyxx/jev-ra/main/assets/readme-step.svg)

![アーキテクチャ: エージェントは MCP で jev-ra と話し、jev-ra は DevTools Protocol で Chrome を動かし、ステップごとに一度 TypeSafe Jev に問う](https://raw.githubusercontent.com/brnyxx/jev-ra/main/assets/readme-architecture.svg)

ステップごとに判断 1 回。ページに入力される文字列はあなたが渡した値
だけだ。

## MCP ツール

| ツール | 引数 | 何をするか |
|---|---|---|
| `browser_open` | url | 共有セッションで URL を開き、ページを要約する。 |
| `browser_run` | goal, values?, max_steps?, resume? | ゴール全体を遂行する。入力が必要な値は values で渡す。`resume` は `needs_human` で止まった実行を続ける。 |
| `browser_search` | query, goal?, max_pages? | 検索し、上位の結果を並列タブで読み、ゴールに対して順位づけする。 |
| `browser_act` | instruction, values? | 指示に沿った 1 ステップを判断して実行する。 |
| `browser_observe` | max_elements? | 観測されたコントロールと可視テキストを列挙する。 |
| `browser_extract` | mode? | 構造化されたページデータ: `text`、`elements`、`links`、`tables`、`main`。 |
| `browser_click` | ref | 観測済み要素を ref でクリックする。 |
| `browser_type` | ref, text | 観測済みフィールドに入力する。 |
| `browser_select` | ref, option | 観測済みドロップダウンの選択肢を選ぶ。 |
| `browser_scroll` | direction? | 1 画面分だけ上下にスクロールする。 |
| `browser_press` | key | Enter、Escape、Tab を押す。 |
| `browser_wait` | - | 少し待ってからもう一度観測する。 |
| `browser_screenshot` | - | 現在のビューポートの JPEG。 |
| `browser_close` | - | サーバーが保持しているセッションを閉じる。 |

すべての応答に `elapsed_ms` が含まれ、Jev を呼んだ場合は `decisions` と `cost` も含まれる。

## CLI

| コマンド | 何をするか |
|---|---|
| `run URL "goal" [--value name=text ...] [--max-steps N]`, `run --resume RUN_ID` | URL からゴールを遂行し、完了かエスカレーションで止まる |
| `search "query" ["what the page must answer"] [--max-pages 3]` | Web を検索し、最良の結果を読む |
| `open URL` | URL を開き、以降のコマンドのためにセッションを保持する |
| `observe` | 開いているページのコントロールとテキストを列挙する |
| `extract [--mode text\|elements\|links\|tables\|main]` | 開いているページから構造化データを取り出す |
| `act "instruction" [--value name=text ...]` | 開いているページで判断済みの 1 ステップを実行する |
| `click REF` | 観測済みの要素を 1 つクリックする |
| `type REF TEXT` | 観測済みのフィールドに 1 つ入力する |
| `select REF OPTION` | 観測済みのドロップダウン選択肢を選ぶ |
| `scroll down\|up` | 開いているページをスクロールする |
| `press Enter\|Escape\|Tab` | Enter、Escape、Tab を押す |
| `wait` | 少し待ってからもう一度観測する |
| `screenshot [PATH]` | ビューポートを JPEG で保存する |
| `close` | `open` が保持しているセッションを閉じる |
| `mcp` | MCP stdio サーバーを実行する |
| `skill` | エージェントガイドを出力する。スキルファイルとして保存できる |
| `install claude\|codex [--scope user\|project\|local]` | jev-ra をコーディングエージェントの MCP サーバーとして登録する |
| `doctor` | 鍵、エンドポイント、Chrome、ライブ判断 1 回を確認する |
| `bench [--live]` | オフラインのフィクスチャを計時し、`--live` ならライブタスクも計時する |
| `corpus run` | 実サイトのコーパスを実行する |

`open` … `close` は `$XDG_STATE_HOME/jev-ra/session.json` の target id を通じて 1 つのブラウザを
複数の呼び出しで共有する。どのコマンドでも `--json` を付ければ生のペイロードが得られる。

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

## 値

TYPE_TEXT には文字列が必要だが、jev-ra はそれを作り出さない。フィールドを選ぶのと同じ往復の中で、
Jev が*あなたが渡した*値のどれがそのフィールドに入るかを選ぶ。合う値がなくテキストヘルパーも設定
されていなければ、実行は `needs_value` で止まり、フィールドの label、role、現在値を返す。値を渡して
もう一度呼べばいい。既定のインストールにテキストモデルはない。

## 制御を返すとき

`Result.status` は `done`、`blocked`、`escalate`、`budget` のいずれか。実行が途中で止まったときの
`reason` は `needs_value`、`stuck_loop`、`unverified_done`、`stale`、`invalid_decision`、
`too_many_controls`、`provider_error`、`blocked`、`blocked_by_site`、`needs_human` のいずれか。`budget` で終わった実行は使い切った
予算(ステップ、判断、時間)を `reason` に入れる。`provider_error` はプロバイダが答えること自体を
拒んだということなので、ゴールを再試行せず鍵と経路を確認する。
escalate には確率つきの上位 8 件の操作/対象候補と、最大 3,000 文字のページテキストが含まれる。
もう一度観測しなくても判断できるだけの材料だ。

検証は決定論的だ。各アクションのあとに url、title、text、フィールド状態を比較し、`page_changed` は
モデルではなくページの意味ベースの marker から決まる。

エラーページで応答するサイト(HTTP 5xx・429、または自らエラーと告げる短いページ)は、何かを決める前に
2 秒待って一度だけ再読み込みする。それでもエラーなら実行は `blocked_by_site` で止まり、`detail.wall` に
ステータス(`"http 502"`)を記す。サイトの一時的な不調を操作すべきページと取り違えない。

## ベンチマーク

5 つのタスク、各 5 回実行、すべての実行を残されたページに対して検証した。2026-09-18 に OpenRouter
経由で、browser-use の記録と同じマシン、同じ Chrome で計測:

| タスク | 中央値 | p90 | 成功 | 判断 | コスト | 比率 |
|---|---|---|---|---|---|---|
| Wikipedia 記事 | 2,714 ms | 3,179 ms | 5/5 | 3 | $0.00075 | 8.50× |
| Google Flights 検索 | 8,888 ms | 10,573 ms | 5/5 | 14 | $0.00317 | 7.47× |
| Olive Young 並べ替え | 3,806 ms | 4,858 ms | 5/5 | 4 | $0.00204 | 3.96× |
| 出典つきの検索 | 2,416 ms | 2,571 ms | 5/5 | 4 | $0.00035 | 基準なし |
| ローカルの決済フォーム | 2,191 ms | 2,338 ms | 5/5 | 5 | $0.00049 | 基準なし |

比率は browser-use 0.13.10 + gemini-3-flash `flash_mode` が同じ日、同じマシン、同じ Chrome で、
やはり OpenRouter 経由で記録したタスクごとの単発の実行に対するもの(それぞれ 23,058 ms、66,414 ms、
15,071 ms)。25 回全体でテキストモデルの呼び出しは 0。同じ日に同じハーネスで browser-use をタスク
ごとに 5 回再実行すると、さらに遅かった: 9.07×、8.31×、7.26×。browser-use がタスクごとに走らせた
6 回のうち最速の記録(15,759 ms、49,914 ms、15,071 ms)と比べても、われわれの中央値は 5.8×、5.6×、
3.96× で、その日に計測した比率に 3.96× を下回るものはない。
`jev-ra bench --live --runs 5` でこの表を再現でき、基準のあるすべてのタスクについて 3× 以上という
v0.1 の基準に対する PASS/FAIL を表示する。0.2.5 で TypeSafe 直接経路(2026-09-23)を使うと、最初の
3 タスクは 4,681 ms、11,603 ms、5,675 ms かかった。その日は browser-use を再実行していないので、
これらの時間は同じ条件の比率ではない。
[測定方法、browser-use の生データ、再現手順](../BENCHMARKS.md)。

左が jev-ra、右が browser-use `flash_mode`。同じタスク、同じ Chrome、実時間:

![browser-use がまだ券種メニューを開いている間に jev-ra は航空券検索を終える](../../assets/demo/flights-side-by-side.gif)

タスクを達成せずに終わった実行は時間ではなく失敗として数える。

### 実サイトでの正確さ

コーパスは十の系統(検索、EC、予約、フォーム、ドキュメント、ニュース、ポータル、ログイン壁、日本語・中国語
サイト)にわたる実サイトの 83 タスクで、各タスクには実行が残したページを検査する仕様がある。0.2.4 で
2026-09-23 に TypeSafe 直接経路で各 3 回: **213 / 249 = 85.5 %**。両ツールに同じく与えた 40 タスク
で、browser-use 0.13.10 `flash_mode` は 2026-09-22 に各 1 回で **29 / 40 = 72 %**、成功した実行の
中央値 **19.4 s**。jev-ra 0.1 は 2026-09-18 に各 3 回で **102 / 120 = 85 %**、中央値 **3.1 s**。
この 2 行は日付、実行回数、jev-ra のバージョンが異なり、同じ条件の比較ではない。
3 回 1 セットの計測はサイト側の事情だけで 5 タスクほど揺れるため、変更はタスクごとの再実行が一致したときだけ
得失として数える。[タスクごとの行と揺れの計測](https://github.com/brnyxx/jev-ra/blob/main/docs/BENCHMARKS.md)。

## やらないこと

| 制限 | 何が起きるか |
|---|---|
| キャンバス描画、ゲームなどマークアップではなく描かれたもの | `blocked`: 目標を進められる観測済みコントロールがない |
| ファイルアップロード | `blocked`: ファイル入力は提示も入力もされない |
| CAPTCHA、ボット対策、ステルス | ページテキストを添えた `blocked`。判断は呼び出し側 |
| 認証フロー | フィールド名を添えた `needs_value`。資格情報を推測しない |
| ポップアップウィンドウ、複数タブのワークフロー | 実行は自分のターゲットに留まる |
| クロスオリジン iframe | 不透明な要素ひとつとして報告。開いた shadow root と同一オリジンの iframe は**走査する** |
| 見えているコントロールが 250 を超える場合 | `omitted` を報告し、詰まった実行は推測せず `too_many_controls` にエスカレーション |

いずれもページテキストと順位付き候補を伴うエスカレーションを返す。
## FAQ

**OpenRouter か TypeSafe の鍵か?** どちらでもいい。jev-ra は `JEV_RA_API_KEY`、`TYPESAFE_API_KEY`、
`OPENROUTER_API_KEY` の順に鍵を探す。`sk-or-` で始まる鍵は OpenRouter 経路
(`typesafe/jev-1.13`)を、それ以外は直接経路(`jev-latest`)を選ぶ。`JEV_RA_ENDPOINT` と
`JEV_RA_MODEL` が両方を上書きする。OpenRouter の方が入手しやすい。どちらの経路が速く判断するかは、
同じ条件では計測されていない。[上流 jev-ultrafast の記録](https://github.com/browser-use/jev-ultrafast/blob/main/docs/performance.md)
では直接経路の判断の中央値が 178 ms、jev-ra が記録した Flights の実行では OpenRouter 経由で中央値
296 ms(2026-09-18)。マシンも日付も異なる。

**1 タスクいくらか?** 2026-09-18 に OpenRouter 経由で **$0.00035**(検索、判断 4 回)から
**$0.00317**(Google Flights の全工程、判断 14 回)。コストはページの大きさではなく判断の回数に
比例する。送るのは HTML ではなく要素表と可視テキストだからだ。

**専用の Chrome が必要か?** 自分で見つけるか、専用プロファイル
(`$XDG_STATE_HOME/jev-ra/chrome-profile`)で起動して再利用する。`BU_CDP_URL` で別の Chrome を
指定できる。エージェントに任せたくないアカウントにログイン済みのブラウザは指さないこと。

**なぜテキストモデルがないのか?** 呼び出すエージェントがすでに文脈を持っている。2 つ目のモデルを挟むと
フィールドごとに呼び出しが 1 回増え(設計時の 2026-09-18 に OpenRouter 経由の mercury-2.5 を 5 回
計測して 675-938 ms、[設計文書](https://github.com/brnyxx/jev-ra/blob/main/docs/DESIGN.md))、誰も
渡していない値を書く。必要なら `JEV_RA_TEXT_MODEL` で付けられる。

## 設定

| 変数 | 効果 |
|---|---|
| `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | 鍵。この優先順位で |
| `JEV_RA_ENDPOINT`, `JEV_RA_MODEL` | 経路の上書き |
| `JEV_RA_CHROME` | 起動するブラウザのバイナリパス |
| `BU_CDP_URL` | 新しく起動する代わりに接続する既存の Chrome |
| `JEV_RA_VIEWPORT` | 例: `1280x900`(既定値) |
| `JEV_RA_MAX_STEPS`, `JEV_RA_MAX_DECISIONS`, `JEV_RA_TIMEOUT_S` | 予算 (40 / 80 / 120) |
| `JEV_RA_BLOCK_RESOURCES` | `0` でフォント/メディアの遮断を切る |
| `JEV_RA_PROXY` | jev-ra が起動する Chrome の egress。例: `http://host:8080` |
| `JEV_RA_PACE_S` | 1 回の実行が同じホストへ始める 2 つの遷移の最小間隔 (秒)。既定 `1`、`0` で無効、このマシン自身は対象外 |
| `JEV_RA_NOTIFY` | `0` で人間確認のデスクトップ通知を止める |
| `JEV_RA_HUMAN_WAIT_S` | 人間確認を人が解くのを待つ時間。既定 `120`、`0` ですぐに返す |
| `JEV_RA_ALLOW_FILE_URLS` | `1` でセッションが `file:` URL を開けるようになる |
| `JEV_RA_SEARCH_URL` | 検索エンドポイントのテンプレート。`{query}` が置換される |
| `JEV_RA_TEXT_MODEL`, `JEV_RA_TEXT_BASE_URL`, `JEV_RA_TEXT_API_KEY` | 任意のテキストヘルパー。既定はオフ |

`$XDG_CONFIG_HOME/jev-ra/config.json` に同じキーを書ける。環境変数が優先される。

## クレジット

`jev_ra/browser/snapshot.js` と `NEXT_ACTION` / `TARGET` の指示文は
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT)から取り込んで
調整したもので、そこで計測されたテキストだ。Chrome の駆動には
[browser-harness](https://github.com/browser-use/browser-harness)(MIT)を使う。
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) を参照。

MIT ライセンス。[コントリビュート](../../CONTRIBUTING.md) · [セキュリティ](../../SECURITY.md) ·
[エージェントガイド](../../AGENTS.md) · [利用リファレンス](../USAGE.md)

[English](../../README.md) · [한국어](README.ko.md) · **日本語** · [简体中文](README.zh-CN.md)

[変更履歴](../../CHANGELOG.md) · [リリース](https://github.com/brnyxx/jev-ra/releases)
