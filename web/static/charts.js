// Line charts for the Outlook page (decision 107). Vanilla, no build step,
// like the rest of the app. One y-axis per chart; dashed lines are
// projections; reference lines are targets; a crosshair and tooltip
// follow the pointer.

(function () {
  const NS = "http://www.w3.org/2000/svg";
  const M = {top: 14, right: 64, bottom: 26, left: 52};

  function el(name, attrs, parent) {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  const day = s => new Date(s + "T00:00:00").getTime();

  function fmt(unit, v) {
    if (v === null || v === undefined) return "—";
    if (unit === "usd") return "$" + v.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    if (unit === "hours") return v.toLocaleString(undefined, {maximumFractionDigits: 1}) + " h";
    return Math.round(v).toLocaleString();
  }

  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  function render(box) {
    const spec = JSON.parse(box.dataset.chart);
    box.innerHTML = "";
    const width = Math.max(280, box.clientWidth), height = 220;
    const svg = el("svg", {viewBox: `0 0 ${width} ${height}`, width: "100%", height, role: "img",
                           "aria-label": box.dataset.label || ""}, box);
    const all = spec.series.flatMap(s => s.points);
    const refs = spec.refs || [];
    if (!all.length) { box.innerHTML = '<p class="meta">No figures yet.</p>'; return; }
    const xs = all.map(p => day(p[0])).concat(refs.flatMap(r => r.segments.flatMap(s => [day(s[0]), day(s[1])])));
    const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 86400000);
    let yTop = niceMax(Math.max(...all.map(p => p[1]), ...refs.flatMap(r => r.segments.map(s => s[2])), 0) * 1.05);
    if (spec.unit === "int") yTop = Math.max(4, yTop);      // whole numbers: four whole steps at least
    const W = width - M.left - M.right, H = height - M.top - M.bottom;
    const X = t => M.left + (t - x0) / (x1 - x0) * W;
    const Y = v => M.top + H - v / yTop * H;

    // Grid and axes: recessive.
    for (let i = 0; i <= 4; i++) {
      const v = yTop * i / 4, y = Y(v);
      el("line", {x1: M.left, x2: M.left + W, y1: y, y2: y, class: "viz-grid"}, svg);
      el("text", {x: M.left - 6, y: y + 4, "text-anchor": "end", class: "viz-axis"}, svg).textContent = fmt(spec.unit, v);
    }
    const months = [];
    const start = new Date(x0); start.setDate(1);
    for (let d = new Date(start); d.getTime() <= x1; d.setMonth(d.getMonth() + 1)) months.push(new Date(d));
    const every = Math.ceil(months.length / Math.max(2, Math.floor(W / 70)));
    months.forEach((d, i) => {
      if (d.getTime() < x0 || i % every) return;
      el("text", {x: X(d.getTime()), y: height - 8, "text-anchor": "middle", class: "viz-axis"}, svg)
        .textContent = d.toLocaleDateString(undefined, {month: "short", year: d.getMonth() === 0 ? "2-digit" : undefined});
    });

    // Targets and markers.
    for (const r of refs) for (const s of r.segments) {
      el("line", {x1: X(day(s[0])), x2: X(day(s[1])), y1: Y(s[2]), y2: Y(s[2]), class: "viz-ref"}, svg);
      el("text", {x: X(day(s[1])) + 4, y: Y(s[2]) + 4, class: "viz-ref-label"}, svg).textContent = r.label;
    }
    for (const m of spec.markers || []) {
      const x = X(day(m.at));
      if (x < M.left || x > M.left + W) continue;
      el("line", {x1: x, x2: x, y1: M.top, y2: M.top + H, class: "viz-marker"}, svg);
      el("text", {x: x + 4, y: M.top + 10, class: "viz-ref-label"}, svg).textContent = m.label;
    }

    // The series.
    for (const s of spec.series) {
      if (s.points.length < 2) continue;
      const d = s.points.map((p, i) => (i ? "L" : "M") + X(day(p[0])).toFixed(1) + " " + Y(p[1]).toFixed(1)).join(" ");
      el("path", {d, class: `viz-line viz-s${s.slot}` + (s.dashed ? " viz-dashed" : "")}, svg);
    }
    // Direct labels at the ends of a two-colour chart's lines.
    if (new Set(spec.series.map(s => s.slot)).size > 1) {
      for (const s of spec.series) {
        const last = s.points[s.points.length - 1];
        if (!last || !s.label_end) continue;
        el("text", {x: X(day(last[0])) + 4, y: Y(last[1]) + 4, class: "viz-end-label"}, svg).textContent = s.name;
      }
    }

    // Hover: a crosshair and the nearest point of each series.
    const cross = el("line", {y1: M.top, y2: M.top + H, class: "viz-cross", visibility: "hidden"}, svg);
    const dots = spec.series.map(s => el("circle", {r: 4, class: `viz-dot viz-s${s.slot}`, visibility: "hidden"}, svg));
    const tip = document.createElement("div");
    tip.className = "viz-tip"; tip.hidden = true; box.appendChild(tip);
    const hit = el("rect", {x: M.left, y: M.top, width: W, height: H, fill: "transparent"}, svg);
    hit.addEventListener("pointermove", ev => {
      const rect = svg.getBoundingClientRect();
      const t = x0 + ((ev.clientX - rect.left) * width / rect.width - M.left) / W * (x1 - x0);
      cross.setAttribute("x1", X(t)); cross.setAttribute("x2", X(t)); cross.setAttribute("visibility", "visible");
      const lines = [];
      spec.series.forEach((s, i) => {
        let best = null;
        for (const p of s.points) if (!best || Math.abs(day(p[0]) - t) < Math.abs(day(best[0]) - t)) best = p;
        if (!best || Math.abs(day(best[0]) - t) > (x1 - x0) / 25) { dots[i].setAttribute("visibility", "hidden"); return; }
        dots[i].setAttribute("cx", X(day(best[0]))); dots[i].setAttribute("cy", Y(best[1]));
        dots[i].setAttribute("visibility", "visible");
        lines.push(`<span class="viz-key viz-s${s.slot}${s.dashed ? " viz-dashed" : ""}"></span>${s.name}: <b>${fmt(spec.unit, best[1])}</b>`);
      });
      tip.innerHTML = `<div class="viz-tip-day">${new Date(t).toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric"})}</div>` + lines.join("<br>");
      tip.hidden = !lines.length;
      const px = (ev.clientX - rect.left);
      tip.style.left = Math.min(px + 12, rect.width - 190) + "px";
      tip.style.top = "8px";
    });
    hit.addEventListener("pointerleave", () => {
      cross.setAttribute("visibility", "hidden"); tip.hidden = true;
      dots.forEach(d => d.setAttribute("visibility", "hidden"));
    });
  }

  function renderAll() { document.querySelectorAll("[data-chart]").forEach(render); }
  window.addEventListener("DOMContentLoaded", renderAll);
  let timer;
  window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(renderAll, 150); });
})();
