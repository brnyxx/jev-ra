// The strike that opens every race: a bolt from the headline onto the top edge of jev-ra's lane.
// race.js owns the timing and starts the clocks when this lands; this file only draws.
(function () {
  const root = document.getElementById("race");
  if (!root || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const NS = "http://www.w3.org/2000/svg";
  const DRAW_MS = 190, HOLD_MS = 90, FADE_MS = 420;
  const el = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); parent.appendChild(n); return n; };

  // A jagged path between two points: each joint is pushed sideways, less so near the ends.
  const jag = (x1, y1, x2, y2, joints, spread) => {
    const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1, nx = -dy / len, ny = dx / len;
    const pts = [[x1, y1]];
    for (let i = 1; i < joints; i++) {
      const f = i / joints, off = (Math.random() * 2 - 1) * spread * Math.sin(Math.PI * f);
      pts.push([x1 + dx * f + nx * off, y1 + dy * f + ny * off]);
    }
    pts.push([x2, y2]);
    return pts;
  };
  const d = (pts) => "M" + pts.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L");

  const strike = (lane) => {
    // It falls from the top of the hero, behind the words, straight onto the top edge of the lane.
    const box = root.getBoundingClientRect();
    const hit = lane.getBoundingClientRect();
    const x2 = hit.left + hit.width * 0.5 - box.left, y2 = hit.top - box.top + 1;
    const x1 = x2 + (Math.random() * 2 - 1) * hit.width * 0.18, y1 = -40;
    const svg = el("svg", { class: "bolt", "aria-hidden": "true" }, root);
    const defs = el("defs", {}, svg);
    const blur = el("filter", { id: "bolt-glow", x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs);
    el("feGaussianBlur", { stdDeviation: "7" }, blur);
    const main = jag(x1, y1, x2, y2, 18, 34);
    const forks = [5, 9, 13].map((i) => {
      const [bx, by] = main[i], side = Math.random() < 0.5 ? -1 : 1;
      return jag(bx, by, bx + side * (50 + Math.random() * 90), by + 50 + Math.random() * 80, 5, 12);
    });
    const paths = [];
    for (const pts of [main, ...forks]) {
      const w = pts === main ? 1 : 0.55;
      paths.push(el("path", { d: d(pts), fill: "none", stroke: "#FFB703", "stroke-width": 12 * w, "stroke-linecap": "round", "stroke-linejoin": "round", filter: "url(#bolt-glow)", opacity: 0.85 }, svg));
      paths.push(el("path", { d: d(pts), fill: "none", stroke: "#FFD466", "stroke-width": 4.5 * w, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg));
      paths.push(el("path", { d: d(pts), fill: "none", stroke: "#FFFFFF", "stroke-width": 1.8 * w, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg));
    }
    // The flash lights the whole window, not just the hero's column, so it has no edges to show.
    const sky = document.createElement("div");
    sky.className = "bolt-sky";
    sky.style.background = `radial-gradient(90vmax 70vmax at ${hit.left + hit.width / 2}px ${hit.top}px, rgba(255,212,102,.34), rgba(255,183,3,.1) 38%, transparent 70%)`;
    document.body.appendChild(sky);
    const flash = el("ellipse", { cx: x2, cy: y2, rx: 10, ry: 4, fill: "#FFF4CF", filter: "url(#bolt-glow)", opacity: 0 }, svg);
    for (const p of paths) {
      const L = p.getTotalLength();
      p.style.strokeDasharray = L; p.style.strokeDashoffset = L;
      p.animate([{ strokeDashoffset: L }, { strokeDashoffset: 0 }], { duration: DRAW_MS, easing: "cubic-bezier(.7,0,.9,.6)", fill: "forwards" });
    }
    flash.animate([{ opacity: 0, rx: 10, ry: 4 }, { opacity: 1, rx: 120, ry: 16, offset: 0.2 }, { opacity: 0, rx: 260, ry: 26 }], { duration: 560, delay: DRAW_MS - 20, easing: "ease-out", fill: "forwards" });
    sky.animate([{ opacity: 0 }, { opacity: 1, offset: 0.12 }, { opacity: 0 }], { duration: 650, delay: DRAW_MS - 30, easing: "ease-out", fill: "forwards" }).finished.then(() => sky.remove());
    svg.animate([{ opacity: 1 }, { opacity: 1, offset: (DRAW_MS + HOLD_MS) / (DRAW_MS + HOLD_MS + FADE_MS) }, { opacity: 0 }], { duration: DRAW_MS + HOLD_MS + FADE_MS, fill: "forwards" }).finished.then(() => svg.remove());
    setTimeout(() => { lane.classList.remove("struck"); void lane.offsetWidth; lane.classList.add("struck"); }, DRAW_MS - 20);
  };

  root.addEventListener("race:start", (e) => { if (!document.hidden) strike(e.detail.lane); });
})();
