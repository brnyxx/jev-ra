# jev-ra

**CLI 코딩 에이전트를 위한 빠른 브라우저 조작 계층.** Claude Code, Codex, 또는 MCP 클라이언트가
jev-ra에 목표를 넘긴다. System One 결정 모델인 TypeSafe Jev가 한 번의 왕복으로 각 단계의 연산과
대상 요소를 함께 고른다. 계획을 세우고, 입력할 값을 주고, 페이지 내용을 읽고, jev-ra가 escalate할 때
넘겨받는 것은 호출한 에이전트의 몫이다. 루프 안에서 두 번째 LLM이 도는 일은 없다.

패키지 하나, 브라우저 코어 하나 위의 세 가지 얼굴: MCP 서버(`jev-ra mcp`), CLI
(`jev-ra run|open|observe|extract|…`), Python API(`jev_ra.Agent`).

## 왜

매 단계마다 full LLM을 돌리는 브라우저 에이전트는 클릭 한 번에 1-3초를 쓴다. jev-ra는 타입이 정해진
결정 한 번만 쓰고, OpenRouter 경유로 274-508 ms가 측정됐다.

| | browser-use 0.13.10 + gemini-3-flash `flash_mode` | jev-ra |
|---|---|---|
| Wikipedia: 괴델 불완전성 정리 문서 열기 | 23,058 ms · 4 steps | **2,798 ms · 2 steps** (8.2배) |

두 행 모두 2026-09-18, 같은 머신, 같은 전용 Chrome(`BU_CDP_URL=http://127.0.0.1:9222`, 1280×900),
OpenRouter 경유 모델, 각 1회 실행이다. browser-use 원본 기록은
[`docs/benchmarks/2026-09-18-browser-use-baseline/`](docs/benchmarks/2026-09-18-browser-use-baseline/)에
있고, jev-ra 행은 `jev-ra bench --live`로 재현한다. 아직 통과하지 못하는 두 과제는
[벤치마크](#벤치마크)를 보라.

## 설치

```sh
export OPENROUTER_API_KEY=sk-or-...
uvx jev-ra doctor
```

설치 단계가 따로 없다. `uvx`가 PyPI에서 바로 실행한다. 영구 설치를 원하면 `uv tool install jev-ra`
또는 `pip install jev-ra`.

`doctor`는 키, 경로, Chrome 연결을 확인하고 실제 결정을 한 번 내려 지연 시간을 보여준다. jev-ra는
[browser-harness](https://github.com/browser-use/browser-harness)를 통해 CDP로 실제 Chrome에 붙는다.
평소 쓰는 브라우저를 건드리지 않도록 전용 프로필을 띄워 가리키는 것이 좋다.

```sh
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir="$HOME/.jev-ra-chrome" &
export BU_CDP_URL=http://127.0.0.1:9222
```

## 코딩 에이전트에 붙이기

```sh
uvx jev-ra install claude   # 실행: claude mcp add jev-ra -s user -e OPENROUTER_API_KEY=… -- uvx jev-ra mcp
uvx jev-ra install codex    # 실행: codex  mcp add jev-ra --env OPENROUTER_API_KEY=… -- uvx jev-ra mcp
```

먼저 설치할 것은 없다. `uvx`가 필요할 때 jev-ra를 받아오고, 등록되는 명령은 `uvx jev-ra mcp`다.
jev-ra가 이미 `PATH`에 있으면 그냥 `jev-ra mcp`가 등록된다. `--scope user|project|local`로 Claude
Code가 어디에 저장할지 고른다.

키는 이미 export해 둔 변수에서 그대로 전달되며 절대 출력되지 않는다. `claude`나 `codex`가 `PATH`에
없으면 실행 대신 명령어를 출력한다.

### MCP 도구

| 도구 | 인자 | 하는 일 |
|---|---|---|
| `browser_open` | url | 공유 세션에서 URL을 열고 페이지를 요약한다. |
| `browser_run` | goal, values?, max_steps? | 목표 전체를 수행한다. 입력이 필요한 값은 values로 준다. |
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

모든 응답에 `elapsed_ms`가 담기고, Jev를 호출한 경우 `decisions`와 `cost`도 함께 담긴다.

## 셸에서 쓰기

```sh
jev-ra run https://en.wikipedia.org/wiki/Main_Page \
  "Find and open the Wikipedia article about Godel incompleteness theorems." \
  --value "search_query=Godel incompleteness theorems"
```

```
done: goal_achieved
https://en.wikipedia.org/wiki/G%C3%B6del%27s_incompleteness_theorems
  1. TYPE_TEXT Search Wikipedia 'Godel incompleteness theorems' (p=0.88, 326 ms, changed)
  2. CLICK Gödel's incompleteness theorems … (p=0.75, 274 ms, changed)
2 steps, 5 decisions, 0 text calls, 2959 ms, $0.001195
```

`open` … `close`는 하나의 브라우저를 여러 호출에 걸쳐 공유하므로 한 단계씩 몰아갈 수 있다.

```sh
jev-ra open https://example.com
jev-ra observe
jev-ra click e3
jev-ra extract --mode links
jev-ra close
```

어느 명령에든 `--json`을 붙이면 원본 페이로드가 나온다. 전체 목록은 `jev-ra --help`.

## Python에서 쓰기

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
호출하면 된다. 기본 설치에 텍스트 모델이 없다는 것이 바로 이 설계의 핵심이다.

## 제어를 되돌려줄 때

`Result.status`는 `done`, `blocked`, `escalate`, `budget` 중 하나다. escalate에는 `reason`
(`needs_value`, `stuck_loop`, `unverified_done`, `stale`, `invalid_decision`, `too_many_controls`),
확률이 붙은 상위 8개 연산/대상 후보, 그리고 최대 3,000자의 페이지 텍스트가 담긴다. 다시 관측하지
않고도 호출한 에이전트가 판단할 수 있을 만큼이다.

검증은 결정론적이다. 매 행동 뒤 url, title, text, 필드 상태를 비교하고, `page_changed`는 모델의
의견이 아니라 페이지의 의미 기반 marker에서 나온다. 아무것도 바꾸지 못한 행동이 세 번 연속이거나
같은 선택이 세 번 연속이면 실행을 멈춘다.

## 안전 속성

- 모델 출력이 셀렉터, 좌표, JavaScript가 되는 일은 없다. 실행되는 모든 대상은 같은 스냅샷에서
  관측된 node id로 해석된다.
- 모든 행동은 입력 직전에 신선도를 다시 확인한다. 옮겨졌거나 교체됐거나 비활성화됐거나 가려진
  컨트롤은 엉뚱한 것을 클릭하는 대신 `StalePage`를 낸다.
- 입력은 합성 JS 클릭이 아니라 신뢰된 CDP 이벤트로 전달된다.
- password, file, hidden 입력은 관측도 보고도 되지 않는다.

## 벤치마크

기록된 browser-use 기준선, 2026-09-18, `use_vision=False`, 각 1회 실행
([원본 기록](docs/benchmarks/2026-09-18-browser-use-baseline/)):

| 과제 | gemini-3-flash | gemini-3-flash `flash_mode` | gpt-5-mini |
|---|---|---|---|
| Wikipedia: 괴델 불완전성 정리 문서 | 46,461 ms · 5 steps | 23,058 ms · 4 steps | 100,399 ms · 11 steps |
| Google Flights ZRH→LON 편도 | 63,565 ms · 11 steps | 66,414 ms · 11 steps | 238,045 ms (예산 소진) |
| 올리브영 카테고리: 신상품순 정렬 | 17,493 ms · 3 steps | 15,071 ms · 3 steps | 240초 타임아웃 |

claude-sonnet-5는 OpenRouter 경유로 browser-use를 전혀 구동하지 못해(구조화 출력 스키마에서
`compiled grammar is too large`) 비율 계산에서 제외했다.

`jev-ra bench`는 네트워크 없이 스크립트된 결정으로 오프라인 픽스처 과제 두 개의 시간을 잰다
(폼 입력 164 ms · 4 steps, 카탈로그 정렬 73 ms · 2 steps). `jev-ra bench --live`는 위 세 과제를
실행해 `jev-ra ms / flash_mode ms = ratio`를 출력하고, 모든 과제에서 3배 이상이라는 v0.1 합격
기준에 대해 PASS/FAIL을 찍는다.

**2026-09-18 기준 v0.1의 현재 위치, 각 1회 실행:**

| 과제 | jev-ra | 비율 | 판정 |
|---|---|---|---|
| Wikipedia | 2,798 ms · 2 steps · 5 decisions | 8.2배 | PASS |
| Google Flights | 4,377 ms 만에 `blocked` | - | FAIL, 완수하지 못함 |
| 올리브영 정렬 | 6,482 ms 만에 `blocked` | - | FAIL, 완수하지 못함 |

두 실패는 속도가 아니라 기능의 문제다. 해당 페이지들은 컨트롤을 shadow root와 iframe 안에 두는데,
v0.1은 그 안을 훑지 않는다. 이 README의 어떤 수치도 추정값이 아니다.

## v0.1이 하지 않는 것

Shadow root, iframe, canvas, 파일 업로드, 팝업 창, 다중 탭 워크플로, 인증 플로, CAPTCHA, stealth.
보이는 컨트롤이 250개를 넘는 페이지는 `omitted`를 보고하고 추측하는 대신 `too_many_controls`로
escalate한다.

## 설정

| 변수 | 효과 |
|---|---|
| `JEV_RA_API_KEY`, `TYPESAFE_API_KEY`, `OPENROUTER_API_KEY` | 키, 이 우선순위로 |
| `JEV_RA_ENDPOINT`, `JEV_RA_MODEL` | 경로 재정의. `sk-or-`로 시작하는 키는 OpenRouter를 고른다 |
| `JEV_RA_VIEWPORT` | 예: `1280x900` (기본값) |
| `JEV_RA_MAX_STEPS`, `JEV_RA_MAX_DECISIONS`, `JEV_RA_TIMEOUT_S` | 예산 (40 / 80 / 120) |
| `JEV_RA_TEXT_MODEL`, `JEV_RA_TEXT_BASE_URL`, `JEV_RA_TEXT_API_KEY` | 선택적 텍스트 헬퍼, 기본은 꺼짐 |
| `BU_CDP_URL` | 구동할 Chrome |

`$XDG_CONFIG_HOME/jev-ra/config.json`에 같은 키를 쓸 수 있고, 환경변수가 우선한다.

## 출처

`jev_ra/browser/snapshot.js`와 `NEXT_ACTION` / `TARGET` 지시문은
[browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)(MIT)에서 가져와 다듬은
것이며, 그곳에서 측정된 텍스트다. [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 보라.

MIT 라이선스. [English README](README.md).
