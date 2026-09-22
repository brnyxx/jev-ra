// The first viewport: two agents get the same job at the same moment and the page plays the measured times back at 4x.
// Every duration below is a measured median (docs/BENCHMARKS.md, 2026-09-18, same machine, same
// Chrome, same OpenRouter key). browser-use's steps are spread evenly over its measured total; only
// the total is a measurement. Words come from hidden template nodes so i18n.js can translate them.
(function () {
  const TASKS = {
    wiki: { j: 2714, js: 2, b: 23058, bs: 4 },
    flights: { j: 8888, js: 11, b: 66414, bs: 11 },
    olive: { j: 3806, js: 2, b: 15071, bs: 3 },
  };
  const HOLD_MS = 5200;
  const $ = (s, r = document) => r.querySelector(s);
  const tpl = (id) => ($("#" + id) ? $("#" + id).textContent.trim() : "");
  const fmt = (ms) => (ms / 1000).toFixed(2);

  document.addEventListener("DOMContentLoaded", () => {
    const root = $("#race");
    if (!root) return;
    const J = $(".lane.jr", root), B = $(".lane.bu", root);
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let key = "wiki", speed = 4, t0 = performance.now(), paused = 0, raf = 0, shown = -1;

    const ticks = (lane, n) => {
      const box = $(".ticks", lane);
      box.innerHTML = "";
      for (let i = 0; i < n; i++) box.appendChild(document.createElement("i"));
    };
    const reset = () => {
      const k = TASKS[key];
      ticks(J, k.js); ticks(B, k.bs);
      root.dataset.task = key; root.classList.remove("over");
      J.classList.remove("won"); B.classList.remove("won");
      shown = -1; t0 = performance.now();
      $(".result", root).textContent = "";
    };
    const paint = (lane, progress, steps, time, state) => {
      $(".clock b", lane).textContent = fmt(time);
      $(".meter i", lane).style.transform = `scaleX(${Math.min(progress, 1)})`;
      const on = Math.min(steps, Math.floor(progress * steps + 1e-9));
      $(".ticks", lane).querySelectorAll("i").forEach((t, i) => t.classList.toggle("on", i < on));
      $(".state", lane).textContent = state;
    };
    const frame = (now) => {
      const k = TASKS[key];
      const t = Math.min((now - t0) * speed, k.b);
      const laps = Math.floor(t / k.j);
      const jDone = laps >= 1;
      const jt = jDone ? k.j : t;
      paint(J, jDone ? 1 : t / k.j, k.js, jt, jDone ? tpl("t-done") : tpl("t-running"));
      paint(B, t / k.b, k.bs, t, t >= k.b ? tpl("t-done") : tpl("t-running"));
      J.classList.toggle("won", jDone);
      if (laps !== shown) {
        shown = laps;
        const lap = $(".laps", J);
        lap.textContent = laps >= 1 ? "×" + laps : "";
        lap.classList.remove("pop"); void lap.offsetWidth; if (laps >= 1) lap.classList.add("pop");
      }
      if (t >= k.b) {
        if (!root.classList.contains("over")) {
          root.classList.add("over"); B.classList.add("won");
          $(".result", root).textContent = tpl("t-result").replace("{n}", Math.floor(k.b / k.j));
        }
        if ((now - t0) * speed - k.b > HOLD_MS * speed) reset();
      }
      raf = requestAnimationFrame(frame);
    };

    root.querySelectorAll("[data-task]").forEach((b) => b.addEventListener("click", () => {
      key = b.dataset.task;
      root.querySelectorAll("[data-task]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      reset();
    }));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { paused = performance.now(); cancelAnimationFrame(raf); }
      else if (paused) { t0 += performance.now() - paused; paused = 0; raf = requestAnimationFrame(frame); }
    });

    reset();
    // ?at=<ms> starts the race that far into the measured timeline, so a screenshot can show any moment of it.
    const at = Number(new URLSearchParams(location.search).get("at"));
    if (at > 0) t0 -= at / speed;
    if (still) {
      const k = TASKS[key];
      t0 = performance.now() - k.b;
      frame(performance.now());
      cancelAnimationFrame(raf);
      return;
    }
    raf = requestAnimationFrame(frame);
  });
})();
