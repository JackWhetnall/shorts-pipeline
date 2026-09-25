/*
 * The motion-template engine. A template is plain HTML/CSS; this sets
 * every animated element to exactly how it looks at time t, so frames are
 * deterministic and any one can be rendered alone (see pipeline.templates).
 *
 * An element animates by declaring, in data attributes:
 *   data-in="1.8"      when it enters (seconds)
 *   data-dur="0.5"     how long the entrance takes
 *   data-anim="rise"   rise | pop | fade | wipe | draw | grow | slide-left | slide-right | strike
 *   data-out="6.2"     (optional) when it leaves
 *   data-count-to="4322" with data-count-from / data-prefix / data-suffix /
 *                      data-decimals: a number that counts up as it enters
 * The engine sets CSS variables the stylesheet uses: --p (0..1 linear),
 * --e (eased, with overshoot for pop), --q (exit 0..1). The page gets --t
 * and --T (time and duration) for slow whole-frame motion.
 */
window.__start = function () {
  "use strict";
  const T = window.TEMPLATE_DURATION || 5;
  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const EASE = {
    out: t => 1 - Math.pow(1 - t, 3),
    inout: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    back: t => { const c1 = 1.7, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); },
  };
  const easeFor = anim => (anim === "pop" ? EASE.back : anim === "draw" || anim === "grow" ? EASE.inout : EASE.out);

  // Text that must fit its box shrinks until it does, once, before any
  // frame: nothing can overflow or run into its neighbour.
  document.querySelectorAll("[data-fit]").forEach(el => {
    const min = parseFloat(el.dataset.fit) || 24;
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (size > min && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
      size -= 2;
      el.style.fontSize = size + "px";
    }
  });

  const items = [...document.querySelectorAll("[data-in]")].map(el => ({
    el,
    at: parseFloat(el.dataset.in) || 0,
    dur: parseFloat(el.dataset.dur) || 0.5,
    out: el.dataset.out ? parseFloat(el.dataset.out) : null,
    anim: el.dataset.anim || "rise",
    count: el.dataset.countTo != null ? {
      from: parseFloat(el.dataset.countFrom || "0"), to: parseFloat(el.dataset.countTo),
      decimals: parseInt(el.dataset.decimals || "0", 10),
      prefix: el.dataset.prefix || "", suffix: el.dataset.suffix || "",
      dur: parseFloat(el.dataset.countDur || "1.4")} : null,
  }));
  // Lines that draw themselves: their length, measured once.
  items.filter(it => it.anim === "draw").forEach(it => {
    const len = it.el.getTotalLength ? it.el.getTotalLength() : 1000;
    it.len = len;
    it.el.style.strokeDasharray = `${len} ${len}`;
  });
  const fmt = (v, c) => c.prefix + Number(v).toLocaleString("en-GB",
      {minimumFractionDigits: c.decimals, maximumFractionDigits: c.decimals}) + c.suffix;

  window.__seek = function (t) {
    const root = document.documentElement.style;
    root.setProperty("--t", t.toFixed(4));
    root.setProperty("--T", String(T));
    for (const it of items) {
      const p = clamp((t - it.at) / it.dur);
      const e = easeFor(it.anim)(p);
      const q = it.out == null ? 0 : clamp((t - it.out) / 0.35);
      it.el.style.setProperty("--p", p.toFixed(4));
      it.el.style.setProperty("--e", e.toFixed(4));
      it.el.style.setProperty("--q", q.toFixed(4));
      it.el.classList.toggle("is-on", p > 0);
      if (it.len != null) it.el.style.strokeDashoffset = String(it.len * (1 - e));
      if (it.count) {
        const cp = EASE.out(clamp((t - it.at) / it.count.dur));
        it.el.textContent = fmt(it.count.from + (it.count.to - it.count.from) * cp, it.count);
      }
    }
  };
  // What a frame at t would look like, without drawing it: every
  // element's progress. A page whose background doesn't drift
  // (STATIC_BACKGROUND) looks the same whenever this is the same, so the
  // encoder can reuse the last frame instead of taking a screenshot. A
  // quiz board is still for most of its two minutes.
  window.__signature = window.STATIC_BACKGROUND ? function (t) {
    return items.map(it => {
      const p = clamp((t - it.at) / it.dur);
      const q = it.out == null ? 0 : clamp((t - it.out) / 0.35);
      const c = it.count ? clamp((t - it.at) / it.count.dur) : 0;
      return p.toFixed(3) + q.toFixed(3) + c.toFixed(3);
    }).join("|");
  } : null;
  window.__seek(0);
  window.__ready = true;
};
document.fonts.ready.then(() => window.__start());
