// The opening of every race: a laser traces once around jev-ra's card and, as it closes the loop,
// the card lights and its meter fires. race.js owns the timing and starts the clocks when the loop
// closes; this file only draws.
(function () {
  const root = document.getElementById("race");
  if (!root || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const NS = "http://www.w3.org/2000/svg";
  const LAP_MS = 520;
  const el = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); parent.appendChild(n); return n; };

  // A comet: a short bright head and two longer, fainter tails, all travelling the same border.
  const LAYERS = [
    { len: 0.3, width: 12, color: "#FFB703", opacity: 0.55, blur: true },
    { len: 0.2, width: 3, color: "#FFB703", opacity: 0.95 },
    { len: 0.07, width: 2.4, color: "#FFF4CF", opacity: 1 },
    { len: 0.02, width: 8, color: "#FFFFFF", opacity: 0.9, blur: true },
  ];

  const trace = (lane) => {
    // Drawn beside the card rather than inside it: the card clips its overflow, and the glow is outside.
    const host = lane.parentElement;
    host.querySelector(":scope > .trace")?.remove();
    const w = lane.offsetWidth, h = lane.offsetHeight;
    const r = parseFloat(getComputedStyle(lane).borderTopLeftRadius) || 0;
    const svg = el("svg", { class: "trace", viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" }, host);
    Object.assign(svg.style, { left: `${lane.offsetLeft}px`, top: `${lane.offsetTop}px`, width: `${w}px`, height: `${h}px` });
    const defs = el("defs", {}, svg);
    el("feGaussianBlur", { stdDeviation: "5" }, el("filter", { id: "trace-glow", x: "-30%", y: "-30%", width: "160%", height: "160%" }, defs));
    // The border as one path starting at the top-left corner's end, so the lap closes where it began.
    const i = 0.5, x0 = i, y0 = i, x1 = w - i, y1 = h - i, k = Math.max(0, r - i);
    const d = `M${x0 + k} ${y0} H${x1 - k} A${k} ${k} 0 0 1 ${x1} ${y0 + k} V${y1 - k} A${k} ${k} 0 0 1 ${x1 - k} ${y1} H${x0 + k} A${k} ${k} 0 0 1 ${x0} ${y1 - k} V${y0 + k} A${k} ${k} 0 0 1 ${x0 + k} ${y0}`;
    for (const layer of LAYERS) {
      const p = el("path", {
        d, pathLength: 1, fill: "none", stroke: layer.color, "stroke-width": layer.width, "stroke-linecap": "round",
        opacity: layer.opacity, "stroke-dasharray": `${layer.len} ${1 - layer.len}`,
        ...(layer.blur ? { filter: "url(#trace-glow)" } : {}),
      }, svg);
      // The head leads: every layer ends at the same point, so a longer tail starts further back.
      p.animate([{ strokeDashoffset: layer.len }, { strokeDashoffset: layer.len - 1 }], { duration: LAP_MS, easing: "cubic-bezier(.55,0,.35,1)", fill: "forwards" });
    }
    svg.animate([{ opacity: 1 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: LAP_MS + 260, fill: "forwards" }).finished.then(() => svg.remove());
    setTimeout(() => { lane.classList.remove("lit"); void lane.offsetWidth; lane.classList.add("lit"); }, LAP_MS - 40);
  };

  root.addEventListener("race:start", (e) => { if (!document.hidden) trace(e.detail.lane); });
})();
