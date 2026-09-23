// jev-ra landing demo: a recorded run (demo-run.json, the raw `jev-ra run --json` output) replayed as SVG.
// No video, no framework. Timings, clicked labels and typed values come from the run log; the page is drawn as vectors.
(function () {
  const host = document.getElementById("jev-demo");
  if (!host) return;
  const NS = "http://www.w3.org/2000/svg";
  const BROWSER_USE = { ms: 66414, steps: 11 };
  const SPEED = 8;
  const L = {
    en: { request: "find one-way flights from Zurich to London on Sep 20 and show me the list", running: "jev-ra is driving Chrome. Every step is one Jev decision.", step: "step", done: "done · goal_achieved · {steps} steps · {decisions} decisions · {s} s · ${cost}", summary: "One-way ZRH → LON on Sep 20, 21 results. Cheapest: easyJet 16:45 → 17:35, direct, ₩231,298. British Airways 07:40 → 08:35 direct, ₩246,696.", compareTitle: "same task · same Chrome · same key", compareNote: "browser-use 0.13 flash_mode with gemini-3-flash: 66.4 s, 11 steps. This jev-ra run: {s} s, {steps} steps. Both from the recorded logs in docs/benchmarks/.", speed: "playback " + SPEED + "x", realTime: "real time", steps: "steps", recorded: "Vector re-enactment of a recorded run (2026-09-18). Timings, clicks and typed values are taken from the run log; nothing is staged.", replay: "Replay" },
    ko: { request: "9월 20일 취리히에서 런던 가는 편도 항공편 찾아서 목록 보여줘", running: "jev-ra 가 Chrome 을 조작합니다. 스텝마다 Jev 결정 한 번입니다.", step: "스텝", done: "완료 · goal_achieved · {steps} 스텝 · {decisions} 결정 · {s} s · ${cost}", summary: "9월 20일 ZRH → LON 편도, 결과 21개. 최저가: 이지젯 16:45 → 17:35 직항 ₩231,298. 영국항공 07:40 → 08:35 직항 ₩246,696.", compareTitle: "같은 과제 · 같은 Chrome · 같은 키", compareNote: "browser-use 0.13 flash_mode + gemini-3-flash: 66.4 s, 11 스텝. 이 jev-ra 실행: {s} s, {steps} 스텝. 둘 다 docs/benchmarks/ 의 기록된 로그입니다.", speed: SPEED + "배속 재생", realTime: "실시간", steps: "스텝", recorded: "기록된 실행(2026-09-18)을 벡터로 재현한 것입니다. 시간·클릭·입력값은 실행 로그 그대로이며 연출은 없습니다.", replay: "다시 보기" },
    ja: { request: "9月20日のチューリッヒ発ロンドン行き片道便を探して一覧を見せて", running: "jev-ra が Chrome を操作します。各ステップは Jev の判断一回です。", step: "ステップ", done: "完了 · goal_achieved · {steps} ステップ · {decisions} 判断 · {s} s · ${cost}", summary: "9月20日 ZRH → LON 片道、21件。最安: easyJet 16:45 → 17:35 直行 ₩231,298。British Airways 07:40 → 08:35 直行 ₩246,696。", compareTitle: "同じタスク · 同じ Chrome · 同じキー", compareNote: "browser-use 0.13 flash_mode + gemini-3-flash: 66.4 s、11 ステップ。この jev-ra 実行: {s} s、{steps} ステップ。どちらも docs/benchmarks/ の記録ログです。", speed: SPEED + "倍速再生", realTime: "リアルタイム", steps: "ステップ", recorded: "記録された実行(2026-09-18)をベクターで再現したものです。時間・クリック・入力値は実行ログのままで、演出はありません。", replay: "もう一度" },
    "zh-CN": { request: "帮我找 9 月 20 日苏黎世飞伦敦的单程航班并显示列表", running: "jev-ra 正在操作 Chrome。每一步只有一次 Jev 决策。", step: "步骤", done: "完成 · goal_achieved · {steps} 步 · {decisions} 次决策 · {s} s · ${cost}", summary: "9 月 20 日 ZRH → LON 单程,共 21 条结果。最低价:easyJet 16:45 → 17:35 直飞 ₩231,298。英国航空 07:40 → 08:35 直飞 ₩246,696。", compareTitle: "同一任务 · 同一 Chrome · 同一密钥", compareNote: "browser-use 0.13 flash_mode + gemini-3-flash:66.4 s,11 步。本次 jev-ra 运行:{s} s,{steps} 步。均来自 docs/benchmarks/ 中记录的日志。", speed: SPEED + " 倍速播放", realTime: "实时", steps: "步", recorded: "以矢量方式重现一次已记录的运行(2026-09-18)。时间、点击和输入值均取自运行日志,没有任何摆拍。", replay: "重播" },
  };
  const TOOL = 'browser_run(goal="Search one-way flights from Zurich to London departing 2026-09-20 and show the list of results.", values={origin, destination, departure_date})';
  // Control geometry inside the 1040x640 page area, one entry per real step target.
  const CTRL = { 1: [36, 96, 118, 40], 2: [36, 176, 200, 40], 3: [36, 168, 330, 56], 4: [36, 232, 330, 48], 5: [400, 168, 330, 56], 6: [400, 232, 330, 48], 7: [764, 168, 240, 56], 8: [520, 372, 40, 40], 9: [700, 520, 120, 44], 10: [440, 268, 160, 52] };
  // The run was recorded on Google Flights in Korean; the page is redrawn the way Google shows it in each language,
  // and the step labels are the same controls named the way that page names them.
  const PRICES = ["₩231,298", "₩246,696", "₩317,373"];
  const G = {
    ko: { tabs: ["항공편", "호텔", "공유숙박"], trips: ["왕복", "편도", "다구간"], from: "출발지가 어디인가요?", to: "목적지가 어디인가요?", when: "출발", zrh: "취리히 공항 (ZRH)", lon: "영국 런던", search: "검색", month: "2026년 9월", week: ["일", "월", "화", "수", "목", "금", "토"], ok: "확인", date: "9월 20일 (일)", sorted: "인기 항공편순으로 정렬됨 · 결과 21개가 반환되었습니다.",
      rows: [["오후 4:45 – 오후 5:35", "이지젯", "1시간 50분 · 직항"], ["오전 7:40 – 오전 8:35", "영국항공", "1시간 55분 · 직항"], ["오후 6:20 – 오후 7:05", "영국항공", "1시간 45분 · 직항"]] },
    en: { tabs: ["Flights", "Hotels", "Vacation rentals"], trips: ["Round trip", "One way", "Multi-city"], from: "Where from?", to: "Where to?", when: "Departure", zrh: "Zurich Airport (ZRH)", lon: "London, UK", search: "Search", month: "September 2026", week: ["S", "M", "T", "W", "T", "F", "S"], ok: "Done", date: "Sun, Sep 20", sorted: "Sorted by top flights · 21 results returned.",
      rows: [["4:45 PM – 5:35 PM", "easyJet", "1 hr 50 min · Nonstop"], ["7:40 AM – 8:35 AM", "British Airways", "1 hr 55 min · Nonstop"], ["6:20 PM – 7:05 PM", "British Airways", "1 hr 45 min · Nonstop"]],
      labels: ["Change ticket type. Round trip", "One way", "Where from?", "Zurich Airport (ZRH)", "Where to?", "London, UK", "Open Departure", "Sunday, September 20, 2026", "Done. Search for one-way flights departing on September 20, 2026", "Search"] },
    ja: { tabs: ["フライト", "ホテル", "バケーションレンタル"], trips: ["往復", "片道", "周遊"], from: "出発地", to: "目的地", when: "出発日", zrh: "チューリッヒ空港 (ZRH)", lon: "イギリス ロンドン", search: "検索", month: "2026年9月", week: ["日", "月", "火", "水", "木", "金", "土"], ok: "完了", date: "9月20日(日)", sorted: "おすすめ順 · 21 件の結果",
      rows: [["16:45 – 17:35", "easyJet", "1 時間 50 分 · 直行便"], ["7:40 – 8:35", "British Airways", "1 時間 55 分 · 直行便"], ["18:20 – 19:05", "British Airways", "1 時間 45 分 · 直行便"]],
      labels: ["チケットの種類を変更します。往復", "片道", "出発地", "チューリッヒ空港 (ZRH)", "目的地", "イギリス ロンドン", "出発日を開く", "2026年9月20日日曜日", "完了。2026年9月20日出発の片道便を検索", "検索"] },
    "zh-CN": { tabs: ["机票", "酒店", "度假屋"], trips: ["往返", "单程", "多城市"], from: "从哪里出发?", to: "要去哪里?", when: "出发时间", zrh: "苏黎世机场 (ZRH)", lon: "英国伦敦", search: "搜索", month: "2026年9月", week: ["日", "一", "二", "三", "四", "五", "六"], ok: "完成", date: "9月20日周日", sorted: "按热门航班排序 · 共返回 21 条结果。",
      rows: [["下午4:45 – 下午5:35", "easyJet", "1小时50分钟 · 直达"], ["上午7:40 – 上午8:35", "英国航空", "1小时55分钟 · 直达"], ["下午6:20 – 下午7:05", "英国航空", "1小时45分钟 · 直达"]],
      labels: ["更改机票类型。往返", "单程", "从哪里出发?", "苏黎世机场 (ZRH)", "要去哪里?", "英国伦敦", "打开出发时间", "2026年9月20日星期日", "完成。搜索2026年9月20日出发的单程航班", "搜索"] },
  };
  // September 2026 starts on a Tuesday; the calendar starts its weeks on Sunday, so the 20th is a Sunday cell.
  const SEP1 = 2, DAY = (d) => { const i = d - 1 + SEP1; return [316 + (i % 7) * 46 + 20, 370 + Math.floor(i / 7) * 42 + 20]; };
  CTRL[8] = [DAY(20)[0] - 20, DAY(20)[1] - 20, 40, 40];
  const gp = () => G[locale] || G.en;
  const stepLabel = (st) => { const ls = gp().labels; return ls ? ls[st.n - 1] : clean(st.target_label); };
  const clean = (s) => String(s || "").replace(/\?{2,}/g, "").replace(/\s+/g, " ").trim();
  const fmt = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
  const el = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); if (parent) parent.appendChild(n); return n; };
  const txt = (parent, x, y, s, cls, attrs) => { const t = el("text", Object.assign({ x, y, class: cls || "" }, attrs || {}), parent); t.textContent = s; return t; };
  const wrap = (s, maxUnits) => { const lines = []; let cur = "", units = 0; for (const w of s.split(" ")) { const u = [...w].reduce((a, c) => a + (c.charCodeAt(0) > 0x2e80 ? 1.9 : 1), 0); if (units + u + 1 > maxUnits && cur) { lines.push(cur); cur = w; units = u; } else { cur = cur ? cur + " " + w : w; units += u + 1; } } if (cur) lines.push(cur); return lines; };
  // Lines are broken at the width the browser actually renders, not at a guessed character count:
  // Japanese and Chinese have no spaces to break at, so a CJK character is a break point of its own,
  // and closing punctuation never starts a line.
  const CJK = "\u2e80-\u2fff\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef";
  const TOKEN = new RegExp(`[${CJK}]|\\s+|[^\\s${CJK}]+`, "g");
  const NOSTART = /^[、。，．：；！？」』）〉》】・ー々,.:;!?)\]]/;
  const fit = (textEl, str, maxW) => {
    const probe = el("tspan", {}, textEl); const width = (v) => { probe.textContent = v; return probe.getComputedTextLength(); };
    const out = []; let cur = "";
    for (const tk of String(str).match(TOKEN) || []) {
      const next = cur + tk;
      if (cur.trim() && !NOSTART.test(tk) && width(next.trimEnd()) > maxW) { out.push(cur.trimEnd()); cur = tk.trimStart(); } else cur = next;
    }
    if (cur.trim()) out.push(cur.trimEnd());
    probe.remove(); return out;
  };
  const setLines = (textEl, x, str, maxW, lh) => { textEl.replaceChildren(); const ls = fit(textEl, str, maxW); ls.forEach((ln, i) => { const t = el("tspan", { x, dy: i ? lh : 0 }, textEl); t.textContent = ln; }); return ls.length; };
  const lines = (parent, x, y, s, cls, maxUnits, lh) => { const t = el("text", { x, y, class: cls }, parent); wrap(s, maxUnits).forEach((ln, i) => { const ts = el("tspan", { x, dy: i ? lh : 0 }, t); ts.textContent = ln; }); return t; };

  const TERM_W = 614;
  const norm = (h) => { h = (h || "en").toLowerCase(); return h.startsWith("ko") ? "ko" : h.startsWith("ja") ? "ja" : h.startsWith("zh") ? "zh-CN" : "en"; };
  let run, timed, elapsed, T, locale = norm(document.documentElement.lang), t0 = 0, raf = 0, S = {};
  const now = () => performance.now();

  function schedule() {
    let acc = 0; for (const s of run.steps) acc += s.total_ms;
    elapsed = run.elapsed_ms; const load = elapsed - acc; let cursor = load;
    timed = run.steps.map((s) => { const startMs = cursor, decidedMs = startMs + s.snapshot_ms + s.decide_ms; cursor = startMs + s.total_ms; return Object.assign({}, s, { startMs, decidedMs, actedMs: decidedMs + s.act_ms, endMs: cursor }); });
    T = { typing: 400, tool: 2600, browserIn: 3000, runStart: 4200 };
    T.runEnd = T.runStart + elapsed; T.done = T.runEnd + 400; T.summary = T.runEnd + 1200; T.compare = T.runEnd + 4000; T.compareLen = 9500; T.outro = T.compare + T.compareLen; T.total = T.outro + 3200;
  }

  function build() {
    host.innerHTML = "";
    const svg = el("svg", { viewBox: "0 0 1920 1080", class: "jd", role: "img", "aria-label": "jev-ra demo: a recorded Google Flights run replayed" }, host);
    const style = el("style", {}, svg);
    style.textContent = `
      .jd{font-family:ui-sans-serif,-apple-system,"Geist","Inter","Apple SD Gothic Neo","Noto Sans CJK KR","Hiragino Sans","PingFang SC",Arial,sans-serif;display:block;width:100%;height:auto;background:#070A0F}
      .jd .m{font-family:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,"Apple SD Gothic Neo","Noto Sans CJK KR",monospace}
      .jd .paper{fill:#F6F4EF}.jd .amber{fill:#FFB703}.jd .cyan{fill:#3DE8FF}.jd .muted{fill:#AEB6C2}.jd .dim{fill:#6B7482}.jd .green{fill:#5BE49B}.jd .ink{fill:#070A0F}
      .jd .g-text{fill:#e8eaed}.jd .g-sub{fill:#9aa0a6}
      .jd .fade{transition:opacity .35s}.jd .hid{opacity:0}
      .jd #browser{transition:transform .6s cubic-bezier(.2,.7,.2,1),opacity .6s}
      .jd #cursor{transition:transform .32s cubic-bezier(.2,.7,.2,1)}
      .jd .ripple{fill:none;stroke:#FFB703;stroke-width:3;opacity:0}
      .jd .ripple.go{animation:jd-ripple .5s ease-out forwards}
      @keyframes jd-ripple{0%{opacity:1;transform:scale(.3)}100%{opacity:0;transform:scale(1.6)}}
      .jd .focus{stroke:#FFB703;stroke-width:3}
      .jd .caret{animation:jd-blink 1s steps(1) infinite}
      @keyframes jd-blink{50%{opacity:0}}
      @media (prefers-reduced-motion:reduce){.jd *{animation:none!important;transition:none!important}}`;
    const defs = el("defs", {}, svg);
    const grad = el("radialGradient", { id: "jd-glow", cx: "78%", cy: "10%", r: "60%" }, defs);
    el("stop", { offset: "0", "stop-color": "#FFB703", "stop-opacity": ".16" }, grad); el("stop", { offset: "1", "stop-color": "#FFB703", "stop-opacity": "0" }, grad);
    const pat = el("pattern", { id: "jd-grid", width: 64, height: 64, patternUnits: "userSpaceOnUse" }, defs);
    el("path", { d: "M64 0H0V64", fill: "none", stroke: "rgba(246,244,239,.05)" }, pat);
    el("rect", { width: 1920, height: 1080, fill: "#070A0F" }, svg);
    el("rect", { width: 1920, height: 1080, fill: "url(#jd-grid)" }, svg);
    el("rect", { width: 1920, height: 1080, fill: "url(#jd-glow)" }, svg);

    // session scene
    const sess = el("g", { id: "session", class: "fade" }, svg); S.session = sess;
    el("image", { href: "assets/mark-dark-512.png", x: 140, y: 40, width: 44, height: 44 }, sess);
    const brand = txt(sess, 200, 74, "", "paper", { "font-size": 30, "font-weight": 800, "letter-spacing": -1 });
    brand.innerHTML = 'jev<tspan class="amber">-</tspan>ra';
    txt(sess, 340, 72, "DEMO · GOOGLE FLIGHTS · 2026-09-18", "m cyan", { "font-size": 18, "letter-spacing": 3 });
    S.recorded = lines(sess, 140, 1010, "", "dim", 150, 24); S.recorded.setAttribute("font-size", 19);

    // terminal
    const term = el("g", { id: "term", transform: "translate(140 140)" }, sess);
    el("rect", { width: 640, height: 760, rx: 10, fill: "rgba(4,7,11,.92)", stroke: "rgba(246,244,239,.14)" }, term);
    txt(term, 26, 44, "claude · ~/work", "m dim", { "font-size": 15 });
    const prompt = el("text", { x: 26, y: 82, class: "m paper", "font-size": 19 }, term); S.promptText = prompt;
    S.promptArrow = el("tspan", { class: "amber" }, prompt); S.promptArrow.textContent = "❯ ";
    S.promptMeasure = el("text", { x: 0, y: 0, class: "m", "font-size": 19, visibility: "hidden" }, term);
    S.promptSpans = []; S.caret = el("tspan", { class: "caret" }, prompt); S.caret.textContent = "▍";
    S.tool = el("g", { class: "fade hid" }, term);
    const tl = el("text", { x: 26, y: 150, class: "m", "font-size": 19 }, S.tool);
    const dot = el("tspan", { class: "green" }, tl); dot.textContent = "⏺ "; const nm = el("tspan", { class: "paper" }, tl); nm.textContent = "jev-ra"; const mc = el("tspan", { class: "dim" }, tl); mc.textContent = " · MCP";
    lines(S.tool, 26, 178, TOOL, "m muted", 66, 21).setAttribute("font-size", 15);
    S.open = txt(S.tool, 26, 264, "open https://www.google.com/travel/flights", "m dim hid fade", { "font-size": 15 });
    S.log = el("g", {}, S.tool);
    S.doneLine = lines(S.tool, 26, 0, "", "m green fade hid", 62, 21); S.doneLine.setAttribute("font-size", 15);
    S.summaryBar = el("rect", { x: 26, y: 0, width: 3, height: 0, fill: "#FFB703", class: "fade hid" }, S.tool);
    S.summary = lines(S.tool, 42, 0, "", "paper fade hid", 66, 26); S.summary.setAttribute("font-size", 17);
    S.running = txt(term, 26, 738, "", "m dim", { "font-size": 14 });

    // browser
    const brOuter = el("g", { transform: "translate(820 140)" }, sess); const br = el("g", { id: "browser", class: "hid" }, brOuter); S.browser = br;
    el("rect", { width: 1080, height: 760, rx: 10, fill: "#202124", stroke: "rgba(246,244,239,.16)" }, br);
    el("path", { d: "M10 0h1060a10 10 0 0 1 10 10v46H0V10A10 10 0 0 1 10 0z", fill: "#2b2c2f" }, br);
    [16, 40, 64].forEach((x) => el("circle", { cx: x + 6, cy: 28, r: 6, fill: "#FFB703" }, br));
    el("rect", { x: 100, y: 11, width: 820, height: 34, rx: 17, fill: "#1f2023" }, br);
    S.url = txt(br, 116, 33, "google.com/travel/flights", "m g-sub", { "font-size": 16 });
    S.timer = txt(br, 1060, 34, "0.00 s", "m paper", { "font-size": 18, "text-anchor": "end" });
    const page = el("g", { transform: "translate(20 76)" }, br); S.page = page;
    S.loading = el("g", {}, page);
    el("rect", { x: 40, y: 40, width: 240, height: 22, rx: 6, fill: "#303134" }, S.loading); el("rect", { x: 40, y: 86, width: 960, height: 120, rx: 12, fill: "#303134", opacity: .6 }, S.loading); el("rect", { x: 40, y: 230, width: 700, height: 22, rx: 6, fill: "#303134", opacity: .4 }, S.loading);
    const pg = el("g", { class: "fade hid" }, page); S.pg = pg;
    S.gTabs = [txt(pg, 16, 34, "", "g-text", { "font-size": 16, "font-weight": 600 }), txt(pg, 0, 34, "", "g-sub", { "font-size": 16 }), txt(pg, 0, 34, "", "g-sub", { "font-size": 16 })];
    el("rect", { y: 80, width: 1040, height: 260, rx: 14, fill: "#303134" }, pg);
    const rect = (r, extra) => el("rect", Object.assign({ x: r[0], y: r[1], width: r[2], height: r[3], rx: 8, fill: "none", stroke: "#5f6368" }, extra || {}), pg);
    S.chipBox = rect(CTRL[1], { stroke: "none" }); S.chip = txt(pg, CTRL[1][0] + 12, CTRL[1][1] + 26, "", "g-text", { "font-size": 17 });
    S.menu = el("g", { class: "fade hid" }, pg);
    el("rect", { x: 36, y: 140, width: 200, height: 122, rx: 8, fill: "#3c4043" }, S.menu); S.menuHi = el("rect", { x: 36, y: 176, width: 200, height: 40, fill: "rgba(138,180,248,.18)", class: "fade hid" }, S.menu);
    S.gTrips = [0, 1, 2].map((i) => txt(S.menu, 52, 166 + i * 40, "", "g-text", { "font-size": 17 }));
    const field = (r, ph) => { const box = rect(r); const t = txt(pg, r[0] + 16, r[1] + r[3] / 2 + 7, ph, "g-sub", { "font-size": 18 }); return { box, t, ph }; };
    S.origin = field(CTRL[3], ""); S.dest = field(CTRL[5], ""); S.date = field(CTRL[7], "");
    const sug = (r, s) => { const g = el("g", { class: "fade hid" }, pg); const b = el("rect", { x: r[0], y: r[1], width: r[2], height: r[3], rx: 8, fill: "#3c4043" }, g); const t = txt(g, r[0] + 16, r[1] + 31, s, "g-text", { "font-size": 17 }); return { g, b, t }; };
    S.sugO = sug(CTRL[4], ""); S.sugD = sug(CTRL[6], "");
    S.search = el("rect", { x: CTRL[10][0], y: CTRL[10][1], width: CTRL[10][2], height: CTRL[10][3], rx: 26, fill: "#8ab4f8" }, pg);
    S.gSearch = txt(pg, CTRL[10][0] + 80, CTRL[10][1] + 33, "", "", { "font-size": 19, "font-weight": 700, "text-anchor": "middle", fill: "#202124" });
    S.cal = el("g", { class: "fade hid" }, pg);
    el("rect", { x: 300, y: 300, width: 540, height: 290, rx: 12, fill: "#3c4043" }, S.cal); S.gMonth = txt(S.cal, 316, 328, "", "g-text", { "font-size": 16 }); S.gWeek = [0, 1, 2, 3, 4, 5, 6].map((c) => txt(S.cal, 336 + c * 46, 356, "", "g-sub", { "font-size": 13, "text-anchor": "middle" }));
    for (let d = 1; d <= 30; d++) { const [cx, cy] = DAY(d); if (d === 20) S.day20 = el("circle", { cx, cy, r: 20, fill: "none" }, S.cal); txt(S.cal, cx, cy + 5, String(d), d === 20 ? "" : "g-text", { "font-size": 15, "text-anchor": "middle", id: d === 20 ? "jd-d20" : null }); }
    S.d20 = S.cal.querySelector("#jd-d20"); S.d20.setAttribute("fill", "#e8eaed");
    S.confirm = el("rect", { x: 700, y: 520, width: 120, height: 44, rx: 22, fill: "#8ab4f8" }, S.cal); S.gOk = txt(S.cal, 760, 548, "", "", { "font-size": 17, "font-weight": 700, "text-anchor": "middle", fill: "#202124" });
    S.placeholder = el("rect", { y: 380, width: 1040, height: 200, rx: 14, fill: "rgba(48,49,52,.5)", class: "fade" }, pg);
    S.results = el("g", { class: "fade hid" }, pg);
    S.gSorted = txt(S.results, 0, 376, "", "g-sub", { "font-size": 15 });
    S.gRows = PRICES.map((price, i) => { const y = 392 + i * 66; el("rect", { y, width: 1040, height: 58, rx: 10, fill: "#303134" }, S.results); const cells = [txt(S.results, 18, y + 36, "", "g-text", { "font-size": 17 }), txt(S.results, 278, y + 36, "", "g-sub", { "font-size": 17 }), txt(S.results, 470, y + 36, "", "g-sub", { "font-size": 17 })]; txt(S.results, 1022, y + 36, price, "g-text", { "font-size": 17, "font-weight": 700, "text-anchor": "end" }); return cells; });
    S.chipLabel = el("g", { class: "fade hid" }, page); S.chipBg = el("rect", { height: 24, rx: 4, fill: "#FFB703" }, S.chipLabel); S.chipTxt = txt(S.chipLabel, 0, 0, "", "m ink", { "font-size": 14 });
    S.cursor = el("g", { id: "cursor", class: "fade hid" }, page);
    S.ripple = el("circle", { r: 24, class: "ripple", cx: 6, cy: 8 }, S.cursor);
    el("path", { d: "M3 2l16 12-7 1.5L15.5 25 11 24.5 8.5 16 3 20z", fill: "#F6F4EF", stroke: "#111", "stroke-width": 1.4, transform: "scale(1.25)" }, S.cursor);
    S.foot = txt(br, 20, 744, "", "m dim", { "font-size": 14 });

    // compare scene
    const cmp = el("g", { id: "compare", class: "fade hid" }, svg); S.compare = cmp;
    S.cmpTitle = txt(cmp, 140, 150, "", "m cyan", { "font-size": 22, "letter-spacing": 4, "text-transform": "uppercase" });
    txt(cmp, 140, 230, "Google Flights · ZRH → LON · 2026-09-20", "paper", { "font-size": 70, "font-weight": 800, "letter-spacing": -2.5 });
    S.speed = txt(cmp, 1780, 150, "", "m paper", { "font-size": 22, "text-anchor": "end" });
    const bar = (y, label, color) => { txt(cmp, 140, y + 30, label, label === "jev-ra" ? "paper" : "muted", { "font-size": 30, "font-weight": label === "jev-ra" ? 800 : 500 }); const sub = txt(cmp, 140, y + 56, "", "m dim", { "font-size": 18 }); el("rect", { x: 460, y, width: 1040, height: 44, rx: 6, fill: "rgba(4,7,11,.75)", stroke: "rgba(246,244,239,.14)" }, cmp); const fill = el("rect", { x: 460, y, width: 0, height: 44, rx: 6, fill: color }, cmp); const val = txt(cmp, 1540, y + 34, "", "m dim", { "font-size": 34, "font-weight": 700 }); return { sub, fill, val }; };
    S.bu = bar(300, "browser-use", "#3a4250"); S.jr = bar(390, "jev-ra", "#FFB703");
    S.ratio = txt(cmp, 140, 600, "", "m amber fade hid", { "font-size": 96, "font-weight": 700 });
    S.cmpNote = lines(cmp, 140, 960, "", "muted", 150, 30); S.cmpNote.setAttribute("font-size", 22);

    // outro
    const out = el("g", { id: "outro", class: "fade hid" }, svg); S.outro = out;
    el("image", { href: "assets/mark-dark-512.png", x: 810, y: 200, width: 300, height: 300 }, out);
    const w = txt(out, 960, 620, "", "paper", { "font-size": 96, "font-weight": 800, "letter-spacing": -5, "text-anchor": "middle" }); w.innerHTML = 'jev<tspan class="amber">-</tspan>ra';
    el("rect", { x: 610, y: 660, width: 700, height: 84, rx: 8, fill: "#FFB703" }, out);
    txt(out, 960, 714, "$ uvx jev-ra install claude", "m ink", { "font-size": 40, "font-weight": 700, "text-anchor": "middle" });
    const gh = txt(out, 960, 800, "", "m muted", { "font-size": 26, "text-anchor": "middle" }); gh.innerHTML = 'github.com/<tspan class="amber">brnyxx/jev-ra</tspan>';

    const tools = document.createElement("div"); tools.className = "demo-tools"; host.parentElement.insertBefore(tools, host);
    S.replay = document.createElement("button"); S.replay.className = "replay"; tools.appendChild(S.replay); S.replay.addEventListener("click", restart);
    applyLocale();
    // Line breaks are measured, so they are measured again once the real font has arrived.
    if (document.fonts) document.fonts.ready.then(applyLocale);
  }

  function applyLocale() {
    const s = L[locale] || L.en; const v = { steps: run.steps.length, decisions: run.decisions, s: (elapsed / 1000).toFixed(1), cost: run.cost.toFixed(4) };
    const g = gp();
    let tx = 16; S.gTabs.forEach((t, i) => { t.textContent = g.tabs[i]; t.setAttribute("x", tx); tx += t.getComputedTextLength() + 34; });
    S.gTrips.forEach((t, i) => { t.textContent = g.trips[i]; }); S.gWeek.forEach((t, i) => { t.textContent = g.week[i]; });
    S.origin.ph = g.from; S.dest.ph = g.to; S.date.ph = g.when; S.sugO.t.textContent = g.zrh; S.sugD.t.textContent = g.lon;
    S.gSearch.textContent = "⌕ " + g.search; S.gMonth.textContent = g.month; S.gOk.textContent = g.ok; S.gSorted.textContent = g.sorted;
    S.gRows.forEach((cells, i) => cells.forEach((t, j) => { t.textContent = g.rows[i][j]; }));
    setLines(S.recorded, 140, s.recorded, 1640, 24);
    setLines(S.doneLine, 26, fmt(s.done, v), TERM_W - 26, 21);
    setLines(S.summary, 42, s.summary, TERM_W - 42, 26);
    const rn = setLines(S.running, 26, s.running, TERM_W - 26, 18); S.running.setAttribute("y", 738 - (rn - 1) * 18);
    S.promptLines = fit(S.promptMeasure, s.request, TERM_W - 26 - S.promptArrow.getComputedTextLength());
    S.promptSpans.forEach((t) => t.remove()); S.promptSpans = S.promptLines.map(() => el("tspan", {}, S.promptText)); S.promptText.appendChild(S.caret);
    S.cmpTitle.textContent = s.compareTitle; S.speed.textContent = s.speed; S.bu.sub.textContent = BROWSER_USE.steps + " " + s.steps; S.jr.sub.textContent = run.steps.length + " " + s.steps;
    setLines(S.cmpNote, 140, fmt(s.compareNote, v), 1640, 30);
    S.replay.textContent = "↻ " + s.replay;
  }

  const show = (n, on) => n.classList.toggle("hid", !on);
  let logged = 0, rippled = -1;
  function reset() { logged = 0; rippled = -1; S.log.replaceChildren(); S.promptSpans.forEach((t) => { t.textContent = ""; }); show(S.tool, false); show(S.open, false); show(S.doneLine, false); show(S.summary, false); show(S.summaryBar, false); show(S.browser, false); S.browser.style.transform = "translate(60px,0)"; show(S.pg, false); show(S.loading, true); show(S.menu, false); show(S.menuHi, false); show(S.sugO.g, false); show(S.sugD.g, false); show(S.cal, false); show(S.results, false); show(S.placeholder, true); show(S.cursor, false); show(S.chipLabel, false); show(S.compare, false); show(S.outro, false); show(S.session, true); show(S.ratio, false); S.url.textContent = "google.com/travel/flights"; S.chip.textContent = gp().trips[0] + " ▾"; [S.origin, S.dest, S.date].forEach((f) => { f.t.textContent = f.ph; f.t.setAttribute("class", "g-sub"); f.box.classList.remove("focus"); }); S.day20.setAttribute("fill", "none"); S.d20.setAttribute("fill", "#e8eaed"); S.search.classList.remove("focus"); S.confirm.classList.remove("focus"); S.chipBox.classList.remove("focus"); S.sugO.b.classList.remove("focus"); S.sugD.b.classList.remove("focus"); S.bu.fill.setAttribute("width", 0); S.jr.fill.setAttribute("width", 0); }

  function frame() {
    const t = now() - t0; const s = L[locale] || L.en;
    if (t >= T.total) { restart(); return; }
    // terminal
    let typedN = Math.max(0, Math.floor(((t - T.typing) / 1000) * 30));
    const indent = 26 + S.promptArrow.getComputedTextLength();
    S.promptLines.forEach((ln, i) => {
      const part = ln.slice(0, Math.max(0, typedN)); typedN -= ln.length; const span = S.promptSpans[i];
      if (span.textContent === part) return;
      span.textContent = part;
      if (i && part) { span.setAttribute("x", indent); span.setAttribute("dy", 26); } else { span.removeAttribute("x"); span.removeAttribute("dy"); }
    });
    show(S.tool, t >= T.tool); show(S.open, t >= T.runStart);
    if (t >= T.browserIn) { show(S.browser, true); S.browser.style.transform = "translate(0,0)"; }
    const ms = t - T.runStart;
    show(S.running, ms >= 0 && ms < elapsed);
    S.foot.textContent = s.realTime + " · Chrome 1280×900";
    if (ms >= 0) {
      S.timer.textContent = (Math.min(elapsed, ms) / 1000).toFixed(2) + " s"; S.timer.setAttribute("class", ms >= elapsed ? "m amber" : "m paper");
      const cur = timed.find((x) => ms >= x.startMs && ms < x.endMs) || null;
      const has = (n) => ms >= timed[n - 1].actedMs;
      const loading = ms < timed[0].startMs; show(S.loading, loading); show(S.pg, !loading); show(S.cursor, !loading);
      while (logged < timed.length && ms >= timed[logged].decidedMs) {
        const st = timed[logged]; const y = 300 + logged * 22; const line = el("text", { x: 26, y, class: "m muted", "font-size": 15 }, S.log);
        const a = el("tspan", { class: "dim" }, line); a.textContent = "⎿ "; const b = el("tspan", { class: "paper" }, line); b.textContent = s.step + " " + st.n; const c = el("tspan", {}, line); c.textContent = " · "; const d = el("tspan", { class: "amber" }, line); d.textContent = st.operation; const e = el("tspan", {}, line); e.textContent = ' "' + stepLabel(st).slice(0, 24) + '"'; if (st.text) { const f = el("tspan", {}, line); f.textContent = " ← "; const g = el("tspan", { class: "cyan" }, line); g.textContent = st.text; } const h = el("tspan", {}, line); h.textContent = " · " + st.latency_ms + " ms";
        for (let keep = 23; keep > 3 && line.getComputedTextLength() > TERM_W - 26; keep -= 2) e.textContent = ' "' + stepLabel(st).slice(0, keep) + '…"';
        logged++;
        while (S.log.children.length > 7) S.log.removeChild(S.log.firstChild); [...S.log.children].forEach((c2, i) => c2.setAttribute("y", 300 + i * 22));
      }
      const typed = (n, text) => { const st = timed[n - 1]; if (ms < st.decidedMs) return ""; return text.slice(0, Math.min(text.length, Math.floor(((ms - st.decidedMs) / st.act_ms) * text.length) + 1)); };
      S.chip.textContent = gp().trips[has(2) ? 1 : 0] + " ▾"; S.chipBox.classList.toggle("focus", cur && cur.n === 1);
      show(S.menu, has(1) && !has(2)); show(S.menuHi, cur && cur.n === 2);
      const setField = (f, val, active) => { f.t.textContent = val || f.ph; f.t.setAttribute("class", val ? "g-text" : "g-sub"); f.box.classList.toggle("focus", !!active); };
      const origin = has(4) ? gp().zrh : typed(3, "Zurich"); const dest = has(6) ? gp().lon : typed(5, "London");
      setField(S.origin, origin, cur && cur.n === 3); setField(S.dest, dest, cur && cur.n === 5); setField(S.date, has(9) ? gp().date : "", cur && cur.n === 7);
      show(S.sugO.g, cur && (cur.n === 3 || cur.n === 4) && origin.length > 0); S.sugO.b.classList.toggle("focus", cur && cur.n === 4);
      show(S.sugD.g, cur && (cur.n === 5 || cur.n === 6) && dest.length > 0); S.sugD.b.classList.toggle("focus", cur && cur.n === 6);
      const calOpen = has(7) && !has(9); show(S.cal, calOpen); show(S.placeholder, !calOpen && !(ms >= timed[9].actedMs + 450));
      const pick = has(8) || (cur && cur.n === 8); S.day20.setAttribute("fill", pick ? "#8ab4f8" : "none"); S.d20.setAttribute("fill", pick ? "#202124" : "#e8eaed"); S.day20.classList.toggle("focus", cur && cur.n === 8); S.confirm.classList.toggle("focus", cur && cur.n === 9); S.search.classList.toggle("focus", cur && cur.n === 10);
      const results = ms >= timed[9].actedMs + 450; show(S.results, results); S.url.textContent = results ? "google.com/travel/flights/search?tfs=CBwQAhojEgoyMDI2LTA5LTIw…" : "google.com/travel/flights";
      if (cur) { const r = CTRL[cur.n]; S.cursor.style.transform = `translate(${r[0] + r[2] * 0.55}px,${r[1] + r[3] * 0.55}px)`; show(S.chipLabel, ms >= cur.startMs + cur.snapshot_ms); const label = "[" + cur.target + "] " + stepLabel(cur).slice(0, 30); S.chipTxt.textContent = label; const w = S.chipTxt.getComputedTextLength() + 16; S.chipBg.setAttribute("width", w); S.chipLabel.setAttribute("transform", `translate(${r[0] + r[2] + 12} ${r[1] + r[3] / 2 - 12})`); S.chipTxt.setAttribute("x", 8); S.chipTxt.setAttribute("y", 17);
        if (cur.operation === "CLICK" && ms >= cur.decidedMs && rippled !== cur.n) { rippled = cur.n; S.ripple.classList.remove("go"); void S.ripple.getBBox(); S.ripple.classList.add("go"); }
      } else if (!loading) { show(S.chipLabel, false); S.cursor.style.transform = "translate(560px,420px)"; }
      show(S.doneLine, t >= T.done); if (t >= T.done) { const y = 300 + Math.min(logged, 7) * 22 + 10; S.doneLine.setAttribute("y", y); [...S.doneLine.children].forEach((c2, i) => c2.setAttribute("y", y + i * 21)); const sy = y + 46; S.summaryBar.setAttribute("y", sy - 18); S.summaryBar.setAttribute("height", S.summary.children.length * 26 + 8); S.summary.setAttribute("y", sy); [...S.summary.children].forEach((c2, i) => c2.setAttribute("y", sy + i * 26)); }
      show(S.summary, t >= T.summary); show(S.summaryBar, t >= T.summary);
    }
    // compare
    if (t >= T.compare - 350) show(S.session, false);
    if (t >= T.compare && t < T.outro) { show(S.compare, true); const clock = Math.max(0, (t - T.compare - 800) * SPEED); const upd = (b, msTotal) => { const shown = Math.min(msTotal, clock); b.fill.setAttribute("width", (shown / BROWSER_USE.ms) * 1040); b.val.textContent = (shown / 1000).toFixed(1) + " s" + (clock >= msTotal ? "" : " …"); b.val.setAttribute("class", clock >= msTotal ? (b === S.jr ? "m amber" : "m paper") : "m dim"); }; upd(S.bu, BROWSER_USE.ms); upd(S.jr, elapsed); S.ratio.textContent = (BROWSER_USE.ms / elapsed).toFixed(1) + "x"; show(S.ratio, clock >= BROWSER_USE.ms); }
    if (t >= T.outro) { show(S.compare, false); show(S.outro, true); }
    raf = requestAnimationFrame(frame);
  }
  function restart() { cancelAnimationFrame(raf); reset(); t0 = now(); raf = requestAnimationFrame(frame); }
  function setLocale(next) { if (!L[next]) return; locale = next; applyLocale(); restart(); }
  window.addEventListener("jevra-locale", (e) => setLocale(e.detail));
  fetch(new URL("demo-run.json", document.currentScript.src)).then((r) => r.json()).then((j) => { run = j; schedule(); build(); restart(); document.addEventListener("visibilitychange", () => { if (document.hidden) cancelAnimationFrame(raf); else restart(); }); });
})();
