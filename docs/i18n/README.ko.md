<p align="center">
  <img src="../../assets/logo.svg" alt="jev-ra" width="360">
</p>

<p align="center">
  <a href="https://github.com/brnyxx/jev-ra/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/brnyxx/jev-ra/ci.yml?branch=main&label=ci""></a>
  <a href="https://pypi.org/project/jev-ra/"><img alt="PyPI" src="https://img.shields.io/pypi/v/jev-ra""></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue"">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-111"">
  <img alt="Chrome" src="https://img.shields.io/badge/Chrome-CDP-111"">
  <a href="../../LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

[![jev-ra: 코딩 에이전트를 위한 브라우저 조작, browser-use보다 4-8.5× 빠르다](../../assets/hero.png)](../BENCHMARKS.md)

[English](../../README.md) · **한국어** · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

**사이트:** [brnyxx.github.io/jev-ra](https://brnyxx.github.io/jev-ra/?lang=ko)에서 실제 기록된 실행을 재생하고 파이프라인을 설명한다.

# jev-ra

**CLI 코딩 에이전트를 위한 빠른 브라우저 조작 계층.** Claude Code, Codex, 또는 MCP 클라이언트가
jev-ra에 목표를 넘긴다. System One 결정 모델인 TypeSafe Jev가 한 번의 왕복으로 각 단계의 연산과
대상 요소를 함께 고른다. 계획을 세우고, 입력할 값을 주고, 페이지를 읽고, jev-ra가 escalate하면
넘겨받는 것은 호출한 에이전트의 몫이다. 루프 안에서 두 번째 LLM이 도는 일은 없다.

![jev-ra가 괴델 불완전성 정리 문서를 여는 모습. 녹화의 시계는 3.79 s 에서 멈춘다](../../assets/demo/wikipedia.gif)

| 과제 | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra | |
|---|---|---|---|
| Wikipedia: 괴델 불완전성 정리 문서 열기 | 23,058 ms | **2,714 ms** | **8.50×** |
| Google Flights ZRH→LON 편도, 결과 표시까지 | 66,414 ms | **8,888 ms** | **7.47×** |
| 올리브영 카테고리: 신상품순 정렬 | 15,071 ms | **3,806 ms** | **3.96×** |

2026-09-18 에 머신 하나, 전용 Chrome 하나에서 쟀고 두 도구 모두 OpenRouter 를 거쳤다. jev-ra 는
5회 실행의 중앙값이고, browser-use 는 기록된 단일 실행이다. 그 단일 실행은 모든 과제에서 browser-use
자신의 5회 중앙값보다 빨랐다. jev-ra 의 각 실행은 마지막 페이지를 기준으로 검증했고, 25번 중 25번
통과했으며 텍스트 모델 호출은 0이었다. [측정 방법, p90, 비용, 원본 기록](../BENCHMARKS.md).

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

Python을 따로 갖추기 싫다면 `npx -y jev-ra install claude`가 npm 런처로 같은 일을 한다. npm 패키지는
런처일 뿐이다. `uv`를 찾고, 없으면 설치를 제안하고, 자기 버전에 고정된 PyPI 패키지를 실행한다.

어느 쪽이든 설치 단계는 없다. `uvx`가 PyPI에서 바로 실행하고, 서버 명령으로 `uvx jev-ra mcp`를
등록한다. 영구 설치는 `uv tool install jev-ra`. 키는 이미 export해 둔 변수에서 전달되며 출력되지
않는다.

## 동작 방식

![한 스텝의 동작: 관찰, 결정, 실행, 검증, 종료 또는 반환, 그리고 browser-use 대비 스텝당 시간](https://raw.githubusercontent.com/brnyxx/jev-ra/main/assets/readme-step.svg)

![아키텍처: 에이전트는 MCP 로 jev-ra 와 말하고, jev-ra 는 DevTools Protocol 로 Chrome 을 움직이며 스텝마다 한 번 TypeSafe Jev 에 묻는다](https://raw.githubusercontent.com/brnyxx/jev-ra/main/assets/readme-architecture.svg)

단계마다 결정 하나. 페이지에 입력되는 텍스트는 당신이 준
값뿐이다.

## MCP 도구

| 도구 | 인자 | 하는 일 |
|---|---|---|
| `browser_open` | url | 공유 세션에서 URL을 열고 페이지를 요약한다. |
| `browser_run` | goal, values?, max_steps?, resume? | 목표 전체를 수행한다. 입력이 필요한 값은 values로 준다. `resume`은 `needs_human`으로 멈춘 실행을 이어 간다. |
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

| 명령 | 하는 일 |
|---|---|
| `run URL "goal" [--value name=text ...] [--max-steps N]`, `run --resume RUN_ID` | URL에서 목표를 추구하고 완료되거나 에스컬레이션되면 멈춘다 |
| `search "query" ["what the page must answer"] [--max-pages 3]` | 웹을 검색하고 가장 좋은 결과를 읽는다 |
| `open URL` | URL을 열고 이후 명령을 위해 세션을 유지한다 |
| `observe` | 열린 페이지의 컨트롤과 텍스트를 나열한다 |
| `extract [--mode text\|elements\|links\|tables\|main]` | 열린 페이지에서 구조화된 데이터를 뽑는다 |
| `act "instruction" [--value name=text ...]` | 열린 페이지에서 결정된 한 단계를 실행한다 |
| `click REF` | 관측된 요소 하나를 클릭한다 |
| `type REF TEXT` | 관측된 필드 하나에 입력한다 |
| `select REF OPTION` | 관측된 드롭다운 옵션을 고른다 |
| `scroll down\|up` | 열린 페이지를 스크롤한다 |
| `press Enter\|Escape\|Tab` | Enter, Escape, Tab을 누른다 |
| `wait` | 잠시 기다린 뒤 다시 관측한다 |
| `screenshot [PATH]` | 뷰포트를 JPEG로 저장한다 |
| `close` | `open`이 남긴 세션을 닫는다 |
| `mcp` | MCP stdio 서버를 실행한다 |
| `skill` | 에이전트 가이드를 출력한다. 스킬 파일로 저장할 수 있다 |
| `install claude\|codex [--scope user\|project\|local]` | jev-ra를 코딩 에이전트의 MCP 서버로 등록한다 |
| `doctor` | 키, 엔드포인트, Chrome, 라이브 결정 하나를 점검한다 |
| `bench [--live]` | 오프라인 픽스처를 재고, `--live`면 라이브 과제도 잰다 |
| `corpus run` | 실제 사이트 코퍼스를 실행한다 |

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

## 값

TYPE_TEXT에는 문자열이 필요하고, jev-ra는 그것을 지어내지 않는다. 필드를 고르는 같은 왕복 안에서
Jev가 *당신이 준* 값 중 어느 것이 그 필드에 들어갈지 고른다. 맞는 값이 없고 텍스트 헬퍼도 설정돼
있지 않으면 실행은 `needs_value`로 멈추고 필드의 label, role, 현재 값을 알려준다. 값을 주고 다시
호출하면 된다. 기본 설치에는 텍스트 모델이 없다.

## 제어를 되돌려줄 때

`Result.status`는 `done`, `blocked`, `escalate`, `budget` 중 하나다. 실행이 중간에 멈추면 `reason`은
`needs_value`, `stuck_loop`, `unverified_done`, `stale`, `invalid_decision`, `too_many_controls`,
`provider_error`, `blocked`, `blocked_by_site`, `needs_human` 중 하나다. `budget`으로 끝난 실행은 소진된 예산(스텝, 결정, 시간)을
`reason`에 담는다. `provider_error`는 공급자가 답하기를 거부한 것이므로, 목표를 다시 시도하지
말고 키와 경로를 확인한다. escalate에는 확률이
붙은 상위 8개 연산/대상 후보와 최대 3,000자의 페이지 텍스트가 담긴다. 다시 관측하지 않고도 판단할
수 있을 만큼이다.

검증은 결정론적이다. 매 행동 뒤 url, title, text, 필드 상태를 비교하고, `page_changed`는 모델의
의견이 아니라 페이지의 의미 기반 marker에서 나온다.

에러 페이지로 답하는 사이트(HTTP 5xx·429, 또는 스스로 에러라고 말하는 짧은 페이지)는 무엇도 결정하기 전에
2초 기다렸다가 한 번 다시 불러온다. 그래도 에러면 실행은 `blocked_by_site`로 멈추고 `detail.wall`에
상태(`"http 502"`)를 적는다. 사이트가 잠깐 앓는 순간을 조작할 페이지로 착각하지 않는다.

## 벤치마크

다섯 과제, 각 5회 실행, 모든 실행을 남긴 페이지 기준으로 검증했다. 2026-09-18 에 OpenRouter 를
거쳐, browser-use 기록과 같은 머신, 같은 Chrome 에서 쟀다:

| 과제 | 중앙값 | p90 | 성공 | 결정 | 비용 | 비율 |
|---|---|---|---|---|---|---|
| Wikipedia 문서 | 2,714 ms | 3,179 ms | 5/5 | 3 | $0.00075 | 8.50× |
| Google Flights 검색 | 8,888 ms | 10,573 ms | 5/5 | 14 | $0.00317 | 7.47× |
| 올리브영 정렬 | 3,806 ms | 4,858 ms | 5/5 | 4 | $0.00204 | 3.96× |
| 인용까지 포함한 검색 | 2,416 ms | 2,571 ms | 5/5 | 4 | $0.00035 | 기준선 없음 |
| 로컬 결제 폼 | 2,191 ms | 2,338 ms | 5/5 | 5 | $0.00049 | 기준선 없음 |

비율은 browser-use 0.13.10 + gemini-3-flash `flash_mode` 가 같은 날, 같은 머신, 같은 Chrome 에서
역시 OpenRouter 를 거쳐 기록한 과제별 단일 실행 기준이다(각각 23,058 ms, 66,414 ms, 15,071 ms).
25회 전체에서 텍스트 모델 호출은 0. 같은 날 같은 하네스로 browser-use를 과제당 5회 다시 돌린 결과는
더 느렸다: 9.07×, 8.31×, 7.26×. browser-use 가 과제마다 돌린 여섯 번 중 가장 빠른 기록(15,759 ms,
49,914 ms, 15,071 ms)과 비교해도 우리 중앙값은 5.8×, 5.6×, 3.96×이고, 그날 잰 비율 중 3.96×보다
낮은 것은 없다.
`jev-ra bench --live --runs 5`로 이 표를 재현할 수 있고, 기준선이 있는 모든 과제에 대해 3×
이상이라는 v0.1 기준의 PASS/FAIL을 찍는다. 0.2.5 에서 TypeSafe 직접 경로로(2026-09-23) 앞의 세
과제는 4,681 ms, 11,603 ms, 5,675 ms 가 걸렸다. 그날은 browser-use 를 다시 돌리지 않았으므로 이
시간들은 같은 조건의 비율이 아니다.
[측정 방법, browser-use 원본 기록, 재현 방법](../BENCHMARKS.md).

왼쪽이 jev-ra, 오른쪽이 browser-use `flash_mode`. 같은 과제, 같은 Chrome, 실시간:

![browser-use가 아직 티켓 유형 메뉴를 여는 동안 jev-ra는 항공편 검색을 끝낸다](../../assets/demo/flights-side-by-side.gif)

과제를 해내지 못하고 끝난 실행은 시간이 아니라 실패로 센다.

### 실제 사이트 정확도

코퍼스는 열 개 계열(검색, 쇼핑, 예약, 폼, 문서, 뉴스, 포털, 로그인 벽, 일본어·중국어 사이트)의 실제
사이트 과제 83개이고, 과제마다 실행이 남긴 페이지를 검사하는 명세가 있다. 0.2.4에서 2026-09-23 에
TypeSafe 직접 경로로 과제당 세 번: **213 / 249 = 85.5 %**. 두 도구에 똑같이 준 과제 40개에서
browser-use 0.13.10 `flash_mode`는 2026-09-22 에 한 번씩 돌려 **29 / 40 = 72 %**, 통과한 실행의
중앙값 **19.4 s**였고, jev-ra 0.1은 2026-09-18 에 세 번씩 돌려 **102 / 120 = 85 %**, 중앙값
**3.1 s**였다. 두 줄은 날짜, 실행 횟수, jev-ra 버전이 달라 같은 조건의 비교가 아니다.
세 번 돌리는 한 판은 사이트 사정만으로 다섯 과제쯤 흔들리므로, 변경은 과제별 재실행이 같은 결과를 낼 때만
득실로 센다. [과제별 행과 흔들림 측정](https://github.com/brnyxx/jev-ra/blob/main/docs/BENCHMARKS.md).

## 하지 않는 것

| 한계 | 결과 |
|---|---|
| 캔버스 드로잉, 게임 등 마크업이 아니라 그려진 것 | `blocked`: 목표를 진행시킬 수 있는 관측된 컨트롤이 없음 |
| 파일 업로드 | `blocked`: 파일 입력은 제시되지도, 입력되지도 않음 |
| CAPTCHA, 봇 차단, 스텔스 | 페이지 텍스트와 함께 `blocked`, 판단은 호출자 몫 |
| 인증 흐름 | 필드 이름을 담은 `needs_value`. 자격 증명을 추측하지 않음 |
| 팝업 창, 멀티 탭 워크플로 | 실행은 자기 타깃에 머무름 |
| 교차 출처 iframe | 불투명한 요소 하나로 보고. 열린 shadow root와 동일 출처 iframe은 **순회함** |
| 보이는 컨트롤이 250개를 넘을 때 | `omitted`를 보고하고, 막힌 실행은 추측 대신 `too_many_controls`로 에스컬레이션 |

각각 페이지 텍스트와 순위가 매겨진 후보를 담은 에스컬레이션을 돌려준다.
## FAQ

**OpenRouter인가 TypeSafe 키인가?** 둘 다 된다. jev-ra는 `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`,
`OPENROUTER_API_KEY` 순으로 키를 찾는다. `sk-or-`로 시작하는 키는 OpenRouter 경로
(`typesafe/jev-1.13`)를, 그 외에는 직접 경로(`jev-latest`)를 고른다. `JEV_RA_ENDPOINT`와
`JEV_RA_MODEL`이 둘 다 덮어쓴다. OpenRouter가 구하기 쉽다. 어느 경로가 더 빨리 결정하는지는 같은
조건에서 잰 적이 없다. [상류 jev-ultrafast 의 기록](https://github.com/browser-use/jev-ultrafast/blob/main/docs/performance.md)은
직접 경로에서 결정 중앙값 178 ms 이고, jev-ra 가 기록한 Flights 실행은 OpenRouter 를 거쳐 중앙값
296 ms 였다(2026-09-18). 머신도 날짜도 다르다.

**한 과제에 얼마가 드나?** 2026-09-18 에 OpenRouter 를 거쳐 **$0.00035**(검색, 결정 4번)에서
**$0.00317**(Google Flights 전체 흐름, 결정 14번) 사이였다. 비용은 페이지 크기가 아니라 결정
횟수에 비례한다. 보내는 상태가 HTML이 아니라 요소 표와 보이는 텍스트이기 때문이다.

**전용 Chrome이 필요한가?** 직접 찾거나 자체 프로필(`$XDG_STATE_HOME/jev-ra/chrome-profile`)로
띄워서 재사용한다. `BU_CDP_URL`로 다른 Chrome을 가리킬 수 있다. 에이전트에게 맡기고 싶지 않은
계정에 로그인된 브라우저는 가리키지 마라.

**왜 텍스트 모델이 없나?** 호출하는 에이전트가 이미 문맥을 갖고 있다. 두 번째 모델을 넣으면 필드마다
호출이 한 번 더 들고(설계 때 2026-09-18 에 OpenRouter 를 거친 mercury-2.5 호출 다섯 번이
675-938 ms, [설계 문서](https://github.com/brnyxx/jev-ra/blob/main/docs/DESIGN.md)), 아무도 주지 않은
값을 쓴다. 원하면 `JEV_RA_TEXT_MODEL`로 붙일 수 있다.

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
| `JEV_RA_PROXY` | jev-ra가 띄우는 Chrome의 egress. 예: `http://host:8080` |
| `JEV_RA_PACE_S` | 한 실행이 같은 호스트로 여는 두 이동 사이의 최소 초. 기본 `1`, `0`이면 끔, 이 머신은 제외 |
| `JEV_RA_NOTIFY` | `0`이면 사람 확인이 띄우는 데스크톱 알림을 끔 |
| `JEV_RA_HUMAN_WAIT_S` | 사람 확인을 사람이 풀어 주기를 기다리는 시간. 기본 `120`, `0`이면 바로 돌려줌 |
| `JEV_RA_ALLOW_FILE_URLS` | `1`이면 세션이 `file:` URL을 열 수 있다 |
| `JEV_RA_SEARCH_URL` | 검색 엔드포인트 템플릿, `{query}`가 치환된다 |
| `JEV_RA_TEXT_MODEL`, `JEV_RA_TEXT_BASE_URL`, `JEV_RA_TEXT_API_KEY` | 선택적 텍스트 헬퍼, 기본은 꺼짐 |

`$XDG_CONFIG_HOME/jev-ra/config.json`에 같은 키를 쓸 수 있고, 환경변수가 우선한다.

## 출처

`jev_ra/browser/snapshot.js`와 `NEXT_ACTION` / `TARGET` 지시문은
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT)에서 가져와 다듬은
것이며, 그곳에서 측정된 텍스트다. Chrome 구동은
[browser-harness](https://github.com/browser-use/browser-harness)(MIT)를 쓴다.
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)를 보라.

MIT 라이선스. [기여 안내](../../CONTRIBUTING.md) · [보안](../../SECURITY.md) ·
[에이전트 가이드](../../AGENTS.md) · [사용 레퍼런스](../USAGE.md)

[English](../../README.md) · **한국어** · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

[변경 내역](../../CHANGELOG.md) · [릴리스](https://github.com/brnyxx/jev-ra/releases)
