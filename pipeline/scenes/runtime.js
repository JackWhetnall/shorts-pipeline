/*
 * The scene timeline engine: SCENE + STYLE -> SVG, and __seek(t) sets every
 * element to exactly how it looks at time t.
 *
 * Deterministic by construction: nothing animates by itself (no CSS
 * animations, no requestAnimationFrame). Each frame is a pure function of
 * t, so the renderer can capture any frame, in any order, and get the same
 * picture every time. See docs/specs/animated-scenes.md.
 *
 * The scene is data the pipeline wrote (never code): elements (shape,
 * label, prop, counter, chart) and actions anchored to times (appear,
 * draw, write, count, move, highlight, stack, exit). Times arrive here in
 * seconds; mapping spoken words to seconds happens in Python.
 */
// Built once fonts are ready: labels measure their own text to size the
// pill behind it, and a measurement taken in a fallback font is wrong.
window.__start = function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const SCENE = window.SCENE, STYLE = window.STYLE, ASSETS = window.ASSETS || {};
  // Per asset: its pixel size and the long axis of the object in it
  // (worked out in Python), so a prop can be laid along two points.
  const META = window.ASSET_META || {};
  const W = SCENE.width || 1080, H = SCENE.height || 1920;
  const stage = document.getElementById("stage");

  // --- helpers --------------------------------------------------------
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, p) => a + (b - a) * p;
  const EASE = {
    linear: t => t,
    out: t => 1 - Math.pow(1 - t, 3),
    inout: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    back: t => { const c1 = 1.9, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
    bounce: t => {
      const n = 7.5625, d = 2.75;
      if (t < 1 / d) return n * t * t;
      if (t < 2 / d) return n * (t -= 1.5 / d) * t + 0.75;
      if (t < 2.5 / d) return n * (t -= 2.25 / d) * t + 0.9375;
      return n * (t -= 2.625 / d) * t + 0.984375;
    },
  };
  const motion = STYLE.motion || {};
  const easeFor = kind => EASE[motion[kind] || "inout"] || EASE.inout;

  function node(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  // Art directions name one installed font; a fallback keeps text
  // readable (and measurable) if it's ever missing.
  const family = f => `'${String(f || "Segoe UI").replace(/'/g, "")}', 'Segoe UI', sans-serif`;
  const color = c => (c && STYLE.colors && STYLE.colors[c]) || c || STYLE.ink;
  const progress = (t, a) => clamp((t - a.at) / Math.max(0.001, a.dur || 0.001));

  // --- backdrop -------------------------------------------------------
  const defs = node("defs", {}, stage);
  const bg = STYLE.background || {};
  node("rect", {x: 0, y: 0, width: W, height: H, fill: bg.color || "#fff"}, stage);
  const pc = bg.pattern_color || "#0001";
  const PATTERNS = {
    dots: pat => node("circle", {cx: 24, cy: 24, r: 3.2, fill: pc}, pat),
    grid: pat => node("path", {d: "M 48 0 H 0 V 48", fill: "none", stroke: pc, "stroke-width": 2}, pat),
    lines: pat => node("path", {d: "M 0 47 H 48", fill: "none", stroke: pc, "stroke-width": 2}, pat),
  };
  if (PATTERNS[bg.pattern]) {
    const pat = node("pattern", {id: "bgpat", width: 48, height: 48, patternUnits: "userSpaceOnUse"}, defs);
    PATTERNS[bg.pattern](pat);
    node("rect", {x: 0, y: 0, width: W, height: H, fill: "url(#bgpat)"}, stage);
  }
  // Paper or board grain: fixed-seed noise, so every frame is identical.
  if (bg.grain) {
    const f = node("filter", {id: "grain", x: 0, y: 0, width: "100%", height: "100%"}, defs);
    node("feTurbulence", {type: "fractalNoise", baseFrequency: 0.9, numOctaves: 2, seed: 7, stitchTiles: "stitch"}, f);
    node("feColorMatrix", {type: "matrix", values: `0 0 0 0 ${bg.grain_light ? 1 : 0}  0 0 0 0 ${bg.grain_light ? 1 : 0}  0 0 0 0 ${bg.grain_light ? 1 : 0}  0 0 0 ${bg.grain} 0`}, f);
    node("rect", {x: 0, y: 0, width: W, height: H, filter: "url(#grain)"}, stage);
  }
  if (bg.vignette) {
    const g = node("radialGradient", {id: "vig", cx: "50%", cy: "42%", r: "75%"}, defs);
    node("stop", {offset: "60%", "stop-color": "#000", "stop-opacity": 0}, g);
    node("stop", {offset: "100%", "stop-color": "#000", "stop-opacity": bg.vignette}, g);
    node("rect", {x: 0, y: 0, width: W, height: H, fill: "url(#vig)"}, stage);
  }
  // Depth: a drop shadow (the "sticker" look of flat styles), or a glow
  // in each element's own colour (neon).
  const sh = STYLE.shadow;
  if (sh) {
    const f = node("filter", {id: "shadow", x: "-30%", y: "-30%", width: "160%", height: "160%"}, defs);
    node("feDropShadow", {dx: sh.dx || 0, dy: sh.dy || 8, stdDeviation: sh.blur || 0,
                          "flood-color": sh.color || "#000", "flood-opacity": sh.opacity == null ? 0.2 : sh.opacity}, f);
  }
  if (STYLE.glow) {
    const f = node("filter", {id: "glow", x: "-40%", y: "-40%", width: "180%", height: "180%"}, defs);
    node("feGaussianBlur", {in: "SourceGraphic", stdDeviation: STYLE.glow, result: "b"}, f);
    const m = node("feMerge", {}, f);
    node("feMergeNode", {in: "b"}, m); node("feMergeNode", {in: "b"}, m); node("feMergeNode", {in: "SourceGraphic"}, m);
  }
  const depth = sh ? "url(#shadow)" : STYLE.glow ? "url(#glow)" : null;
  // Hand-drawn wobble (chalk, ink): the whole drawing layer is displaced
  // by fixed-seed noise, so lines waver the same way on every frame.
  if (STYLE.sketch) {
    const f = node("filter", {id: "sketch", x: "-5%", y: "-5%", width: "110%", height: "110%"}, defs);
    node("feTurbulence", {type: "fractalNoise", baseFrequency: 0.035, numOctaves: 2, seed: 3, result: "n"}, f);
    node("feDisplacementMap", {in: "SourceGraphic", in2: "n", scale: STYLE.sketch, xChannelSelector: "R", yChannelSelector: "G"}, f);
  }
  const layer = node("g", STYLE.sketch ? {filter: "url(#sketch)"} : {}, stage);

  // --- geometry for anchors ------------------------------------------
  function starVertices(e) {
    const n = e.points || 5, pts = [];
    const rot = ((e.rotation || 0) - 90) * Math.PI / 180;
    for (let i = 0; i < n; i++) {
      const a = rot + i * 2 * Math.PI / n;
      pts.push([e.x + e.r * Math.cos(a), e.y + e.r * Math.sin(a)]);
    }
    return pts;
  }
  const byId = {};
  // Shape geometry, worked out before anything is drawn so anchors and
  // constructions ("the square on this side") can refer to it: each
  // shape's corner points (if it has corners) and its centre.
  const geom = {};
  const centroid = pts => [pts.reduce((s, p) => s + p[0], 0) / pts.length,
                           pts.reduce((s, p) => s + p[1], 0) / pts.length];
  for (const e of SCENE.elements) {
    if (e.type !== "shape") continue;
    let pts = null;
    if (e.kind === "star" || e.kind === "polygon") pts = starVertices(e);
    else if (e.kind === "poly") pts = (e.vertices || []).map(p => [p[0], p[1]]);
    else if (e.kind === "rect") pts = [[e.x - e.w / 2, e.y - e.h / 2], [e.x + e.w / 2, e.y - e.h / 2],
                                       [e.x + e.w / 2, e.y + e.h / 2], [e.x - e.w / 2, e.y + e.h / 2]];
    else if (e.kind === "square" && e.on && geom[e.on.of] && geom[e.on.of].pts) {
      // The square standing on one side of another shape, facing out.
      const base = geom[e.on.of], n = base.pts.length, i = e.on.edge % n;
      const p1 = base.pts[i], p2 = base.pts[(i + 1) % n];
      let nx = -(p2[1] - p1[1]), ny = p2[0] - p1[0];
      const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
      if ((mx + nx * 0.01 - base.cx) ** 2 + (my + ny * 0.01 - base.cy) ** 2
          < (mx - base.cx) ** 2 + (my - base.cy) ** 2) { nx = -nx; ny = -ny; }
      pts = [p1, p2, [p2[0] + nx, p2[1] + ny], [p1[0] + nx, p1[1] + ny]];
    }
    if (e.kind === "beam") pts = [[e.x, e.y], [e.x2, e.y2]];
    const [cx, cy] = pts && pts.length ? centroid(pts)
      : e.kind === "line" || e.kind === "arrow" ? [(e.x + e.x2) / 2, (e.y + e.y2) / 2] : [e.x, e.y];
    geom[e.id] = {pts, cx, cy};
  }
  // Where an element sits: its own x/y, or an anchor on another element:
  // a corner or a side's midpoint pushed outward from its centre, a
  // prop's top/bottom, or simply the other element's centre.
  function resolveXY(e) {
    const a = e.anchor;
    if (!a) return [e.x, e.y];
    const t = byId[a.of];
    if (!t) return [e.x || W / 2, e.y || H / 2];
    const gm = geom[a.of];
    let x = gm ? gm.cx : t.spec.x, y = gm ? gm.cy : t.spec.y;
    const pushOut = (px, py) => {
      const dx = px - x, dy = py - y, d = Math.hypot(dx, dy) || 1, push = a.offset || 0;
      return [px + dx / d * push, py + dy / d * push];
    };
    if (a.vertex != null && gm && gm.pts) {
      const v = gm.pts[a.vertex % gm.pts.length];
      [x, y] = pushOut(v[0], v[1]);
    } else if (a.edge != null && gm && gm.pts) {
      const n = gm.pts.length, p1 = gm.pts[a.edge % n], p2 = gm.pts[(a.edge + 1) % n];
      [x, y] = pushOut((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2);
    } else if (a.side) {
      const h = (t.spec.h || t.spec.w || 0) / 2;
      if (a.side === "top") y -= h;
      if (a.side === "bottom") y += h;
    }
    return [x + (a.dx || 0), y + (a.dy || 0)];
  }

  // --- builders -------------------------------------------------------
  // Each returns {g, spec, draw(p), extra(t)}; g carries the element's
  // transform and opacity, set by __seek.
  // Surface textures for areas (a brick wall, hatched ground), drawn in
  // the element's own stroke colour over its fill.
  const TEXTURES = {
    bricks: (pat, c) => { node("path", {d: "M 0 0.5 H 64 M 0 32.5 H 64 M 32 0 V 32 M 0 32 V 64 M 64 32 V 64",
                                        fill: "none", stroke: c, "stroke-width": 3, opacity: 0.8}, pat); },
    hatch: (pat, c) => { node("path", {d: "M -8 8 L 8 -8 M 0 64 L 64 0 M 56 72 L 72 56", fill: "none",
                                       stroke: c, "stroke-width": 3, opacity: 0.6}, pat); },
    planks: (pat, c) => { node("path", {d: "M 0 0.5 H 64 M 20 0 V 21 M 44 21 V 42 M 0 21.5 H 64 M 0 42.5 H 64 M 10 42 V 64",
                                        fill: "none", stroke: c, "stroke-width": 3, opacity: 0.7}, pat); },
  };
  let textureCount = 0;
  function textureFill(e) {
    const make = TEXTURES[e.texture];
    if (!make) return null;
    const id = `tex${textureCount++}`;
    const pat = node("pattern", {id, width: 64, height: 64, patternUnits: "userSpaceOnUse"}, defs);
    make(pat, color(e.stroke || "ink"));
    return `url(#${id})`;
  }
  function strokeAttrs(e) {
    return {
      stroke: color(e.stroke || "ink"),
      "stroke-width": e.width || STYLE.stroke_width || 10,
      "stroke-linecap": "round", "stroke-linejoin": "round",
      fill: e.fill ? color(e.fill) : "none",
    };
  }

  function drawable(path, e) {
    const len = path.getTotalLength ? path.getTotalLength() : 1000;
    path.setAttribute("stroke-dasharray", `${len} ${len}`);
    return p => {
      path.setAttribute("stroke-dashoffset", String(len * (1 - p)));
      const full = e.fill_opacity == null ? 1 : e.fill_opacity;
      if (e.fill) path.setAttribute("fill-opacity", String(full * clamp((p - 0.85) / 0.15)));
    };
  }

  function buildShape(e, g) {
    let d;
    if (e.kind === "circle") {
      d = `M ${e.x} ${e.y - e.r} A ${e.r} ${e.r} 0 1 1 ${e.x - 0.01} ${e.y - e.r} Z`;
    } else if (e.kind === "poly" || e.kind === "square") {
      const v = (geom[e.id] && geom[e.id].pts) || [[0, 0]];
      d = v.map((p, k) => `${k ? "L" : "M"} ${p[0]} ${p[1]}`).join(" ") + " Z";
    } else if (e.kind === "angle" && e.at && geom[e.at.of] && geom[e.at.of].pts) {
      // A corner mark: the small square of a right angle, or an arc.
      const v = geom[e.at.of].pts, n = v.length, i = e.at.vertex % n;
      const c = v[i], a = v[(i + n - 1) % n], b = v[(i + 1) % n], s = e.size || 44;
      const ua = [(a[0] - c[0]), (a[1] - c[1])], ub = [(b[0] - c[0]), (b[1] - c[1])];
      const la = Math.hypot(...ua) || 1, lb = Math.hypot(...ub) || 1;
      const pa = [c[0] + ua[0] / la * s, c[1] + ua[1] / la * s], pb = [c[0] + ub[0] / lb * s, c[1] + ub[1] / lb * s];
      d = e.right !== false
        ? `M ${pa} L ${pa[0] + ub[0] / lb * s} ${pa[1] + ub[1] / lb * s} L ${pb}`
        : `M ${pa} A ${s} ${s} 0 0 ${(ua[0] * ub[1] - ua[1] * ub[0]) > 0 ? 1 : 0} ${pb}`;
    } else if (e.kind === "star" || e.kind === "polygon") {
      const v = starVertices(e);
      // A star is drawn as one continuous line through every second
      // point, the way a pentagram is drawn by hand.
      const order = e.kind === "star"
        ? Array.from({length: v.length}, (_, i) => (i * 2) % v.length) : v.map((_, i) => i);
      d = order.map((i, k) => `${k ? "L" : "M"} ${v[i][0]} ${v[i][1]}`).join(" ") + " Z";
    } else if (e.kind === "line" || e.kind === "arrow") {
      d = `M ${e.x} ${e.y} L ${e.x2} ${e.y2}`;
    } else if (e.kind === "beam") {
      // A physical bar exactly between two points: a plank, pole or ramp,
      // or with rungs, a ladder. Drawn, not illustrated, so it lies
      // precisely on the geometry it stands for.
      const dx = e.x2 - e.x, dy = e.y2 - e.y, L = Math.hypot(dx, dy) || 1;
      const t = (e.thickness || 56) / 2, nx = -dy / L * t, ny = dx / L * t;
      const rail = s => `M ${e.x + nx * s} ${e.y + ny * s} L ${e.x2 + nx * s} ${e.y2 + ny * s}`;
      if (e.rungs) {
        const n = Math.max(2, Math.round(L / (e.spacing || 70)));
        d = rail(1) + " " + rail(-1);
        for (let i = 1; i < n; i++) {
          const px = e.x + dx * i / n, py = e.y + dy * i / n;
          d += ` M ${px + nx} ${py + ny} L ${px - nx} ${py - ny}`;
        }
      } else {
        d = `M ${e.x + nx} ${e.y + ny} L ${e.x2 + nx} ${e.y2 + ny} L ${e.x2 - nx} ${e.y2 - ny} `
          + `L ${e.x - nx} ${e.y - ny} Z`;
      }
    } else if (e.kind === "rect") {
      const r = e.radius || 24, x = e.x - e.w / 2, y = e.y - e.h / 2;
      d = `M ${x + r} ${y} H ${x + e.w - r} Q ${x + e.w} ${y} ${x + e.w} ${y + r} V ${y + e.h - r} `
        + `Q ${x + e.w} ${y + e.h} ${x + e.w - r} ${y + e.h} H ${x + r} Q ${x} ${y + e.h} ${x} ${y + e.h - r} `
        + `V ${y + r} Q ${x} ${y} ${x + r} ${y} Z`;
    } else {
      d = e.d || "M 0 0";
    }
    const path = node("path", {d, ...strokeAttrs(e)}, g);
    const setDraw = drawable(path, e);
    const tex = textureFill(e);
    let texPath = null;
    if (tex) {
      texPath = node("path", {d, fill: tex, stroke: "none"}, g);
      g.insertBefore(texPath, path);
    }
    let head = null;
    if (e.kind === "arrow") {
      const ang = Math.atan2(e.y2 - e.y, e.x2 - e.x), s = (e.width || STYLE.stroke_width || 10) * 3;
      const p1 = [e.x2 - s * Math.cos(ang - 0.5), e.y2 - s * Math.sin(ang - 0.5)];
      const p2 = [e.x2 - s * Math.cos(ang + 0.5), e.y2 - s * Math.sin(ang + 0.5)];
      head = node("path", {d: `M ${p1} L ${e.x2} ${e.y2} L ${p2}`, ...strokeAttrs({...e, fill: null})}, g);
    }
    return {draw: p => {
      setDraw(p);
      if (head) head.setAttribute("opacity", p > 0.97 ? 1 : 0);
      if (texPath) texPath.setAttribute("opacity", clamp((p - 0.85) / 0.15));
    }};
  }

  function buildLabel(e, g) {
    const size = e.size || STYLE.label_size || 64;
    const font = family(e.font === "text" ? STYLE.font_text : STYLE.font_display);
    const weight = e.font === "text" ? (STYLE.font_text_weight || 600) : (STYLE.font_display_weight || 800);
    const pill = e.pill !== false && e.style !== "title";
    const inner = node("g", {}, g);
    const bgRect = pill ? node("rect", {rx: STYLE.label_radius || 18, fill: color(e.fill || "label_fill"),
                                         stroke: color(e.stroke || "ink"), "stroke-width": STYLE.label_stroke || 5}, inner) : null;
    const txt = node("text", {"font-family": font, "font-weight": weight, "font-size": size,
                              fill: color(e.color || "ink"), "text-anchor": "middle",
                              "dominant-baseline": "central"}, inner);
    // `parts`: the text in coloured pieces, e.g. an equation whose terms
    // match the shapes they stand for. Written part by part.
    const parts = Array.isArray(e.parts) && e.parts.length ? e.parts : null;
    const spans = [];
    if (parts) {
      for (const part of parts) {
        const sp = node("tspan", {fill: color(part.color || e.color || "ink")}, txt);
        sp.textContent = part.text;
        spans.push(sp);
      }
      e = {...e, text: parts.map(q => q.text).join("")};
    } else {
      txt.textContent = e.text;
    }
    let dot = null;
    if (e.dot) dot = node("circle", {r: size * 0.2, fill: color(e.dot), stroke: color("ink"), "stroke-width": 4}, inner);
    const box = txt.getBBox();
    const padX = size * 0.45, padY = size * 0.22, dotW = dot ? size * 0.55 : 0;
    const w = box.width + padX * 2 + dotW, h = box.height + padY * 2;
    if (bgRect) { bgRect.setAttribute("x", -w / 2); bgRect.setAttribute("y", -h / 2);
                  bgRect.setAttribute("width", w); bgRect.setAttribute("height", h); }
    if (dot) { dot.setAttribute("cx", -w / 2 + padX * 0.7 + dotW * 0.25); dot.setAttribute("cy", 0);
               txt.setAttribute("x", dotW / 2); }
    // "write": the text appears as it's spoken, word by word.
    const words = String(e.text).split(" ");
    return {
      h, w,
      write: parts
        ? p => spans.forEach((sp, i) => sp.setAttribute("opacity", p >= 1 || i < Math.ceil(spans.length * p) ? 1 : 0))
        : p => {
          const shown = Math.ceil(words.length * p);
          txt.textContent = p >= 1 ? e.text : words.slice(0, shown).join(" ");
        },
    };
  }

  function buildProp(e, g) {
    const src = ASSETS[e.asset];
    const w = e.w || 300, h = e.h || w;
    if (src && e.span) {
      // Laid along two exact points (a ladder from the ground to the top
      // of a wall): the object's own long axis, whatever angle it was
      // drawn at, is turned onto the line and scaled to its length. The
      // "to" end is the object's top.
      const m = META[e.asset] || {w: 100, h: 100, cx: 50, cy: 50, angle: -Math.PI / 2, length: 100};
      const inner = node("g", {}, g);
      node("image", {href: src, x: 0, y: 0, width: m.w, height: m.h}, inner);
      return {h, w, span: (p1, p2) => {
        const L = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]) || 1;
        const turn = (Math.atan2(p2[1] - p1[1], p2[0] - p1[0]) - m.angle) * 180 / Math.PI;
        inner.setAttribute("transform", `rotate(${turn}) scale(${L / m.length}) translate(${-m.cx} ${-m.cy})`);
      }};
    }
    if (src) {
      // fit "cover" fills the box and crops (a wall, the ground); "fill"
      // stretches; the default keeps the whole object inside the box.
      const par = {cover: "xMidYMid slice", fill: "none"}[e.fit] || "xMidYMid meet";
      node("image", {href: src, x: -w / 2, y: -h / 2, width: w, height: h, preserveAspectRatio: par}, g);
    } else {
      // A missing prop is visible, not silent: the layout checker should
      // never let this through, and if it does, it shows.
      node("rect", {x: -w / 2, y: -h / 2, width: w, height: h, fill: "#f0f", opacity: 0.4}, g);
    }
    return {h, w};
  }

  function formatNumber(v, e) {
    const d = e.decimals || 0;
    const s = Number(v).toLocaleString("en-GB", {minimumFractionDigits: d, maximumFractionDigits: d});
    return `${e.prefix || ""}${s}${e.suffix || ""}`;
  }

  function buildCounter(e, g) {
    const size = e.size || 110;
    const txt = node("text", {"font-family": family(STYLE.font_display), "font-weight": STYLE.font_display_weight || 800,
                              "font-size": size, fill: color(e.color || "ink"), "text-anchor": "middle",
                              "dominant-baseline": "central", "font-variant-numeric": "tabular-nums"}, g);
    txt.textContent = formatNumber(e.from || 0, e);
    return {value: e.from || 0, set: v => { txt.textContent = formatNumber(v, e); }};
  }

  function buildChart(e, g) {
    const x0 = -e.w / 2, y0 = e.h / 2, sw = STYLE.stroke_width || 10;
    const axes = node("path", {d: `M ${x0} ${-e.h / 2} V ${y0} H ${e.w / 2}`, fill: "none",
                               stroke: color("ink"), "stroke-width": sw * 0.6, "stroke-linecap": "round"}, g);
    const vals = e.values || [0, 1], lo = Math.min(...vals, 0), hi = Math.max(...vals);
    const pts = vals.map((v, i) => [x0 + e.w * i / (vals.length - 1), y0 - e.h * (v - lo) / (hi - lo || 1)]);
    let setDraw;
    if (e.kind === "bar") {
      const bw = e.w / vals.length * 0.62, bars = [];
      vals.forEach((v, i) => {
        const bx = x0 + e.w * (i + 0.5) / vals.length - bw / 2;
        const fullH = e.h * (v - lo) / (hi - lo || 1);
        bars.push([node("rect", {x: bx, width: bw, rx: 10, fill: color(e.fill || "accent2"),
                                 stroke: color("ink"), "stroke-width": sw * 0.5}, g), fullH]);
      });
      setDraw = p => bars.forEach(([r, fullH], i) => {
        const q = EASE.out(clamp(p * bars.length - i * 0.6));
        r.setAttribute("height", fullH * q); r.setAttribute("y", y0 - fullH * q);
      });
    } else {
      const d = pts.map((p, i) => `${i ? "L" : "M"} ${p[0]} ${p[1]}`).join(" ");
      const line = node("path", {d, fill: "none", stroke: color(e.stroke || "accent1"), "stroke-width": sw,
                                 "stroke-linecap": "round", "stroke-linejoin": "round"}, g);
      const drawLine = drawable(line, {});
      const tip = node("circle", {r: sw * 1.1, fill: color(e.stroke || "accent1"), stroke: color("ink"), "stroke-width": 4}, g);
      setDraw = p => {
        drawLine(p);
        const at = line.getPointAtLength(line.getTotalLength() * p);
        tip.setAttribute("cx", at.x); tip.setAttribute("cy", at.y); tip.setAttribute("opacity", p > 0.01 ? 1 : 0);
      };
    }
    (e.axis_labels || []).forEach(lab => {
      const t = node("text", {"font-family": family(STYLE.font_text), "font-weight": STYLE.font_text_weight || 600,
                              "font-size": 38, fill: color("ink_soft"), "text-anchor": lab.align || "middle"}, g);
      t.setAttribute("x", lab.at === "end" ? e.w / 2 : x0); t.setAttribute("y", y0 + 56);
      t.textContent = lab.text;
    });
    void axes;
    return {draw: setDraw};
  }


  // --- maths: typeset expressions, plots, number lines ------------------
  // A small typesetter for a LaTeX-like subset, drawn in the channel's own
  // font and colours: \frac{a}{b}, \sqrt{x}, x^{2}, x_{1}, \color{accent1}{...}
  // and the usual symbols. Enough for school and popular maths, and it
  // always looks like the rest of the scene.
  const SYMBOLS = {times: " × ", div: " ÷ ", pm: " ± ", cdot: " · ", pi: "π", theta: "θ", le: " ≤ ",
                   ge: " ≥ ", ne: " ≠ ", approx: " ≈ ", infty: "∞", alpha: "α", beta: "β",
                   gamma: "γ", Delta: "Δ", sum: "Σ", to: "→", degree: "°", sqrt: null, frac: null,
                   color: null, percent: "%", lt: "<", gt: ">", quad: " ",
                   qquad: "  ", ",": " "};
  function parseTex(src) {
    let i = 0;
    function group() {                       // {...} or a single token
      if (src[i] === "{") {
        i++;
        const r = row("}");
        i++;
        return r;
      }
      return atom();
    }
    function atom() {
      if (src[i] === "\\") {
        let j = i + 1;
        while (j < src.length && /[A-Za-z]/.test(src[j])) j++;
        if (j === i + 1 && j < src.length) j++;      // a one-character command: \,
        const name = src.slice(i + 1, j);
        i = j;
        if (name === "frac") return {t: "frac", num: group(), den: group()};
        if (name === "sqrt") return {t: "sqrt", body: group()};
        if (name === "color") {
          const c = group();
          return {t: "color", c: flat(c), body: group()};
        }
        return {t: "text", s: SYMBOLS[name] || name};
      }
      const ch = src[i++];
      return {t: "text", s: "+-=×÷<>≤≥≈≠±".includes(ch) ? ` ${ch} ` : ch};
    }
    function flat(n) { return n.t === "text" ? n.s : (n.items || []).map(flat).join(""); }
    function row(end) {
      const items = [];
      while (i < src.length && src[i] !== end) {
        if (src[i] === " ") { i++; continue; }
        if (src[i] === "^" || src[i] === "_") {
          const kind = src[i++] === "^" ? "sup" : "sub";
          items.push({t: kind, base: items.pop() || {t: "text", s: ""}, script: group()});
          continue;
        }
        // A sign at the start of a group is unary: "-b", not "- b".
        const unary = !items.length && "+-".includes(src[i]);
        const next = atom();
        if (unary) next.s = next.s.trim();
        items.push(next);
      }
      return {t: "row", items};
    }
    return row(undefined);
  }
  // white-space: pre keeps the spaces round operators, in the measure and
  // in the drawing alike.
  const measurer = node("text", {"font-family": family(STYLE.font_display), opacity: 0,
                                 style: "white-space: pre"}, defs);
  function textWidth(str, size) {
    measurer.setAttribute("font-size", size);
    measurer.setAttribute("font-weight", STYLE.font_display_weight || 700);
    measurer.textContent = str;
    return measurer.getComputedTextLength();
  }
  function layoutTex(n, size, col) {
    if (n.t === "text") {
      const w = textWidth(n.s, size);
      return {w, asc: size * 0.74, desc: size * 0.22, draw: (g, x, y) => {
        const t = node("text", {x, y, "font-family": family(STYLE.font_display), "font-size": size,
                                "font-weight": STYLE.font_display_weight || 700, fill: color(col),
                                style: "white-space: pre"}, g);
        t.textContent = n.s;
      }};
    }
    if (n.t === "row") {
      const kids = n.items.map(k => layoutTex(k, size, col));
      return {w: kids.reduce((a, k) => a + k.w, 0), asc: Math.max(size * 0.74, ...kids.map(k => k.asc)),
              desc: Math.max(size * 0.22, ...kids.map(k => k.desc)),
              draw: (g, x, y) => { let cx = x; for (const k of kids) { k.draw(g, cx, y); cx += k.w; } }};
    }
    if (n.t === "color") return layoutTex(n.body, size, n.c);
    if (n.t === "sup" || n.t === "sub") {
      const base = layoutTex(n.base, size, col), sc = layoutTex(n.script, size * 0.62, col);
      const shift = n.t === "sup" ? -size * 0.42 : size * 0.18;
      return {w: base.w + sc.w + size * 0.04,
              asc: Math.max(base.asc, sc.asc - shift), desc: Math.max(base.desc, sc.desc + shift),
              draw: (g, x, y) => { base.draw(g, x, y); sc.draw(g, x + base.w + size * 0.04, y + shift); }};
    }
    if (n.t === "frac") {
      const num = layoutTex(n.num, size * 0.82, col), den = layoutTex(n.den, size * 0.82, col);
      const w = Math.max(num.w, den.w) + size * 0.3, axis = size * 0.3, gap = size * 0.12;
      return {w, asc: axis + gap + num.desc + num.asc, desc: -axis + gap + den.asc + den.desc,
              draw: (g, x, y) => {
                num.draw(g, x + (w - num.w) / 2, y - axis - gap - num.desc);
                den.draw(g, x + (w - den.w) / 2, y - axis + gap + den.asc);
                node("path", {d: `M ${x + size * 0.05} ${y - axis} H ${x + w - size * 0.05}`,
                              stroke: color(col), "stroke-width": Math.max(3, size * 0.06),
                              "stroke-linecap": "round"}, g);
              }};
    }
    if (n.t === "sqrt") {
      const body = layoutTex(n.body, size, col), lead = size * 0.55, over = size * 0.14;
      return {w: lead + body.w + size * 0.1, asc: body.asc + over, desc: body.desc,
              draw: (g, x, y) => {
                const top = y - body.asc - over * 0.5, sw = Math.max(3, size * 0.06);
                node("path", {d: `M ${x} ${y - size * 0.3} L ${x + lead * 0.3} ${y - size * 0.38} `
                                 + `L ${x + lead * 0.6} ${y + body.desc * 0.6} L ${x + lead} ${top} `
                                 + `H ${x + lead + body.w + size * 0.08}`,
                              fill: "none", stroke: color(col), "stroke-width": sw,
                              "stroke-linejoin": "round", "stroke-linecap": "round"}, g);
                body.draw(g, x + lead + size * 0.04, y);
              }};
    }
    return {w: 0, asc: 0, desc: 0, draw: () => {}};
  }
  function buildMath(e, g) {
    const size = e.size || 90;
    const box = layoutTex(parseTex(String(e.tex || "")), size, e.color || "ink");
    const inner = node("g", {}, g);
    box.draw(inner, -box.w / 2, (box.asc - box.desc) / 2);
    // "write" wipes it in left to right, as if written as it's said.
    const clipId = `mclip${e.id}`;
    const clip = node("clipPath", {id: clipId}, defs);
    const r = node("rect", {x: -box.w / 2 - 10, y: -box.asc - size, width: box.w + 20,
                            height: box.asc + box.desc + size * 2}, clip);
    inner.setAttribute("clip-path", `url(#${clipId})`);
    return {w: box.w, h: box.asc + box.desc, write: p => r.setAttribute("width", (box.w + 20) * p)};
  }

  function axisText(g, str, x, y, anchor) {
    const t = node("text", {x, y, "font-family": family(STYLE.font_text), "font-size": 34,
                            "font-weight": STYLE.font_text_weight || 600, fill: color("ink_soft"),
                            "text-anchor": anchor || "middle"}, g);
    t.textContent = str;
  }
  function niceStep(span) {
    const raw = span / 5, mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    return [1, 2, 5, 10].map(m => m * mag).find(v => v >= raw) || raw;
  }
  function buildPlot(e, g) {
    const w = e.w || 760, h = e.h || 560, sw = STYLE.stroke_width || 10;
    const [x0, x1] = e.x_range || [0, 10], [y0, y1] = e.y_range || [0, 10];
    const X = v => -w / 2 + w * (v - x0) / ((x1 - x0) || 1);
    const Y = v => h / 2 - h * (v - y0) / ((y1 - y0) || 1);
    const xs = e.x_step || niceStep(x1 - x0), ys = e.y_step || niceStep(y1 - y0);
    if (e.grid !== false) {
      for (let v = Math.ceil(x0 / xs) * xs; v <= x1 + 1e-9; v += xs)
        node("path", {d: `M ${X(v)} ${-h / 2} V ${h / 2}`, stroke: color("ink_soft"), "stroke-width": 2, opacity: 0.25}, g);
      for (let v = Math.ceil(y0 / ys) * ys; v <= y1 + 1e-9; v += ys)
        node("path", {d: `M ${-w / 2} ${Y(v)} H ${w / 2}`, stroke: color("ink_soft"), "stroke-width": 2, opacity: 0.25}, g);
    }
    const ax = Math.min(Math.max(0, x0), x1), ay = Math.min(Math.max(0, y0), y1);
    node("path", {d: `M ${-w / 2} ${Y(ay)} H ${w / 2} M ${X(ax)} ${h / 2} V ${-h / 2}`, fill: "none",
                  stroke: color("ink"), "stroke-width": sw * 0.5, "stroke-linecap": "round"}, g);
    const fmt = v => Number(v.toFixed(6)).toLocaleString("en-GB");
    for (let v = Math.ceil(x0 / xs) * xs; v <= x1 + 1e-9; v += xs)
      if (Math.abs(v - ax) > 1e-9) axisText(g, fmt(v), X(v), Y(ay) + 44);
    for (let v = Math.ceil(y0 / ys) * ys; v <= y1 + 1e-9; v += ys)
      if (Math.abs(v - ay) > 1e-9) axisText(g, fmt(v), X(ax) - 16, Y(v) + 12, "end");
    if (e.x_label) axisText(g, e.x_label, w / 2, Y(ay) + 92, "end");
    if (e.y_label) axisText(g, e.y_label, X(ax), -h / 2 - 24, "middle");
    const draws = (e.curves || []).map(c => {
      const pts = (c.points || []).map(q => [X(q[0]), Y(q[1])]);
      if (pts.length < 2) return () => {};
      const path = node("path", {d: pts.map((q, i) => `${i ? "L" : "M"} ${q[0]} ${q[1]}`).join(" "),
                                 fill: "none", stroke: color(c.color || "accent1"), "stroke-width": sw * 0.8,
                                 "stroke-linecap": "round", "stroke-linejoin": "round"}, g);
      return drawable(path, {});
    });
    const dots = (e.dots || []).map(d => {
      const dg = node("g", {opacity: 0}, g);
      node("circle", {cx: X(d.at[0]), cy: Y(d.at[1]), r: sw * 1.1, fill: color(d.color || "accent2"),
                      stroke: color("ink"), "stroke-width": 4}, dg);
      if (d.label) axisText(dg, d.label, X(d.at[0]) + 22, Y(d.at[1]) - 22, "start");
      return dg;
    });
    return {w, h, draw: p => {
      draws.forEach(f => f(p));
      dots.forEach(d => d.setAttribute("opacity", p >= 0.98 ? 1 : 0));
    }};
  }
  function buildNumberLine(e, g) {
    const w = e.w || 860, from = e.from == null ? 0 : e.from, to = e.to == null ? 10 : e.to;
    const step = e.step || niceStep(to - from), sw = STYLE.stroke_width || 10;
    const X = v => -w / 2 + w * (v - from) / ((to - from) || 1);
    const line = node("path", {d: `M ${-w / 2 - 20} 0 H ${w / 2 + 20}`, stroke: color("ink"),
                               "stroke-width": sw * 0.6, "stroke-linecap": "round", fill: "none"}, g);
    const drawLine = drawable(line, {});
    const ticks = node("g", {opacity: 0}, g);
    for (let v = from; v <= to + 1e-9; v += step) {
      node("path", {d: `M ${X(v)} -16 V 16`, stroke: color("ink"), "stroke-width": sw * 0.4}, ticks);
      axisText(ticks, Number(v.toFixed(6)).toLocaleString("en-GB"), X(v), 62);
    }
    const marks = (e.marks || []).map(m => {
      const mg = node("g", {opacity: 0}, g);
      node("circle", {cx: X(m.at), cy: 0, r: sw * 1.3, fill: color(m.color || "accent1"),
                      stroke: color("ink"), "stroke-width": 4}, mg);
      if (m.label) axisText(mg, m.label, X(m.at), -40);
      return mg;
    });
    return {w, h: 120, draw: p => {
      drawLine(p);
      ticks.setAttribute("opacity", clamp((p - 0.4) / 0.4));
      marks.forEach(m => m.setAttribute("opacity", p >= 0.98 ? 1 : 0));
    }};
  }

  const BUILDERS = {shape: buildShape, label: buildLabel, prop: buildProp, counter: buildCounter,
                    chart: buildChart, math: buildMath, plot: buildPlot, numberline: buildNumberLine};

  // --- build everything ----------------------------------------------
  const items = [];
  for (const spec of SCENE.elements) {
    const outer = node("g", {"data-id": spec.id}, layer);   // data-id: for tests and the layout check
    const g = node("g", {}, outer);            // animated transform lives on g
    if (depth && spec.shadow !== false && (spec.type !== "counter" || !sh)) g.setAttribute("filter", depth);
    const item = {spec, outer, g, actions: SCENE.actions.filter(a => a.target === spec.id)};
    byId[spec.id] = item;
    item.api = BUILDERS[spec.type](spec, g) || {};
    items.push(item);
  }
  // A point given as [x, y] or as an anchor on another element.
  const pointOf = p => Array.isArray(p) ? p : resolveXY({anchor: p});
  // Positions after every element exists, so anchors can refer forward.
  for (const it of items) {
    let [x, y] = it.spec.type === "shape" || it.spec.type === "chart" ? [0, 0] : resolveXY(it.spec);
    if (it.spec.span && it.api.span) {
      const p1 = pointOf(it.spec.span.from), p2 = pointOf(it.spec.span.to);
      [x, y] = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
      it.api.span([p1[0] - x, p1[1] - y], [p2[0] - x, p2[1] - y]);
    }
    it.base = [x, y];
    if (["chart", "plot", "numberline"].includes(it.spec.type)) it.base = [it.spec.x, it.spec.y];
    // A label with a pointer draws a leader line to what it names.
    if (it.spec.pointer) {
      const [px, py] = it.spec.pointer;
      it.leader = node("path", {d: `M ${x} ${y} L ${px} ${py}`, fill: "none", stroke: color("ink"),
                                "stroke-width": 5, "stroke-dasharray": "2 14", "stroke-linecap": "round"}, layer);
      layer.insertBefore(it.leader, it.outer);
    }
  }

  // "stack": copies of a prop drop one after another into a target.
  const stacks = [];
  for (const a of SCENE.actions.filter(a => a.do === "stack")) {
    const src = byId[a.target], into = byId[a.into];
    for (let i = 0; i < (a.count || 5); i++) {
      const outer = node("g", {}, layer), g = node("g", {}, outer);
      if (depth) g.setAttribute("filter", depth);
      BUILDERS[src.spec.type]({...src.spec, id: `${src.spec.id}_${i}`}, g);
      stacks.push({g, a, i, into});
    }
    layer.appendChild(into.outer);             // the target sits in front of what falls in
  }

  // --- __seek(t) -------------------------------------------------------
  function stateAt(it, t) {
    const s = {opacity: it.spec.start_visible ? 1 : 0, scale: 1, dx: 0, dy: 0, rot: 0, draw: it.spec.start_visible ? 1 : 0, write: 1};
    let hasEntry = false;
    for (const a of it.actions) {
      const p = progress(t, a);
      if (t < a.at && (a.do === "appear" || a.do === "draw" || a.do === "write")) { hasEntry = true; continue; }
      switch (a.do) {
        case "appear": {
          hasEntry = true;
          const how = a.style || "pop";
          if (how === "pop") { s.opacity = clamp(p * 4); s.scale = lerp(0.3, 1, easeFor("appear")(p)); }
          else if (how === "slide") { s.opacity = clamp(p * 2); s.dy = lerp(a.from_dy == null ? 120 : a.from_dy, 0, EASE.out(p)); }
          else if (how === "drop") { s.opacity = clamp(p * 5); s.dy = lerp(-500, 0, EASE.bounce(p)); }
          else { s.opacity = EASE.out(p); }
          break;
        }
        case "draw": hasEntry = true; s.opacity = 1; s.draw = easeFor("draw")(p); break;
        case "write": hasEntry = true; s.opacity = 1; s.write = p; break;
        case "move": {
          const e = easeFor("move")(p);
          s.dx = lerp(s.dx, a.to[0] - it.base[0], e); s.dy = lerp(s.dy, a.to[1] - it.base[1], e); break;
        }
        case "highlight": {
          if (t >= a.at && t <= a.at + (a.dur || 0.8)) s.scale *= 1 + 0.16 * Math.sin(Math.PI * p);
          break;
        }
        case "wiggle": {
          if (t >= a.at && t <= a.at + (a.dur || 0.8)) s.rot = 8 * Math.sin(p * Math.PI * 6) * (1 - p);
          break;
        }
        case "exit": if (t >= a.at) s.opacity *= 1 - EASE.out(p); break;
        // Turn about its own centre to `angle` degrees, and stay there:
        // how a rearrangement proof moves its pieces.
        case "rotate": if (t >= a.at) s.rot = lerp(s.rot, a.angle || 0, easeFor("move")(p)); break;
      }
    }
    if (!hasEntry) { s.opacity = 1; s.draw = 1; }
    return s;
  }

  // --- camera ------------------------------------------------------------
  // The drawing layer is filmed by a camera: a slow push-in across the
  // whole scene (so a finished picture never sits frozen), and "focus"
  // actions that glide in on an element, "reset" back out. The camera
  // looks at point F and puts it at screen point A, zoomed by Z.
  const A = [W / 2, 700];
  const DRIFT = STYLE.camera_drift == null ? 0.035 : STYLE.camera_drift;
  const camActions = SCENE.actions.filter(a => a.do === "focus" || a.do === "reset")
    .sort((a, b) => a.at - b.at);
  let centres = null;                  // each element's centre, measured once
  function centreOf(id) {
    if (!centres) {
      centres = {};
      window.__seek(SCENE.duration || 1, false);
      for (const it of items) {
        try {
          const b = it.outer.getBBox();
          centres[it.spec.id] = [b.x + b.width / 2, b.y + b.height / 2];
        } catch (err) { centres[it.spec.id] = A; }
      }
    }
    return centres[id] || A;
  }
  function cameraAt(t) {
    let f = A, z = 1;
    for (const a of camActions) {
      if (t < a.at) break;
      const p = easeFor("move")(progress(t, a));
      const target = a.do === "reset" ? A : centreOf(a.target);
      const zoom = a.do === "reset" ? 1 : (a.zoom || 1.35);
      f = [lerp(f[0], target[0], p), lerp(f[1], target[1], p)];
      z = lerp(z, zoom, p);
    }
    z *= 1 + DRIFT * clamp(t / (SCENE.duration || 1));
    return `translate(${A[0]} ${A[1]}) scale(${z}) translate(${-f[0]} ${-f[1]})`;
  }

  window.__seek = function (t, camera = true) {
    layer.setAttribute("transform", camera ? cameraAt(t) : "");
    for (const it of items) {
      // A template is only ever drawn through its copies (a stack's coins);
      // a hidden element only exists for others to anchor to.
      if (it.spec.template || it.spec.hidden) { it.outer.setAttribute("opacity", 0); continue; }
      const s = stateAt(it, t);
      const [x, y] = it.base;
      it.outer.setAttribute("opacity", s.opacity);
      if (it.spec.type === "shape") {
        const gm = geom[it.spec.id] || {cx: 0, cy: 0};
        it.g.setAttribute("transform", `translate(${gm.cx + s.dx} ${gm.cy + s.dy}) rotate(${s.rot}) `
          + `scale(${s.scale}) translate(${-gm.cx} ${-gm.cy})`);
      } else {
        it.g.setAttribute("transform", `translate(${x + s.dx} ${y + s.dy}) rotate(${s.rot}) scale(${s.scale})`);
      }
      if (it.api.draw) it.api.draw(s.draw);
      if (it.api.write) it.api.write(s.write);
      if (it.leader) it.leader.setAttribute("opacity", s.opacity);
      if (it.api.set) {                          // counters
        let v = it.spec.from || 0;
        for (const a of it.actions.filter(a => a.do === "count")) {
          if (t >= a.at) v = lerp(v, a.to, easeFor("count")(progress(t, a)));
        }
        it.api.set(v);
      }
    }
    for (const c of stacks) {
      const span = c.a.dur || 2, n = c.a.count || 5;
      const start = c.a.at + c.i * span / n, fall = Math.min(0.7, span / n * 1.4);
      const p = clamp((t - start) / fall);
      const [tx, ty] = c.into.base;
      const top = ty - (c.into.spec.h || c.into.spec.w || 300) * 0.42;
      const y = lerp(top - (c.a.height || 380), top, EASE.inout(p) * EASE.inout(p));
      // Fades in as it starts to fall; gone once it's "in".
      c.g.parentNode.setAttribute("opacity", t < start || p >= 1 ? 0 : clamp(p * 5));
      c.g.setAttribute("transform", `translate(${tx + (c.a.spread || 0) * ((c.i % 3) - 1)} ${y}) rotate(${p * 200 + c.i * 40}) scale(0.9)`);
      // The target jolts slightly as each one lands.
      if (p >= 1 && t < start + fall + 0.18) c.into.g.setAttribute("transform",
        `translate(${tx} ${ty + 10 * Math.sin((t - start - fall) / 0.18 * Math.PI)}) scale(1)`);
    }
  };

  // What the layout check needs: every element visible at time t, with
  // its on-screen box. Text boxes are measured on the text itself.
  // Measured without the camera: a close-up is on purpose, not "off screen".
  window.__layout = function (t) {
    window.__seek(t, false);
    const out = [];
    for (const it of items) {
      if (it.spec.template || it.spec.hidden || Number(it.outer.getAttribute("opacity")) < 0.05) continue;
      const r = it.outer.getBoundingClientRect();
      out.push({id: it.spec.id, type: it.spec.type, kind: it.spec.kind || "",
                box: [r.left, r.top, r.right, r.bottom]});
    }
    return out;
  };

  window.__seek(0);
  window.__ready = true;
};
document.fonts.ready.then(() => window.__start());
