// The compositor: a stage of pictures and marks, set for any time t.
//
// window.STAGE describes everything (see pipeline/animation/compositor/
// script.py): a surface, sprites with keyed positions, marks (labels,
// arrows, paths, rings, badges, titles), an optional avatar, and a camera.
// window.__seek(t) sets every element for time t from that data alone, with
// no clock and nothing carried over between frames, so any frame can be
// drawn on its own and the same stage always gives the same film.
//
// Stop-motion looks are stepped: sprite and camera times snap to the
// look's drawing rate, and each sprite shifts by a hair on every new
// drawing, as a hand-moved object does. Flat looks run smooth.
(function () {
  const S = window.STAGE;
  const A = window.ASSETS || {};
  const NS = "http://www.w3.org/2000/svg";
  const W = S.width, H = S.height;

  // --- easing and noise -------------------------------------------------
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const EASE = {
    linear: p => p,
    out: p => 1 - Math.pow(1 - p, 3),
    in: p => p * p * p,
    inout: p => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
    back: p => { const c = 1.9; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); },
    land: p => {                     // falls, overshoots into a squash, settles
      if (p < 0.72) return EASE.in(p / 0.72) * 1.0;
      const q = (p - 0.72) / 0.28;
      return 1 + Math.sin(q * Math.PI) * 0.04 * (1 - q);
    },
  };
  function hash(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function noise(seed) {             // deterministic, -1..1
    const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
    return (x - Math.floor(x)) * 2 - 1;
  }
  const step = S.step || 0;
  const snap = t => (step > 0 ? Math.floor(t / step + 1e-6) * step : t);

  function latest(keys, t, name, fallback) {      // a property that jumps, never blends
    let v = fallback;
    for (const k of keys) if (k[name] !== undefined && k.t <= t + 1e-6) v = k[name];
    return v;
  }
  function inWindows(windows, t) {
    for (const [a, b] of windows || []) if (t >= a && t < b) return true;
    return false;
  }

  function keyed(keys, t, props) {
    // Each property interpolated between the keys around t, with the ease
    // of the key being moved towards.
    const out = {};
    for (const name of props) {
      const ks = keys.filter(k => k[name] !== undefined);
      if (!ks.length) continue;
      if (t <= ks[0].t) { out[name] = ks[0][name]; continue; }
      const last = ks[ks.length - 1];
      if (t >= last.t) { out[name] = last[name]; continue; }
      let i = 0;
      while (i < ks.length - 1 && ks[i + 1].t <= t) i++;
      const a = ks[i], b = ks[i + 1];
      const p = clamp((t - a.t) / Math.max(1e-6, b.t - a.t), 0, 1);
      const e = (EASE[b.ease] || EASE.inout)(p);
      out[name] = a[name] + (b[name] - a[name]) * e;
      if (name === "y" && b.hop) out.y -= Math.sin(p * Math.PI) * b.hop;   // an arc
    }
    return out;
  }

  // --- build ------------------------------------------------------------
  const frame = document.getElementById("frame");
  const world = document.createElement("div");
  world.id = "world";
  world.style.cssText = `position:absolute;left:0;top:0;width:${S.world.w}px;height:${S.world.h}px;` +
    "transform-origin:0 0;";
  frame.appendChild(world);

  if (S.surface.image) {
    const img = new Image();
    img.src = A[S.surface.image];
    img.style.cssText = `position:absolute;left:0;top:0;width:${S.world.w}px;height:${S.world.h}px;` +
      "object-fit:cover;";
    world.appendChild(img);
  } else {
    world.style.background = S.surface.color || "#F4F1EA";
    if (S.surface.pattern === "dots") {
      world.style.backgroundImage =
        `radial-gradient(${S.surface.pattern_color || "rgba(0,0,0,0.07)"} 2.2px, transparent 2.6px)`;
      world.style.backgroundSize = "46px 46px";
    }
  }

  // A standing piece casts a soft ellipse on the ground under it; a piece
  // lying flat, or pinned to a board, casts its own shape.
  const ground = S.shadow && S.shadow.mode === "ground";
  const sprites = S.sprites.map(sp => {
    const el = document.createElement("img");
    el.src = A[sp.src];
    const z = sp.layer === "back" ? 1 : 10 + (sp.z || 0);
    el.style.cssText = `position:absolute;left:0;top:0;width:${sp.w}px;height:${sp.h}px;` +
      `will-change:transform;z-index:${z};transform-origin:50% 50%;`;
    let shade = null;
    if (ground && sp.layer !== "back") {
      shade = document.createElement("div");
      shade.style.cssText = `position:absolute;left:0;top:0;width:${sp.w * 0.78}px;height:${sp.w * 0.16}px;` +
        `border-radius:50%;background:rgba(${S.shadow.rgb},1);z-index:${z - 1};` +
        `filter:blur(${S.shadow.blur || 12}px);`;
      world.appendChild(shade);
    }
    world.appendChild(el);
    return { sp, el, shade };
  });

  // Every pose is its own image, decoded up front, and shown or hidden:
  // swapping one image's source would race the screenshot.
  let avatar = null;
  if (S.avatar) {
    const images = {};
    for (const [name, src] of Object.entries(S.avatar.poses)) {
      const img = document.createElement("img");
      img.src = A[src];
      img.style.cssText = `position:absolute;left:0;top:0;height:${S.avatar.h}px;z-index:2500;opacity:0;` +
        `transform:translate(${S.avatar.x}px, ${S.avatar.y}px) translate(-50%, -100%);`;
      world.appendChild(img);
      images[name] = img;
    }
    avatar = { images };
  }

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", S.world.w);
  svg.setAttribute("height", S.world.h);
  svg.style.cssText = "position:absolute;left:0;top:0;z-index:5000;overflow:visible;";
  world.appendChild(svg);
  const L = S.labels;                // the label style
  const defs0 = document.createElementNS(NS, "defs");
  svg.appendChild(defs0);

  function el(name, attrs, parent) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    (parent || svg).appendChild(e);
    return e;
  }

  // A hand-drawn line: the straight or bent path with a slight, fixed
  // wobble, so it looks drawn with a marker rather than plotted.
  function roughPath(points, seed, rough) {
    const pts = [];
    for (let i = 0; i < points.length - 1; i++) {
      const [x1, y1] = points[i], [x2, y2] = points[i + 1];
      const n = Math.max(2, Math.round(Math.hypot(x2 - x1, y2 - y1) / 28));
      for (let j = 0; j < n; j++) {
        const p = j / n, x = x1 + (x2 - x1) * p, y = y1 + (y2 - y1) * p;
        const d = rough * noise(seed + i * 31 + j);
        pts.push([x + d, y - d * 0.6]);
      }
    }
    pts.push(points[points.length - 1]);
    return "M" + pts.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" L");
  }
  function curvePoints(x1, y1, x2, y2, bend) {
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, len = Math.hypot(x2 - x1, y2 - y1);
    const nx = -(y2 - y1) / (len || 1), ny = (x2 - x1) / (len || 1);
    const cx = mx + nx * bend * len, cy = my + ny * bend * len;
    const pts = [];
    for (let i = 0; i <= 24; i++) {
      const p = i / 24, a = (1 - p) * (1 - p), b = 2 * (1 - p) * p, c = p * p;
      pts.push([a * x1 + b * cx + c * x2, a * y1 + b * cy + c * y2]);
    }
    return pts;
  }

  function wrapText(text, maxChars) {
    const words = String(text).split(/\s+/), lines = [];
    let line = "";
    for (const w of words) {
      if (line && (line + " " + w).length > maxChars) { lines.push(line); line = w; }
      else line = line ? line + " " + w : w;
    }
    if (line) lines.push(line);
    return lines.slice(0, 3);
  }

  // A diagram's arrowhead: a filled triangle (crisp looks) or a chevron.
  function arrowHead(g, tip, from, width, color, solid) {
    const ang = Math.atan2(tip[1] - from[1], tip[0] - from[0]), hl = width * (solid ? 4.6 : 4.2);
    const a = [tip[0] - hl * Math.cos(ang - 0.42), tip[1] - hl * Math.sin(ang - 0.42)];
    const b = [tip[0] - hl * Math.cos(ang + 0.42), tip[1] - hl * Math.sin(ang + 0.42)];
    return el("path", solid
      ? { d: `M${a[0]},${a[1]} L${tip[0]},${tip[1]} L${b[0]},${b[1]} Z`, fill: color, stroke: color,
          "stroke-width": 1, opacity: 0 }
      : { d: `M${a[0]},${a[1]} L${tip[0]},${tip[1]} L${b[0]},${b[1]}`, fill: "none", stroke: color,
          "stroke-width": width, "stroke-linecap": "round", "stroke-linejoin": "round", opacity: 0 }, g);
  }

  const marks = S.marks.map((m, index) => {
    const g = el("g", { opacity: 0 });
    const seed = hash(m.id || String(index));
    const color = m.color || L.color;
    const rough = L.rough ? 2.2 : 0;
    const item = { m, g, parts: [] };
    if (m.kind === "stroke") {                        // a diagram's line or curve, drawn on
      const pts = m.points;
      const tip = m.arrow ? 0.9 * (m.width || L.line) * 4.6 : 0;
      const shaft = pts.slice();
      // The shaft stops short of a solid head, so the point stays sharp.
      if (m.arrow && m.solid_head && shaft.length > 1) {
        const [ex, ey] = shaft[shaft.length - 1], [px, py] = shaft[shaft.length - 2];
        const d = Math.hypot(ex - px, ey - py) || 1;
        shaft[shaft.length - 1] = [ex - (ex - px) / d * tip * 0.8, ey - (ey - py) / d * tip * 0.8];
      }
      item.path = el("path", {
        d: rough ? roughPath(shaft, seed, rough * 0.7) : "M" + shaft.map(p => p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" L"),
        fill: "none", stroke: color, "stroke-width": m.width || L.line, "stroke-linecap": "round",
        "stroke-linejoin": "round", opacity: m.opacity == null ? 1 : m.opacity,
      }, g);
      if (m.arrow && pts.length > 1) {
        item.head = arrowHead(g, pts[pts.length - 1], pts[pts.length - 2], m.width || L.line, color, m.solid_head);
        if (m.arrow === "both") item.tail = arrowHead(g, pts[0], pts[1], m.width || L.line, color, m.solid_head);
      }
    } else if (m.kind === "bar") {                    // grows from its baseline; may change height
      item.rect = el("rect", { x: m.x - m.w / 2, y: m.base, width: m.w, height: 0, fill: color }, g);
    } else if (m.kind === "dot") {
      item.dot = el("circle", {
        cx: m.x, cy: m.y, r: m.r, fill: m.hollow ? "none" : color,
        stroke: m.hollow ? color : "none", "stroke-width": m.width || L.line,
      }, g);
    } else if (m.kind === "area") {
      el("path", { d: "M" + m.points.map(p => p.join(",")).join(" L") + " Z", fill: color,
                   opacity: m.opacity == null ? 0.35 : m.opacity, stroke: "none" }, g);
    } else if (m.kind === "math") {                   // typeset maths, written in left to right
      item.img = el("image", { href: A[m.src], x: m.x - m.w / 2, y: m.y - m.h / 2,
                               width: m.w, height: m.h }, g);
      const id = "mclip" + index;
      const cp = el("clipPath", { id }, defs0);
      item.clipRect = el("rect", { x: m.x - m.w / 2 - 6, y: m.y - m.h / 2 - 6, width: 0,
                                   height: m.h + 12 }, cp);
      item.img.setAttribute("clip-path", `url(#${id})`);
    } else if (m.kind === "text") {                   // a diagram's plain numbers and words
      item.plain = el("text", {
        x: m.x, y: m.y, "text-anchor": m.align || "middle", "dominant-baseline": "central",
        "font-family": m.font || L.font, "font-size": m.size || L.size * 0.6,
        "font-weight": m.weight || 400, fill: color,
      }, g);
      item.plain.textContent = m.text;
    } else if (m.kind === "label" || m.kind === "title") {
      const size = m.kind === "title" ? L.title_size * (m.big ? 1.5 : 1) : (m.size || L.size);
      const words = L.upper ? String(m.text).toUpperCase() : m.text;
      const lines = wrapText(words, m.kind === "title" ? (m.big ? 13 : 20) : (m.chars || 14));
      const lh = size * 1.12;
      const text = el("text", {
        x: m.x, y: m.y - (lines.length - 1) * lh / 2, "text-anchor": m.align || "middle",
        "dominant-baseline": "central", "font-family": L.font, "font-size": size,
        "font-weight": L.weight, fill: L.tag ? (L.tag_text || color) : color,
        "letter-spacing": L.tracking || 0,
      }, g);
      lines.forEach((ln, i) => {
        const ts = el("tspan", { x: m.x, dy: i ? lh : 0 }, text);
        ts.textContent = ln;
      });
      item.text = text;
      item.lines = lines;
      item.tilt = L.tag ? noise(seed) * 2.5 : 0;
    } else if (m.kind === "arrow" || m.kind === "path") {
      const pts = curvePoints(m.x1, m.y1, m.x2, m.y2, m.bend || 0);
      const path = el("path", {
        d: roughPath(pts, seed, rough), fill: "none", stroke: color,
        "stroke-width": m.width || L.line, "stroke-linecap": "round", "stroke-linejoin": "round",
      }, g);
      if (m.kind === "path") path.setAttribute("stroke-dasharray", `${(m.width || L.line) * 0.2} ${(m.width || L.line) * 2.6}`);
      item.path = path;
      if (m.kind === "arrow") {
        const [ex, ey] = pts[pts.length - 1], [px, py] = pts[pts.length - 4];
        const ang = Math.atan2(ey - py, ex - px), hl = (m.width || L.line) * 4.2;
        const head = el("path", {
          d: `M${ex - hl * Math.cos(ang - 0.5)},${ey - hl * Math.sin(ang - 0.5)} L${ex},${ey} ` +
             `L${ex - hl * Math.cos(ang + 0.5)},${ey - hl * Math.sin(ang + 0.5)}`,
          fill: "none", stroke: color, "stroke-width": m.width || L.line,
          "stroke-linecap": "round", "stroke-linejoin": "round", opacity: 0,
        }, g);
        item.head = head;
      }
    } else if (m.kind === "ring") {
      const pts = [];
      for (let i = 0; i <= 40; i++) {
        const a = -Math.PI / 2 + i / 40 * Math.PI * 2.12;
        const r = 1 + 0.05 * noise(seed + i);
        pts.push([m.x + Math.cos(a) * m.rx * r, m.y + Math.sin(a) * m.ry * r]);
      }
      item.path = el("path", {
        d: roughPath(pts, seed, rough * 0.6), fill: "none", stroke: m.color || L.accent,
        "stroke-width": L.line * 1.1, "stroke-linecap": "round",
      }, g);
    } else if (m.kind === "badge") {
      el("circle", { cx: m.x, cy: m.y, r: m.r || 44, fill: m.color || L.accent }, g);
      const t = el("text", {
        x: m.x, y: m.y + 2, "text-anchor": "middle", "dominant-baseline": "central",
        "font-family": L.font, "font-size": (m.r || 44) * 1.05, "font-weight": L.weight,
        fill: L.badge_text || "#FFFFFF",
      }, g);
      t.textContent = m.text;
    } else if (m.kind === "bubble") {                 // speech or thought, over a head
      const lines = wrapText(m.text, 16);
      const size = L.size * 0.82, lh = size * 1.1;
      const text = el("text", {
        x: m.x, y: m.y, "text-anchor": "middle", "dominant-baseline": "central",
        "font-family": L.font, "font-size": size, "font-weight": L.weight,
        fill: L.bubble_text || "#1F1F24",
      }, g);
      lines.forEach((ln, i) => {
        const ts = el("tspan", { x: m.x, dy: i ? lh : 0 }, text);
        ts.textContent = ln;
      });
      item.bubble = { text, lines, lh };
    } else if (m.kind === "table") {                  // a grid of words: a payoff matrix, a tally
      const rows = m.rows || [], nr = rows.length, nc = Math.max(1, ...rows.map(r => r.length));
      const cw = m.w / nc, ch = m.h / Math.max(1, nr), x0 = m.x - m.w / 2, y0 = m.y - m.h / 2;
      // On a textured surface (a wooden board, felt) the grid sits on a card
      // of its own, so its words read.
      const card = L.tag || S.surface.image;
      const ink = card ? (L.tag_text || "#2B2A33") : color;
      if (card) {
        item.card = el("rect", { x: x0 - 22, y: y0 - 22, width: m.w + 44, height: m.h + 44, rx: 12,
                                 fill: L.tag || "#FBF8F1", filter: "url(#tagshadow)" }, g);
      }
      const lines = [];
      for (let r = 0; r <= nr; r++) lines.push([[x0, y0 + r * ch], [x0 + m.w, y0 + r * ch]]);
      for (let c = 0; c <= nc; c++) lines.push([[x0 + c * cw, y0], [x0 + c * cw, y0 + m.h]]);
      item.paths = lines.map((pts, i) => el("path", {
        d: roughPath(pts, seed + i * 13, rough * 0.8), fill: "none", stroke: ink,
        "stroke-width": L.line * 0.8, "stroke-linecap": "round",
      }, g));
      item.cells = [];
      rows.forEach((row, r) => row.forEach((cell, c) => {
        const head = r === 0 || c === 0;
        const t = el("text", {
          x: x0 + (c + 0.5) * cw, y: y0 + (r + 0.5) * ch, "text-anchor": "middle",
          "dominant-baseline": "central", "font-family": L.font, "font-weight": L.weight,
          "font-size": Math.min(L.size * (head ? 0.8 : 0.95), ch * 0.5, cw / Math.max(3, String(cell).length) * 1.7),
          fill: head && (r > 0 || c > 0) ? L.accent : ink, opacity: 0,
        }, g);
        t.textContent = L.upper ? String(cell).toUpperCase() : cell;
        item.cells.push(t);
      }));
    } else if (m.kind === "symbol") {                 // vs, +, =
      const t = el("text", {
        x: m.x, y: m.y, "text-anchor": "middle", "dominant-baseline": "central",
        "font-family": L.font, "font-size": m.size || L.title_size * 1.3, "font-weight": L.weight,
        fill: m.color || L.color,
      }, g);
      t.textContent = m.text;
    }
    return item;
  });

  // Labels on tags need their text measured, so tags are laid out once the
  // fonts are in.
  function layoutTags() {
    for (const item of marks) {
      if (item.bubble) {
        // The bubble is sized to its words, above the point it speaks from.
        const { text, lines, lh } = item.bubble, m = item.m;
        const tail = 34, padX = L.size * 0.55, padY = L.size * 0.36;
        const box = text.getBBox();
        const bw = box.width + padX * 2, bh = box.height + padY * 2;
        // Inside the frame and below the title: the bubble slides along or
        // down; its tail still points at whoever speaks.
        const half = (m.thinks ? bw * 0.62 : bw / 2) + 6;
        const bx = clamp(m.x, (m.min_x == null ? 24 : m.min_x) + half,
                         (m.max_x == null ? W - 24 : m.max_x) - half);
        const cy = Math.max(m.y - tail - bh / 2, (m.min_y || 0) + (m.thinks ? bh * 0.66 : bh / 2));
        text.setAttribute("x", bx);
        text.querySelectorAll("tspan").forEach(ts => ts.setAttribute("x", bx));
        text.setAttribute("y", cy - (lines.length - 1) * lh / 2);
        const shape = document.createElementNS(NS, "g");
        const body = document.createElementNS(NS, m.thinks ? "ellipse" : "rect");
        if (m.thinks) {
          body.setAttribute("cx", bx); body.setAttribute("cy", cy);
          body.setAttribute("rx", bw * 0.62); body.setAttribute("ry", bh * 0.66);
        } else {
          body.setAttribute("x", bx - bw / 2); body.setAttribute("y", cy - bh / 2);
          body.setAttribute("width", bw); body.setAttribute("height", bh);
          body.setAttribute("rx", Math.min(28, bh / 2));
        }
        const style = { fill: L.bubble || "#FFFFFF", stroke: L.bubble_line || "#1F1F24", "stroke-width": 4 };
        for (const k in style) body.setAttribute(k, style[k]);
        shape.appendChild(body);
        if (m.thinks) {
          // Two puffs from the bubble's underside towards the thinker.
          const sx = bx, sy = cy + bh * 0.66;
          for (const [f, r] of [[0.35, 10], [0.7, 6]]) {
            const c = document.createElementNS(NS, "circle");
            c.setAttribute("cx", sx + (m.x - sx) * f); c.setAttribute("cy", sy + (m.y - sy) * f + 6);
            c.setAttribute("r", r);
            for (const k in style) c.setAttribute(k, style[k]);
            shape.appendChild(c);
          }
        } else {
          const tailPath = document.createElementNS(NS, "path");
          const by = cy + bh / 2 - 2;
          const tx = clamp(m.x, bx - bw / 2 + 26, bx + bw / 2 - 26);
          const ty = Math.max(m.y, by + 18);
          tailPath.setAttribute("d", `M${tx - 16},${by} L${m.x},${ty} L${tx + 16},${by}`);
          for (const k in style) tailPath.setAttribute(k, style[k]);
          shape.appendChild(tailPath);
          const hide = document.createElementNS(NS, "path");       // hides the seam
          hide.setAttribute("d", `M${tx - 13},${by - 3} L${tx + 13},${by - 3}`);
          hide.setAttribute("stroke", L.bubble || "#FFFFFF"); hide.setAttribute("stroke-width", 7);
          shape.appendChild(hide);
        }
        shape.setAttribute("filter", "url(#tagshadow)");
        item.g.insertBefore(shape, text);
        continue;
      }
      if (!item.text || !L.tag) continue;
      const box = item.text.getBBox();
      const padX = L.size * 0.42, padY = L.size * 0.22;
      const rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", box.x - padX);
      rect.setAttribute("y", box.y - padY);
      rect.setAttribute("width", box.width + padX * 2);
      rect.setAttribute("height", box.height + padY * 2);
      rect.setAttribute("rx", L.tag_radius || 6);
      rect.setAttribute("fill", L.tag);
      rect.setAttribute("filter", "url(#tagshadow)");
      item.g.insertBefore(rect, item.text);
      item.tag = rect;
    }
  }
  const defs = el("defs", {});
  const filter = el("filter", { id: "tagshadow", x: "-20%", y: "-20%", width: "140%", height: "160%" }, defs);
  el("feDropShadow", { dx: 3, dy: 6, stdDeviation: 5, "flood-color": "#2B2118", "flood-opacity": 0.28 }, filter);
  // Chalk: lettering and lines broken up into powder.
  if (L.chalk) {
    const chalk = el("filter", { id: "chalk", x: "-5%", y: "-5%", width: "110%", height: "110%" }, defs);
    el("feTurbulence", { type: "fractalNoise", baseFrequency: "0.9", numOctaves: 2, seed: 3, result: "n" }, chalk);
    el("feDisplacementMap", { in: "SourceGraphic", in2: "n", scale: 3.2, result: "d" }, chalk);
    el("feColorMatrix", { in: "n", type: "matrix", values: "0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 -1.4 1.25", result: "holes" }, chalk);
    el("feComposite", { in: "d", in2: "holes", operator: "in" }, chalk);
    marks.forEach(item => { if (!item.bubble) item.g.setAttribute("filter", "url(#chalk)"); });
  }

  // --- seek ---------------------------------------------------------------
  function state(t) {
    const ts = snap(t);
    const drawing = step > 0 ? Math.round(ts / step) : 0;
    const cam = keyed(S.camera, S.camera_stepped ? ts : t, ["x", "y", "zoom"]);
    // Never past the edge of the world: a push-in near the top of the
    // table would otherwise show black above it.
    const hw = W / 2 / cam.zoom, hh = H / 2 / cam.zoom;
    if (S.world.w >= 2 * hw) cam.x = clamp(cam.x, hw, S.world.w - hw);
    if (S.world.h >= 2 * hh) cam.y = clamp(cam.y, hh, S.world.h - hh);
    const out = { cam, sprites: [], marks: [], avatar: null };
    for (const { sp } of sprites) {
      const k = keyed(sp.keys, ts, ["x", "y", "rot", "scale", "alpha", "lift", "reveal"]);
      k.flip = latest(sp.keys, ts, "flip", 1);
      if (k.reveal === undefined) k.reveal = 1;
      if (k.lift === undefined) k.lift = 0;
      if (inWindows(sp.sway, ts)) {                   // a puppet speaking: it rocks and bobs
        k.rot += Math.sin(ts * 7 + hash(sp.id) % 5) * 2.2;
        k.y -= Math.abs(Math.sin(ts * 7)) * 7;
      }
      const j = S.jitter || 0;
      if (j > 0 && k.alpha > 0) {
        const seed = hash(sp.id) + drawing * 7;
        k.x += noise(seed) * j;
        k.y += noise(seed + 1) * j;
        k.rot += noise(seed + 2) * j * 0.35;
      }
      if (sp.idle === "breathe") k.scale *= 1 + 0.018 * Math.sin(ts * 2.4 + hash(sp.id) % 7);
      out.sprites.push(k);
    }
    for (const item of marks) {
      const m = item.m;
      const tm = L.stepped ? ts : t;
      const since = tm - m.t0, left = (m.t1 == null ? 1e9 : m.t1) - tm;
      const draw = m.draw || 0.45;
      const p = clamp(since / draw, 0, 1);
      const fades = m.kind === "label" || m.kind === "title" || m.kind === "text" || m.kind === "area";
      const alpha = since < 0 ? 0 : Math.min(1, clamp(left / 0.25, 0, 1),
                                            fades ? clamp(since / (m.kind === "area" ? draw : 0.18), 0, 1) : 1);
      // A continued diagram's bar or point moves to its new value.
      const kv = m.keys ? keyed(m.keys, tm, ["h", "x", "y"]) : null;
      out.marks.push({ p, alpha, kv });
    }
    if (avatar) {
      let pose = null, at = null;
      for (const k of S.avatar.keys) if (k.t <= t + 1e-6) { pose = k.pose; at = k; }
      let open = false;
      for (const [a, b] of S.avatar.talk) {
        if (t >= a && t < b) { open = Math.floor((t - a) * 8) % 2 === 0; break; }
      }
      out.avatar = { pose, open, x: at ? at.x : S.avatar.x, y: at ? at.y : S.avatar.y };
    }
    return out;
  }

  function apply(st) {
    const c = st.cam;
    world.style.transform =
      `translate(${W / 2 - c.x * c.zoom}px, ${H / 2 - c.y * c.zoom}px) scale(${c.zoom})`;
    sprites.forEach(({ sp, el }, i) => {
      const k = st.sprites[i];
      const s = k.scale * (1 + 0.07 * k.lift);
      el.style.opacity = k.alpha;
      el.style.transform = `translate(${k.x - sp.w / 2}px, ${k.y - sp.h / 2}px) ` +
        `rotate(${k.rot}deg) scale(${s * k.flip}, ${s})`;
      // Drawn in as if being drawn: revealed left to right.
      el.style.clipPath = k.reveal < 0.999 ? `inset(0 ${(1 - k.reveal) * 100}% 0 0)` : "none";
      if (S.depth_sort && sp.layer !== "back") el.style.zIndex = 20 + Math.round(k.y / 2);
      const sh = S.shadow;
      const shade = sprites[i].shade;
      if (shade) {
        const lift = k.lift || 0;
        const sw = sp.w * 0.78 * s * (1 - 0.35 * lift);
        shade.style.opacity = k.alpha * (sh.opacity || 0.35) * (1 - 0.6 * lift);
        shade.style.transformOrigin = "0 0";
        shade.style.transform = `translate(${k.x - sw / 2}px, ${k.y + sp.h * s / 2 - sp.w * 0.1 + 24 * lift}px) ` +
          `scale(${sw / (sp.w * 0.78)}, 1)`;
        if (S.depth_sort) shade.style.zIndex = 19 + Math.round(k.y / 2);
        el.style.filter = "none";
      } else if (sh && sh.mode !== "none" && sh.mode !== "ground" && k.alpha > 0) {
        const d = sh.distance * (1 + 5 * k.lift), b = sh.blur * (1 + 2.2 * k.lift);
        const o = sh.opacity * (1 - 0.45 * k.lift);
        el.style.filter = `drop-shadow(${d * sh.dx}px ${d * sh.dy}px ${b}px rgba(${sh.rgb},${o}))`;
      } else {
        el.style.filter = "none";
      }
    });
    marks.forEach((item, i) => {
      const { p, alpha } = st.marks[i];
      item.g.setAttribute("opacity", alpha);
      if (item.path) {
        const len = item.len || (item.len = item.path.getTotalLength());
        item.path.setAttribute("stroke-dasharray", item.m.kind === "path"
          ? item.path.getAttribute("stroke-dasharray") : `${len} ${len}`);
        if (item.m.kind !== "path") item.path.setAttribute("stroke-dashoffset", len * (1 - p));
        else item.g.setAttribute("opacity", alpha * Math.min(1, p * 1.5));
        if (item.head) item.head.setAttribute("opacity", p >= 0.98 ? 1 : 0);
        if (item.tail) item.tail.setAttribute("opacity", p > 0.02 ? 1 : 0);
      }
      const kv = st.marks[i].kv || {};
      if (item.rect) {                      // a bar grows, then follows its value
        const m = item.m;
        const h = (kv.h !== undefined ? kv.h : m.h) * EASE.out(p);
        item.rect.setAttribute("y", h >= 0 ? m.base - h : m.base);
        item.rect.setAttribute("height", Math.abs(h));
      }
      if (item.dot) {                       // a point pops in, then moves with its value
        const m = item.m;
        item.dot.setAttribute("cx", kv.x !== undefined ? kv.x : m.x);
        item.dot.setAttribute("cy", kv.y !== undefined ? kv.y : m.y);
        item.dot.setAttribute("r", Math.max(0.01, m.r * EASE.back(p)));
      }
      if (item.img) {                       // maths written in left to right
        const m = item.m;
        const x = (kv.x !== undefined ? kv.x : m.x) - m.w / 2;
        const y = (kv.y !== undefined ? kv.y : m.y) - m.h / 2;
        item.img.setAttribute("x", x); item.img.setAttribute("y", y);
        item.clipRect.setAttribute("x", x - 6); item.clipRect.setAttribute("y", y - 6);
        item.clipRect.setAttribute("width", (m.w + 12) * EASE.inout(p));
      }
      if (item.plain && (kv.x !== undefined || kv.y !== undefined)) {
        item.plain.setAttribute("x", kv.x !== undefined ? kv.x : item.m.x);
        item.plain.setAttribute("y", kv.y !== undefined ? kv.y : item.m.y);
      }
      if (item.bubble) {                    // pops out of the speaker
        const m = item.m, sc = 0.55 + 0.45 * EASE.back(clamp(p * 1.4, 0, 1));
        item.g.setAttribute("transform", `translate(${m.x} ${m.y}) scale(${sc}) translate(${-m.x} ${-m.y})`);
      }
      if (item.paths) {                     // a table: lines drawn on, then its words
        item.paths.forEach((path, j) => {
          const len = path.__len || (path.__len = path.getTotalLength());
          path.setAttribute("stroke-dasharray", `${len} ${len}`);
          const q = clamp(p * 1.6 - j * 0.05, 0, 1);
          path.setAttribute("stroke-dashoffset", len * (1 - q));
        });
        item.cells.forEach((c, j) => c.setAttribute("opacity", clamp(p * 2.2 - 0.9 - j * 0.06, 0, 1)));
      }
      if (item.text) {
        // Written in, left to right, or faded up for clean looks.
        const tilt = item.tilt || 0, m = item.m;
        const lift = L.write ? 0 : (1 - EASE.out(clamp(p * 1.6, 0, 1))) * 18;
        item.g.setAttribute("transform", `translate(0 ${lift}) rotate(${tilt} ${m.x} ${m.y})`);
        if (L.write) {
          if (!item.clip) {
            const box = item.g.getBBox();
            const id = "clip" + i;
            const cp = el("clipPath", { id }, defs);
            item.clipRect = el("rect", { x: box.x - 20, y: box.y - 20, width: 0, height: box.height + 40 }, cp);
            item.clipW = box.width + 40;
            item.g.setAttribute("clip-path", `url(#${id})`);
            item.clip = true;
          }
          item.clipRect.setAttribute("width", item.clipW * EASE.inout(clamp(p * 1.25, 0, 1)));
        }
      }
    });
    if (avatar && st.avatar) {
      const pose = st.avatar.pose;
      const name = pose && avatar.images[pose + (st.avatar.open ? "_open" : "")]
        ? pose + (st.avatar.open ? "_open" : "") : pose;
      for (const [key, img] of Object.entries(avatar.images)) {
        img.style.opacity = key === name ? 1 : 0;
        if (key === name) img.style.transform =
          `translate(${st.avatar.x}px, ${st.avatar.y}px) translate(-50%, -100%)`;
      }
    }
  }

  window.__seek = t => apply(state(t));
  // Equal signatures, equal frames: a stepped stage repeats each drawing
  // for several video frames, and those are captured once.
  window.__signature = t => {
    if (step <= 0) return null;
    const st = state(t);
    return JSON.stringify([snap(t), st.marks.map(m => [m.p.toFixed(3), m.alpha.toFixed(3),
                                                        m.kv ? Object.values(m.kv).map(v => v.toFixed(1)) : 0]),
                           st.sprites.map(k => [k.x.toFixed(1), k.y.toFixed(1), k.alpha.toFixed(3), k.reveal.toFixed(3)]),
                           st.avatar, S.camera_stepped ? null : st.cam]);
  };
  window.__boxes = t => {             // where each sprite and mark is, for the checks
    window.__seek(t);
    const out = [];
    sprites.forEach(({ sp, el }) => {
      const r = el.getBoundingClientRect();
      if (parseFloat(el.style.opacity) > 0.05) out.push({ id: sp.id, kind: "sprite", box: [r.left, r.top, r.width, r.height] });
    });
    marks.forEach(item => {
      if (parseFloat(item.g.getAttribute("opacity")) > 0.05 && item.text) {
        const r = item.g.getBoundingClientRect();
        out.push({ id: item.m.id, kind: item.m.kind, box: [r.left, r.top, r.width, r.height] });
      }
    });
    return out;
  };

  const images = [...document.images];
  Promise.all([document.fonts.ready, ...images.map(i => i.decode ? i.decode().catch(() => {}) : null)])
    .then(() => { layoutTags(); window.__seek(0); window.__ready = true; });
})();
