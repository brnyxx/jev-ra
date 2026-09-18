# jev-ra

**CLI 코딩 에이전트를 위한 빠른 브라우저 조작 계층.** Claude Code, Codex, 또는 MCP 클라이언트가
jev-ra에 목표를 넘긴다. System One 결정 모델인 TypeSafe Jev가 한 번의 왕복으로 각 단계의 연산과
대상 요소를 함께 고른다. 계획을 세우고, 입력할 값을 주고, 페이지를 읽고, jev-ra가 escalate하면
넘겨받는 것은 호출한 에이전트의 몫이다. 루프 안에서 두 번째 LLM이 도는 일은 없다.

![jev-ra가 3초 안에 괴델 불완전성 정리 문서를 여는 모습](assets/demo/wikipedia.gif)

| 과제 | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra | |
|---|---|---|---|
| Wikipedia: 괴델 불완전성 정리 문서 열기 | 23,058 ms | **2,714 ms** | **8.5배** |
| Google Flights ZRH→LON 편도, 결과 표시까지 | 66,414 ms | **8,888 ms** | **7.5배** |
| 올리브영 카테고리: 신상품순 정렬 | 15,071 ms | **3,806 ms** | **4.0배** |

각 5회 실행의 중앙값. 2026-09-18, 같은 머신, 같은 전용 Chrome, 양쪽 모두 OpenRouter 경유.
모든 실행은 남긴 페이지를 기준으로 검증했고 25번 중 25번 통과했으며 텍스트 모델 호출은 0이었다.
[측정 방법, p90, 비용, 원본 기록](docs/BENCHMARKS.md).

## 빠른 시작

**Claude Code**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install claude
# 이후 Claude Code에서: "wikipedia.org 열어서 괴델 불완전성 정리 문서 찾아줘"
```

**Codex**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra install codex
# 이후 Codex에서: "jev-ra로 wikipedia.org 열어서 괴델 불완전성 정리 문서 찾아줘"
```

**셸**

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra doctor
uvx jev-ra run https://en.wikipedia.org/wiki/Main_Page "Open the Godel incompleteness article." \
  --value "search_query=Godel incompleteness theorems"
```

설치 단계는 없다. `uvx`가 PyPI에서 바로 실행하고, 서버 명령으로 `uvx jev-ra mcp`를 등록한다.
영구 설치는 `uv tool install jev-ra`. 키는 이미 export해 둔 변수에서 전달되며 출력되지 않는다.

## 동작 방식

```
  당신의 에이전트                  jev-ra                              Chrome
 ────────────────            ───────────────                      ─────────────
  목표 + values  ──────────▶  observe ─────────────────────────▶  snapshot.js
                              │   요소, 가드, 페이지 marker      ◀──── eval 한 번
                              ▼
                              한 번의 요청: 연산? 대상?
                              값? prev_ok? goal_achieved?    ──▶  Jev  (~300 ms)
                              │
                              ▼
                              신선도 가드 ──▶ act ─────────────▶  신뢰된 CDP 입력
                              │                                    (JS 클릭 아님)
                              ▼
                              url/title/text/필드 상태 검증
                              │
       Result  ◀──────────────┴── done · blocked · escalate · budget
```

단계마다 결정 하나, 왕복 한 번, 실행 경로에는 모델이 없다. 페이지에 들어가는 텍스트는 당신이 준
값뿐이다.

## MCP 도구

| 도구 | 인자 | 하는 일 |
|---|---|---|
| `browser_open` | url | 공유 세션에서 URL을 열고 페이지를 요약한다. |
| `browser_run` | goal, values?, max_steps? | 목표 전체를 수행한다. 입력이 필요한 값은 values로 준다. |
| `browser_search` | query, goal?, max_pages? | 검색하고, 상위 결과를 병렬 탭에서 읽어 목표 기준으로 순위를 매긴다. |
| `browser_act` | instruction, values? | 지시에 맞는 한 단계를 결정해 실행한다. |
| `browser_observe` | max_elements? | 관측된 컨트롤과 보이는 텍스트를 나열한다. |
| `browser_extract` | mode? | 구조화된 페이지 데이터: `text`, `elements`, `links`, `tables`, `main`. |
| `browser_click` | ref | 관측된 요소를 ref로 클릭한다. |
| `browser_type` | ref, text | 관측된 입력 필드에 텍스트를 넣는다. |
| `browser_select` | ref, option | 관측된 드롭다운 옵션을 고른다. |
| `browser_scroll` | direction? | 한 화면만큼 위아래로 스크롤한다. |
| `browser_press` | key | Enter, Escape, Tab을 누른다. |
| `browser_wait` | - | 잠시 기다린 뒤 다시 관측한다. |
| `browser_screenshot` | - | 현재 뷰포트의 JPEG. |
| `browser_close` | - | 서버가 들고 있는 세션을 닫는다. |

모든 응답에 `elapsed_ms`가 담기고, Jev를 호출했다면 `decisions`와 `cost`도 함께 담긴다.

## CLI

```sh
jev-ra run URL "goal" [--value name=text ...] [--max-steps N] [--json]
jev-ra search "query" ["페이지가 답해야 할 것"] [--max-pages 3]
jev-ra open URL | observe | extract [--mode text|elements|links|tables|main]
jev-ra act "instruction" | click REF | type REF TEXT | select REF OPTION
jev-ra scroll down|up | press Enter|Escape|Tab | wait | screenshot [PATH] | close
jev-ra mcp | install claude|codex [--scope user|project|local] | doctor | bench [--live]
```

`open` … `close`는 `$XDG_STATE_HOME/jev-ra/session.json`의 target id를 통해 하나의 브라우저를
여러 호출에 걸쳐 공유한다. 어느 명령에든 `--json`을 붙이면 원본 페이로드가 나온다.

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

## 추측하지 않고 값을 받는다

TYPE_TEXT에는 문자열이 필요하고, jev-ra는 그것을 지어내지 않는다. 필드를 고르는 같은 왕복 안에서
Jev가 *당신이 준* 값 중 어느 것이 그 필드에 들어갈지 고른다. 맞는 값이 없고 텍스트 헬퍼도 설정돼
있지 않으면 실행은 `needs_value`로 멈추고 필드의 label, role, 현재 값을 알려준다. 값을 주고 다시
호출하면 된다. 기본 설치에 텍스트 모델이 없다는 것이 이 설계의 핵심이다.

## 제어를 되돌려줄 때

`Result.status`는 `done`, `blocked`, `escalate`, `budget` 중 하나다. escalate에는 `reason`
(`needs_value`, `stuck_loop`, `unverified_done`, `stale`, `invalid_decision`, `too_many_controls`),
확률이 붙은 상위 8개 연산/대상 후보, 최대 3,000자의 페이지 텍스트가 담긴다. 다시 관측하지 않고도
판단할 수 있을 만큼이다.

검증은 결정론적이다. 매 행동 뒤 url, title, text, 필드 상태를 비교하고, `page_changed`는 모델의
의견이 아니라 페이지의 의미 기반 marker에서 나온다.

## 하지 않는 것

Canvas, 파일 업로드, 팝업 창, 다중 탭 워크플로, 인증 플로, CAPTCHA, stealth. 보이는 컨트롤이
250개를 넘는 페이지는 `omitted`를 보고하고 추측 대신 `too_many_controls`로 escalate한다.
교차 출처 iframe은 하나의 불투명한 요소로 보고하며, 열린 shadow root와 동일 출처 iframe은
**훑는다**.

## FAQ

**OpenRouter인가 TypeSafe 키인가?** 둘 다 된다. jev-ra는 `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`,
`OPENROUTER_API_KEY` 순으로 키를 찾는다. `sk-or-`로 시작하는 키는 OpenRouter 경로
(`typesafe/jev-1.13`)를, 그 외에는 직접 경로(`jev-latest`)를 고른다. `JEV_RA_ENDPOINT`와
`JEV_RA_MODEL`이 둘 다 덮어쓴다. OpenRouter가 구하기 쉽고, 상류 측정에 따르면 직접 호출이 결정당
약 140 ms 빠르다.

**한 과제에 얼마가 드나?** **$0.00035**(검색, 결정 4번)에서 **$0.00317**(Google Flights 전체 흐름,
결정 14번) 사이다. 비용은 페이지 크기가 아니라 결정 횟수에 비례한다. 보내는 상태가 HTML이 아니라
요소 표와 보이는 텍스트이기 때문이다.

**전용 Chrome이 필요한가?** 직접 찾거나 자체 프로필(`$XDG_STATE_HOME/jev-ra/chrome-profile`)로
띄워서 재사용한다. `BU_CDP_URL`로 다른 Chrome을 가리킬 수 있다. 에이전트에게 맡기고 싶지 않은
계정에 로그인된 브라우저는 가리키지 마라.

**왜 텍스트 모델이 없나?** 호출하는 쪽이 이미 문맥을 가진 LLM이기 때문이다. 두 번째 모델을 넣으면
필드당 675-938 ms가 더 들고 값을 지어낸다. 원하면 `JEV_RA_TEXT_MODEL`로 붙일 수 있다.

## 설정

| 변수 | 효과 |
|---|---|
| `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | 키, 이 우선순위로 |
| `JEV_RA_ENDPOINT`, `JEV_RA_MODEL` | 경로 재정의 |
| `JEV_RA_CHROME` | 띄울 브라우저 바이너리 경로 |
| `BU_CDP_URL` | 새로 띄우는 대신 붙을 기존 Chrome |
| `JEV_RA_VIEWPORT` | 예: `1280x900` (기본값) |
| `JEV_RA_MAX_STEPS`, `JEV_RA_MAX_DECISIONS`, `JEV_RA_TIMEOUT_S` | 예산 (40 / 80 / 120) |
| `JEV_RA_BLOCK_RESOURCES` | `0`이면 폰트/미디어 차단을 끈다 |
| `JEV_RA_SEARCH_URL` | 검색 엔드포인트 템플릿, `{query}`가 치환된다 |
| `JEV_RA_TEXT_MODEL`, `JEV_RA_TEXT_BASE_URL`, `JEV_RA_TEXT_API_KEY` | 선택적 텍스트 헬퍼, 기본은 꺼짐 |

`$XDG_CONFIG_HOME/jev-ra/config.json`에 같은 키를 쓸 수 있고, 환경변수가 우선한다.

## 출처

`jev_ra/browser/snapshot.js`와 `NEXT_ACTION` / `TARGET` 지시문은
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT)에서 가져와 다듬은
것이며, 그곳에서 측정된 텍스트다. Chrome 구동은
[browser-harness](https://github.com/browser-use/browser-harness)(MIT)를 쓴다.
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 보라.

MIT 라이선스. [기여 안내](CONTRIBUTING.md) · [보안](SECURITY.md) · [English](README.md)
