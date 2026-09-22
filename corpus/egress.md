# The seven sites that will not serve this network

Seven corpus tasks fail on every run for a reason no decision can change: the site answers this
IP with something other than the page. Their goals are possible and their specs are not bent to
match what the wall says, so they stay failures until the corpus runner is pointed somewhere else.

This file is what each site actually answered, and how to give the runner a different egress.

## What each site answered

Measured directly, one open per site, against a Chrome on a residential Korean connection.
`chars` is what the opened page said - what a reader can see, or the whole document when that is
longer - and `controls` is how many elements the snapshot could offer a decision.

| task | address | HTTP | landed on | chars | controls | what it said |
|---|---|---|---|---|---|---|
| `coupang_search` | `www.coupang.com` | 403 | same | 193 | 0 | `Access Denied` / `You don't have permission to access "http://www.coupang.com/" on this server.` / `Reference #18.` |
| `ja_rakuten_search` | `www.rakuten.co.jp` | 200 | same | 42 | 0 | `Reference #18.0ca3c117.1790048097.332eea0` and nothing else - an edge network's block page, served as a 200 |
| `reuters_open_section` | `www.reuters.com` | 401 | same | 0 | 1 | nothing at all: zero visible characters behind one opaque frame |
| `zh_taobao_search` | `www.taobao.com` | 200 | same | 1094 | 95 | `中国大陆` / `亲，请登录` - the page is served, and it is the logged-out shell asking to sign in before it will search |
| `zh_jd_search` | `www.jd.com` | 200 | `global.jd.com` | 907 | 55 | `京东首页` / `京东全球版` - redirected by geography to the global storefront, which carries no 搜索 for the goal |
| `gov_kr_search` | `www.gov.kr/portal/main/nologin` | redirect | `plus.gov.kr` | 1008 | 44 | `본문 바로가기` / `이 누리집은 대한민국 공식 전자정부 누리집입니다.` / `정부24` - the portal moved; this is not a wall |
| `ja_asahi_search` | `www.asahi.com` | 200 | same | 6000 | 44 | `高市政権` / `熊本地震` / `速報` - served in full at the time of writing; it refuses intermittently, not always |

Two of the seven are not egress at all, and saying so is the point of measuring:

- **`gov_kr_search` has moved.** `www.gov.kr/portal/main/nologin` now redirects to `plus.gov.kr`,
  which serves 1008 characters and 44 controls. Nothing is refusing anything. The task's address
  is stale and the task needs rewriting against the portal that exists, which is a corpus change
  and not one this lane was asked to make.
- **`ja_asahi_search` refuses only sometimes.** It served the whole front page here and failed
  1 of 3 runs in the previous lane's measurement. It belongs in this list as a site that
  sometimes answers a machine and sometimes does not, not as one that never does.

The other five are the real thing: two block pages that say so (coupang, rakuten), one that says
nothing (reuters), one login wall (taobao), and one geographic redirect that serves a storefront
the goal cannot be done on (jd).

## Pointing the runner at another egress

`JEV_RA_PROXY` is the egress a Chrome **jev-ra launches** is put behind. It is passed straight to
Chrome as `--proxy-server`, so it takes any value that flag takes - `host:port`,
`scheme://host:port`, a per-scheme list such as `http=proxy1:80;https=proxy2:80`, or `direct://`.

```sh
export JEV_RA_PROXY=http://user:password@residential.example:8080
uv run jev-ra corpus run --runs 3
```

It can also live in `~/.config/jev-ra/config.json` as `"proxy"`; the environment wins over the
file. A value that is blank, carries whitespace, or starts with a dash is refused with a warning
and the run goes out directly - a proxy has to be one argument, and something that would split
into two of them is a different flag being smuggled in. The value is never written to a log,
because a residential egress carries its credentials inside it.

**It only applies to a Chrome jev-ra starts.** A proxy is a launch argument, so a browser that was
already running was started without it. When `BU_CDP_URL` names a live Chrome and a proxy is
configured, the run says so at WARNING and goes out through whatever that browser already uses -
otherwise an egress would be measured that was never in the path. Unset `BU_CDP_URL`, or run
`jev-ra clean` first, so the corpus starts its own.

## What to expect from a different egress

These seven are reported as **walled, unchanged**: no spec was widened and no goal was rewritten
to match what a wall says. `coupang_search` expects `done` and gets `escalate:blocked_by_site`,
which is the agent correctly reporting that the site served a wall; changing the task to expect
the escalation would turn five failures into passes without anything having been fixed.

What a residential egress should change, if it changes anything: coupang, rakuten and reuters
either serve their pages or they do not, and the answer is one run away. `zh_jd_search` needs an
egress inside mainland China or it will keep landing on `global.jd.com`. `zh_taobao_search` will
still want an account. `gov_kr_search` will fail from anywhere until its address is fixed.
