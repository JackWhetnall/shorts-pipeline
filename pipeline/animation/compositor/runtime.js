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

  const sprites = S.sprites.map(sp => {
    const el = document.createElement("img");
    el.src = A[sp.src];
    el.style.cssText = `position:absolute;left:0;top:0;width:${sp.w}px;height:${sp.h}px;` +
      `will-change:transform;z-index:${10 + (sp.z || 0)};`;
    world.appendChild(el);
    return { sp, el };
  });

  // Every pose is its own image, decoded up front, and shown or hidden:
  // swapping one image's source would race the screenshot.
  let avatar = null;
  if (S.avatar) {
    const images = {};
    for (const [name, src] of Object.entries(S.avatar.poses)) {
      const img = document.createElement("img");
      img.src = A[src];
      img.style.cssText = `position:absolute;left:0;top:0;height:${S.avatar.h}px;z-index:40;opacity:0;` +
        `transform:translate(${S.avatar.x}px, ${S.avatar.y}px) translate(-50%, -100%);`;
      world.appendChild(img);
      images[name] = img;
    }
    avatar = { images };
  }

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", S.world.w);
  svg.setAttribute("height", S.world.h);
  svg.style.cssText = "position:absolute;left:0;top:0;z-index:60;overflow:visible;";
  world.appendChild(svg);
  const L = S.labels;                // the label style

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

  const marks = S.marks.map((m, index) => {
    const g = el("g", { opacity: 0 });
    const seed = hash(m.id || String(index));
    const color = m.color || L.color;
    const rough = L.rough ? 2.2 : 0;
    const item = { m, g, parts: [] };
    if (m.kind === "label" || m.kind === "title") {
      const size = m.kind === "title" ? L.title_size * (m.big ? 1.5 : 1) : (m.size || L.size);
      const lines = wrapText(m.text, m.kind === "title" ? (m.big ? 13 : 20) : (m.chars || 14));
      const lh = size * 1.12;
      const text = el("text", {
        x: m.x, y: m.y - (lines.length - 1) * lh / 2, "text-anchor": m.align || "middle",
        "dominant-baseline": "central", "font-family": L.font, "font-size": size,
        "font-weight": L.weight, fill: color, "letter-spacing": L.tracking || 0,
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
      const k = keyed(sp.keys, ts, ["x", "y", "rot", "scale", "alpha", "lift"]);
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
      const alpha = since < 0 ? 0 : Math.min(1, clamp(left / 0.25, 0, 1), m.kind === "label" || m.kind === "title" ? clamp(since / 0.18, 0, 1) : 1);
      out.marks.push({ p, alpha });
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
        `rotate(${k.rot}deg) scale(${s})`;
      const sh = S.shadow;
      if (sh && sh.mode !== "none" && k.alpha > 0) {
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
    return JSON.stringify([snap(t), st.marks.map(m => [m.p.toFixed(3), m.alpha.toFixed(3)]),
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
