// Every request goes through here so the CSRF token is attached in one
// place rather than at each of the seventeen call sites below — and so a
// new call site can't forget it.
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || "";

function apiFetch(url, options = {}) {
  const opts = {...options};
  opts.headers = {...(opts.headers || {})};
  if ((opts.method || "GET").toUpperCase() !== "GET") {
    opts.headers["X-CSRF-Token"] = CSRF_TOKEN;
  }
  return fetch(url, opts);
}

// Vanilla JS, no build step — matches the rest of this project's
// zero-dependency-tooling style.

let currentSeed = null;
let pollTimer = null;
let seenLogLength = 0;
let currentJobId = null;

// Shared setup for the progress card, used by startGenerate, resuming an
// active job, and showing a past interrupted/failed one - one place so
// all three can never drift out of sync on what "starting fresh" resets.
function showJobProgressView() {
  document.getElementById("seed-idle").classList.add("hidden");
  // #seed-preview only exists for a channel with no topic table (a quote
  // channel, or a topic channel with no plan) - a curriculum channel's
  // preview lives in #topic-preview, inside #seed-idle, already hidden
  // by the line above.
  document.getElementById("seed-preview")?.classList.add("hidden");
  document.getElementById("job-progress").classList.remove("hidden");
  seenLogLength = 0;
  document.getElementById("job-log").textContent = "";
  resetStageTracker();
  resetDetailPanel();
  hideJobBanner();
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// Swaps a button's contents for a spinner + label while an async action
// runs, restoring the original afterward — used anywhere a click kicks
// off a real API call (Voice Lab test, seed fetch/generate).
function withButtonLoading(button, loadingLabel, action) {
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span> ${loadingLabel}`;
  return Promise.resolve(action()).finally(() => {
    button.disabled = false;
    button.innerHTML = original;
  });
}

// What the create-video table is currently asking for. Absent table (a
// quote channel, or a topic channel with no plan) means "next", which is
// what fetch_seed does with no pick at all. The default selection IS the
// ordering policy's own pick, so sticking with it sends no pick at all
// too — letting fetch_seed re-resolve it itself, which matters when
// subtopic order is random: a topic-scoped next_pending isn't the same
// thing as what the policy actually chose.
function currentPick() {
  const table = document.getElementById("topic-table");
  if (!table || !table.dataset.selectedTopic) return {};
  if (table.dataset.selectedTopic === table.dataset.defaultTopic) return {};
  return {topic_id: table.dataset.selectedTopic};
}

async function getSeed(channelKey) {
  const pick = currentPick();
  await withButtonLoading(event.target.closest("button"), "Fetching…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/seed`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(pick),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to fetch a candidate.");
      return;
    }
    currentSeed = data.seed;

    const previewEl = document.getElementById("seed-preview-text");
    if (currentSeed.type === "quote") {
      previewEl.innerHTML =
        `<p><strong>Quote:</strong> ${escapeHtml(currentSeed.text)}</p>` +
        `<p><strong>Reference:</strong> ${escapeHtml(currentSeed.reference)}</p>`;
    } else {
      previewEl.innerHTML = `<p><strong>Topic:</strong> ${escapeHtml(currentSeed.topic)}</p>`;
    }

    // Whether this passage has come up before. Readable filenames make
    // repeats visible when browsing the output folder, but not here —
    // which is the one moment the answer actually changes a decision.
    const history = data.history || {};
    if (history.count) {
      previewEl.innerHTML +=
        `<p class="meta seed-repeat">Already used ${history.count} time${history.count === 1 ? "" : "s"}` +
        `${history.last ? ", most recently " + escapeHtml(history.last) : ""}. Reroll for something new.</p>`;
    }

    // A fully-specific pick (a named subtopic) has nothing to reroll —
    // rerolling would fetch the exact same thing again. Showing it with
    // a Reroll button reads as "here's a candidate we picked," when it's
    // actually just confirming the one thing you already chose.
    const isSpecific = Boolean(pick.subtopic_id);
    document.getElementById("seed-reroll-btn").hidden = isSpecific;
    document.getElementById("seed-use-btn").textContent = isSpecific ? "Confirm" : "Use this";

    document.getElementById("seed-idle").classList.add("hidden");
    document.getElementById("seed-preview").classList.remove("hidden");
  });
}

async function startGenerate(channelKey) {
  if (!currentSeed) return;
  await withButtonLoading(event.target.closest("button"), "Starting…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/generate`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({seed: currentSeed}),
    });
    const data = await res.json();
    if (res.status === 409) {
      alert("A generation job is already running — wait for it to finish first.");
      return;
    }
    if (!res.ok) {
      alert(data.error || "Failed to start the job.");
      return;
    }

    currentJobId = data.job_id;
    showJobProgressView();
    pollJob(data.job_id);
  });
}

// Resumes the progress view if a job's already running/queued for this
// channel (e.g. you navigated away mid-generation and came back) instead
// of always starting from the idle "get a candidate" state - the job
// itself kept running the whole time as a background thread, only the
// page's connection to it was lost. Failing that, checks for a recent
// interrupted/failed job worth offering to retry - nothing else on this
// page would otherwise tell you one exists, since its id was never
// exposed anywhere you could navigate back to.
async function resumeRunningJob() {
  const marker = document.getElementById("create-video-page");
  if (!marker) return;
  const channelKey = marker.dataset.channelKey;
  try {
    const res = await apiFetch(`/api/channels/${channelKey}/current-job`);
    if (res.ok) {
      const data = await res.json();
      if (data.job) {
        currentJobId = data.job.id;
        showJobProgressView();
        pollJob(data.job.id);
        return;
      }
    }
  } catch (err) {
    // fall through to checking for a past failed/interrupted job
  }

  try {
    const res = await apiFetch(`/api/channels/${channelKey}/last-failed-job`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.job) return;
    currentJobId = data.job.id;
    showJobProgressView();
    updateStageTracker(data.job);
    updateDetailPanel(data.job);
    const heading = document.getElementById("job-heading");
    if (heading) heading.textContent = data.job.status === "interrupted" ? "Interrupted" : "Failed";
    showJobBanner(data.job.error, true);
    const logEl = document.getElementById("job-log");
    if (data.job.log && data.job.log.length) {
      logEl.textContent = data.job.log.join("\n") + "\n" + (data.job.error_traceback || "");
      seenLogLength = data.job.log.length;
    }
  } catch (err) {
    // fall back to the idle state
  }
}

document.addEventListener("DOMContentLoaded", resumeRunningJob);

// Drives the 5-card stage tracker (Script/Voiceover/Footage/Assembling/
// Finishing) from job.stage (0..STAGE_COUNT, monotonic - see
// core/job_context.py's STAGES list). A stage is "done" once job.stage has
// moved past it, "active" while it's the current stage, "pending"
// otherwise. The Assembling card additionally shows the real determinate
// progress bar once job.progress_percent has a value (the encode step is
// the only stage that reports a real percentage); before that it shows
// an indeterminate fill, same as the home page's per-channel cards.
const STAGE_COUNT = 5;

function updateStageTracker(job) {
  const stage = job.stage || 0;
  for (let i = 1; i <= STAGE_COUNT; i++) {
    const item = document.querySelector(`.stage-item[data-stage="${i}"]`);
    if (!item) continue;
    item.classList.remove("pending", "active", "done");
    item.classList.add(stage > i ? "done" : stage === i ? "active" : "pending");
  }
  for (let i = 1; i < STAGE_COUNT; i++) {
    const line = document.querySelector(`.stage-line[data-stage-line="${i}"]`);
    if (line) line.classList.toggle("done", stage > i);
  }
  const bar = document.getElementById("assembling-progress-bar");
  const fill = document.getElementById("assembling-progress-fill");
  if (bar && fill) {
    if (stage === 4) {
      bar.hidden = false;
      const hasPercent = job.progress_percent !== null && job.progress_percent !== undefined;
      fill.classList.toggle("indeterminate", !hasPercent);
      fill.style.width = hasPercent ? `${job.progress_percent}%` : "";
    } else {
      bar.hidden = true;
    }
  }
}

function resetStageTracker() {
  updateStageTracker({stage: 0, progress_percent: null});
}

// Small colored dot for a binary-ish status - used for the per-segment
// voiceover list, which genuinely only has one meaningful transition
// (synthesizing -> done). "done" is green, not the same gold as "active",
// so a finished row doesn't read as indistinguishable from one still in
// progress; "error" is red.
function statusDot(status) {
  const cls = status === "done" ? "done" : status === "active" ? "active" : status === "error" ? "error" : "pending";
  return `<span class="detail-dot detail-dot-${cls}"></span>`;
}

// Per-clip footage progress is a real multi-step pipeline (download,
// normalize, analyze/describe, done) - a genuine progress bar with a
// text label of the current step reads far better than two same-colored
// dots that looked identical whether a step was active or finished.
const FOOTAGE_STEPS = ["queued", "downloading", "normalizing", "analyzing", "done"];
const FOOTAGE_STEP_LABELS = {
  queued: "Queued", downloading: "Downloading", normalizing: "Normalizing",
  analyzing: "Analyzing", done: "Done", failed: "Failed",
};

function footageStepInfo(step) {
  const failed = step === "failed";
  const idx = FOOTAGE_STEPS.indexOf(step || "queued");
  const percent = failed ? 100 : ((idx === -1 ? 0 : idx) / (FOOTAGE_STEPS.length - 1)) * 100;
  return {label: FOOTAGE_STEP_LABELS[step] || "Queued", percent, done: step === "done", failed};
}

// The "Details" box between the stage tracker and the raw log - more
// granular than the 5-card tracker (which only tracks stage), less noisy
// than the full text log. Fed by job.detail, which pipeline code builds
// up via job_context.report_detail (see core/jobs.py's _update_detail
// and pipeline/tts.py and pipeline/footage/library.py calling report_detail). Re-rendered
// from scratch every poll tick - cheap at this size - but a full innerHTML
// replace resets any scrolled sub-element back to the top, which is
// exactly the "scrolling the clip tower jumps back to the top" bug this
// was built to avoid; the tower's scrollTop is captured before the
// replace and restored after.
function updateDetailPanel(job) {
  const wrap = document.getElementById("job-detail-details");
  const container = document.getElementById("job-detail-content");
  if (!wrap || !container) return;
  const detail = job.detail || {};

  const existingTower = container.querySelector(".detail-tower");
  const towerScrollTop = existingTower ? existingTower.scrollTop : 0;

  let html = "";

  const tts = detail.tts;
  if (tts && tts.items && tts.items.length) {
    const doneCount = tts.items.filter((it) => it.status === "done").length;
    html += `<div class="detail-block">`;
    html += `<p class="detail-block-title">Voiceover &middot; ${doneCount}/${tts.total || tts.items.length} segment(s)</p>`;
    html += `<ul class="detail-list">`;
    tts.items.forEach((it) => {
      html += `<li class="detail-list-item">${statusDot(it.status)}<span>${escapeHtml(it.preview || "")}</span></li>`;
    });
    html += `</ul></div>`;
  }

  const footage = detail.footage;
  if (footage && (footage.total_shots || (footage.items && footage.items.length))) {
    html += `<div class="detail-block">`;
    if (footage.total_shots) {
      html += `<p class="detail-block-title">Footage &middot; ${footage.total_shots} shot${footage.total_shots === 1 ? "" : "s"} needed</p>`;
    }
    if (footage.items && footage.items.length) {
      const count = footage.total_candidates || footage.items.length;
      const roundLabel = footage.round ? ` (round ${footage.round}/${footage.total_rounds || "?"})` : "";
      html += `<p class="meta">Fetching ${count} clip${count === 1 ? "" : "s"}${roundLabel} — a failed clip (red) is skipped automatically, nothing to do:</p>`;
      html += `<ul class="detail-list detail-tower">`;
      footage.items.forEach((it) => {
        const info = footageStepInfo(it.step);
        html += `<li class="detail-tower-item">
          <div class="detail-tower-row-top">
            <span class="detail-tower-label">${escapeHtml(it.query || "")}</span>
            <span class="detail-tower-step-text ${info.done ? "done" : ""} ${info.failed ? "failed" : ""}">${info.label}</span>
          </div>
          <div class="job-progress-bar-track detail-tower-bar-track">
            <div class="job-progress-bar-fill ${info.done ? "done" : ""} ${info.failed ? "failed" : ""}" style="width: ${info.percent}%"></div>
          </div>
        </li>`;
      });
      html += `</ul>`;
    }
    html += `</div>`;
  }

  container.innerHTML = html;
  wrap.classList.toggle("hidden", html === "");

  const newTower = container.querySelector(".detail-tower");
  if (newTower) newTower.scrollTop = towerScrollTop;
}

function resetDetailPanel() {
  const container = document.getElementById("job-detail-content");
  if (container) container.innerHTML = "";
  const wrap = document.getElementById("job-detail-details");
  if (wrap) wrap.classList.add("hidden");
}

function showJobBanner(message, retryable) {
  const el = document.getElementById("job-banner");
  const msgEl = document.getElementById("job-banner-message");
  const btn = document.getElementById("job-retry-btn");
  if (!el) return;
  if (msgEl) msgEl.textContent = message;
  el.classList.remove("hidden");
  if (btn) btn.classList.toggle("hidden", !retryable);
}

function hideJobBanner() {
  const el = document.getElementById("job-banner");
  if (el) el.classList.add("hidden");
  const btn = document.getElementById("job-retry-btn");
  if (btn) btn.classList.add("hidden");
}

// Re-runs the currently-viewed job in place, reusing whatever it already
// completed (script/voiceover/footage picks - see core/jobs.py's
// retry_job and the checkpointing in pipeline/run.py, tts.py and
// footage/library.py) rather than starting over from nothing. Available
// on both a live "error"/"interrupted" job (shown by pollJob below) and
// a past one surfaced on page load (resumeRunningJob).
async function retryCurrentJob() {
  if (!currentJobId) return;
  const btn = document.getElementById("job-retry-btn");
  await withButtonLoading(btn, "Retrying…", async () => {
    let res;
    try {
      res = await apiFetch(`/api/jobs/${currentJobId}/retry`, {method: "POST"});
    } catch (err) {
      alert("Couldn't reach the server to retry this job.");
      return;
    }
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to retry this job.");
      return;
    }
    showJobProgressView();
    pollJob(currentJobId);
  });
}

let pollFailCount = 0;
const MAX_POLL_FAILURES = 4;

// A poll that never resolves into a visible state is exactly the "job
// just hangs, no error" failure mode this was built to avoid - it
// happened for real when the dev server behind an in-flight job got
// restarted mid-generation. Two layers now cover that: the job registry
// itself persists to disk and reloads at startup (see core/jobs.py's
// load_persisted_jobs), so a job that was running when the server died
// comes back as a real "interrupted" status - a 404 from here should
// now only mean a genuinely bogus/nonexistent id, not "the server
// restarted." Either way: a 404 fails immediately (never worth
// retrying); a network error or non-2xx gets a few retries in case it's
// a momentary blip, then gives up loudly instead of hanging silently.
function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollFailCount = 0;
  pollTimer = setInterval(async () => {
    let res;
    try {
      res = await apiFetch(`/api/jobs/${jobId}`);
    } catch (err) {
      pollFailCount++;
      if (pollFailCount >= MAX_POLL_FAILURES) {
        clearInterval(pollTimer);
        showJobBanner("Lost connection while checking on this job — the server may be unreachable. Check the gallery to see if a video was produced, or go back and start a new one.");
      }
      return;
    }
    if (res.status === 404) {
      clearInterval(pollTimer);
      showJobBanner("This job no longer exists. Check the gallery to see if a video was produced, or go back and start a new one.");
      return;
    }
    if (!res.ok) {
      pollFailCount++;
      if (pollFailCount >= MAX_POLL_FAILURES) {
        clearInterval(pollTimer);
        showJobBanner(`Lost connection to this job (server returned ${res.status}). Check the gallery, or start a new one.`);
      }
      return;
    }
    pollFailCount = 0;
    const job = await res.json();

    currentJobId = jobId;
    const heading = document.getElementById("job-heading");
    const queueNote = document.getElementById("job-queue-note");
    if (job.status === "queued") {
      if (heading) heading.textContent = "Queued…";
      if (queueNote) {
        queueNote.textContent = job.queue_position
          ? `Waiting for another video to finish first — position ${job.queue_position} in the queue.`
          : "Waiting for another video to finish first.";
        queueNote.classList.remove("hidden");
      }
    } else {
      if (heading) heading.textContent = job.status === "interrupted" ? "Interrupted" : "Generating…";
      if (queueNote) queueNote.classList.add("hidden");
    }

    // "Should I wait or come back later?" - answered here rather than
    // only on Activity, since this is where someone who just pressed
    // the button is looking.
    const etaEl = document.getElementById("job-eta");
    if (etaEl) {
      etaEl.textContent = job.eta_label ? `${job.eta_label} left` : "";
      etaEl.classList.toggle("hidden", !job.eta_label);
    }

    updateStageTracker(job);
    updateDetailPanel(job);

    const logEl = document.getElementById("job-log");
    if (job.log.length > seenLogLength) {
      logEl.textContent += job.log.slice(seenLogLength).join("\n") + "\n";
      seenLogLength = job.log.length;
      logEl.scrollTop = logEl.scrollHeight;
    }
    const currentEl = document.getElementById("job-current");
    if (currentEl) currentEl.textContent = job.current_progress || "";

    if (job.status === "done") {
      clearInterval(pollTimer);
      window.location.href = `/channels/${job.channel_key}/videos/${job.result_path_rel}`;
    } else if (job.status === "error" || job.status === "interrupted") {
      // job.error is a plain-English summary (core/jobs.py's
      // _friendly_error / load_persisted_jobs) - shown prominently in
      // the banner. The raw traceback (if any - an "interrupted" job has
      // none, it wasn't a code failure) goes only into the collapsed
      // log, for anyone who actually needs it.
      clearInterval(pollTimer);
      if (job.error_traceback) {
        logEl.textContent += "\n--- ERROR ---\n" + job.error_traceback;
        document.getElementById("job-log-details").open = true;
      }
      showJobBanner(job.error || "Something went wrong.", true);
    }
  }, 1000);
}

// --- Voice Lab ---

async function refreshVoiceList() {
  await withButtonLoading(event.target.closest("button"), "Refreshing…", async () => {
    const res = await apiFetch("/api/voice-lab/refresh-voices", {method: "POST"});
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to refresh the voice list.");
      return;
    }
    location.reload();
  });
}

async function testVoiceCombo() {
  const voiceInput = document.querySelector('input[name="voice_id"]:checked');
  if (!voiceInput) {
    alert("Pick a voice first.");
    return;
  }
  const voiceId = voiceInput.value;
  const preset = document.getElementById("preset-select").value;
  const speed = parseFloat(document.getElementById("speed-slider").value);

  await withButtonLoading(event.target.closest("button"), "Generating… (first time for this combo can take a bit)", async () => {
    const res = await apiFetch("/api/voice-lab/test", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({voice_id: voiceId, preset, speed}),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to generate the test snippet.");
      return;
    }
    document.getElementById("voice-lab-result").classList.remove("hidden");
    const audio = document.getElementById("voice-lab-audio");
    audio.src = data.sample_url;
    audio.play();
    document.getElementById("voice-lab-combo-summary").textContent =
      `voice_id=${voiceId}  preset=${preset}  speed=${speed.toFixed(2)}`;
  });
}

// --- Logo generation ---

async function generateLogos(channelKey) {
  const fragmentInput = document.getElementById("logo-fragment");
  const fragment = fragmentInput.value.trim();
  if (!fragment) {
    alert("Describe what the channel is about first.");
    return;
  }
  const button = event.target.closest("button");
  const count = button.dataset.count || "5";

  await withButtonLoading(button, `Generating ${count} ideas… (this takes a little while)`, async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/logo/generate`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({fragment}),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to generate logo candidates.");
      return;
    }

    const grid = document.getElementById("logo-candidates-grid");
    grid.innerHTML = "";
    for (const candidate of data.candidates) {
      const el = document.createElement("img");
      el.src = candidate.url;
      el.className = "logo-candidate";
      el.onclick = () => selectLogo(channelKey, candidate.filename, el);
      grid.appendChild(el);
    }
    document.getElementById("logo-candidates").classList.remove("hidden");
  });
}

async function selectLogo(channelKey, filename, imgEl) {
  document.querySelectorAll(".logo-candidate").forEach(el => el.classList.remove("selected"));
  imgEl.classList.add("selected");
  imgEl.style.opacity = "0.5";

  // Just a file copy server-side now (no more API calls) — should return
  // almost instantly, but the opacity dip above gives feedback either way
  // so this never again looks like clicking a candidate did nothing.
  const res = await apiFetch(`/api/channels/${channelKey}/logo/select`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({filename}),
  });
  const data = await res.json();
  if (!res.ok) {
    imgEl.style.opacity = "1";
    alert(data.error || "Failed to finalize the logo.");
    return;
  }
  location.href = data.redirect;
}

// --- Merch logo variants ---

async function generateMerchVariants(channelKey) {
  await withButtonLoading(event.target.closest("button"), "Generating minimalist versions… (takes a minute or two)", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/logo/variants/generate`, {method: "POST"});
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to generate merch versions.");
      return;
    }

    const grid = document.getElementById("merch-variants-grid");
    grid.innerHTML = "";
    for (const variant of data.variants) {
      const wrap = document.createElement("div");
      const img = document.createElement("img");
      img.src = variant.url;
      img.className = "logo-preview";
      const label = document.createElement("p");
      label.className = "meta";
      label.textContent = variant.label;
      wrap.appendChild(img);
      wrap.appendChild(label);
      grid.appendChild(wrap);
    }
    document.getElementById("merch-variants").classList.remove("hidden");
  });
}

// --- Home page: channel section drag-reorder ---
// Off by default (a stray drag shouldn't silently reorder channels) —
// toggled on via the "Reorder" button, which flips `reorderMode` and
// sets `draggable` on every card. Reordering only ever happens WITHIN one
// section's grid (cross-section moves are the "Move to" dropdown's job,
// never dragging), so each grid only ever needs to know its own cards'
// current order.

let reorderMode = false;
let draggedCard = null;

function toggleReorderMode() {
  reorderMode = !reorderMode;
  const wrapper = document.getElementById("channel-sections");
  if (!wrapper) return;
  wrapper.classList.toggle("reorder-active", reorderMode);
  wrapper.querySelectorAll(".channel-card").forEach(card => {
    card.draggable = reorderMode;
  });
  const btn = document.getElementById("reorder-toggle-btn");
  if (btn) btn.classList.toggle("active", reorderMode);
}

// .channel-grid is a multi-column CSS grid, not a simple vertical list —
// so "where should the dragged card land" has to compare the cursor
// against every OTHER card's center point (nearest wins), not just walk
// down a single column comparing Y alone.
function _closestCard(grid, x, y) {
  const cards = [...grid.querySelectorAll(".channel-card:not(.dragging)")];
  let closest = {distance: Infinity, element: null, after: false};
  for (const card of cards) {
    const box = card.getBoundingClientRect();
    const cx = box.left + box.width / 2;
    const cy = box.top + box.height / 2;
    const distance = Math.hypot(x - cx, y - cy);
    if (distance < closest.distance) {
      closest = {distance, element: card, after: x > cx};
    }
  }
  return closest;
}

function initChannelReorder() {
  document.querySelectorAll(".channel-grid[data-section]").forEach(grid => {
    grid.addEventListener("dragstart", e => {
      const card = e.target.closest(".channel-card");
      if (!reorderMode || !card) return;
      draggedCard = card;
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    grid.addEventListener("dragend", () => {
      if (draggedCard) draggedCard.classList.remove("dragging");
      draggedCard = null;
    });
    grid.addEventListener("dragover", e => {
      if (!reorderMode || !draggedCard) return;
      e.preventDefault();
      const closest = _closestCard(grid, e.clientX, e.clientY);
      if (!closest.element || closest.element === draggedCard) return;
      if (closest.after) {
        closest.element.after(draggedCard);
      } else {
        closest.element.before(draggedCard);
      }
    });
    grid.addEventListener("drop", async e => {
      if (!reorderMode) return;
      e.preventDefault();
      const keys = [...grid.querySelectorAll(".channel-card")].map(c => c.dataset.key);
      try {
        await apiFetch("/api/channels/reorder", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({keys}),
        });
      } catch (err) {
        alert("Failed to save the new order.");
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", initChannelReorder);

// --- Home page: quick-generate, generate-all, per-card progress bars ---

async function quickGenerate(event, channelKey) {
  // This button lives on top of the card's stretched-link overlay - stop
  // the click from also navigating to the dashboard.
  event.preventDefault();
  event.stopPropagation();
  await withButtonLoading(event.target.closest("button"), "Starting…", async () => {
    const res = await apiFetch(`/channels/${channelKey}/generate-now`, {method: "POST"});
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to start generation.");
      return;
    }
    location.reload();
  });
}

async function generateAll() {
  await withButtonLoading(event.target.closest("button"), "Starting…", async () => {
    const res = await apiFetch("/api/channels/generate-all", {method: "POST"});
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to start generation.");
      return;
    }
    if (data.started.length === 0) {
      alert("No eligible channels right now — Live channels with nothing unpublished, and no job already running.");
      return;
    }
    location.reload();
  });
}

let homeJobPollTimer = null;

function initHomeJobPolling() {
  const bars = document.querySelectorAll(".job-progress-bar[data-job-id]");
  if (bars.length === 0) return;

  homeJobPollTimer = setInterval(async () => {
    const currentBars = document.querySelectorAll(".job-progress-bar[data-job-id]");
    if (currentBars.length === 0) {
      clearInterval(homeJobPollTimer);
      return;
    }
    for (const bar of currentBars) {
      const jobId = bar.dataset.jobId;
      let job;
      try {
        const res = await apiFetch(`/api/jobs/${jobId}`);
        if (res.status === 404) {
          // The job this card was tracking no longer exists server-side
          // (e.g. a restart) - reloading is the simplest way to stop
          // silently polling a dead id forever and show real state again.
          location.reload();
          return;
        }
        if (!res.ok) continue;
        job = await res.json();
      } catch (err) {
        continue;
      }
      if (job.status === "done" || job.status === "error" || job.status === "interrupted") {
        // Simplest correct way to transition this card back to normal
        // AND pick up any section-membership change from the server.
        // "interrupted" happens live here too: a job this card was
        // tracking as running can flip to interrupted mid-poll if the
        // server restarts (see core/jobs.py's load_persisted_jobs).
        location.reload();
        return;
      }
      const fill = bar.querySelector(".job-progress-bar-fill");
      const label = bar.querySelector(".job-progress-label");
      bar.classList.toggle("job-progress-bar-queued", job.status === "queued");
      if (job.status === "queued") {
        fill.classList.remove("indeterminate");
        fill.style.width = "0%";
        if (label) label.textContent = job.queue_position ? `Queued · position ${job.queue_position}` : "Queued";
        continue;
      }
      if (label) label.textContent = "Generating…";
      if (job.progress_percent === null || job.progress_percent === undefined) {
        fill.classList.add("indeterminate");
        fill.style.width = "";
      } else {
        fill.classList.remove("indeterminate");
        fill.style.width = job.progress_percent + "%";
      }
    }
  }, 2000);
}

document.addEventListener("DOMContentLoaded", initHomeJobPolling);

// --- Gallery: multi-select discard ---
// Off by default (same "Reorder"-style toggle-button interaction as the
// home page) so a stray click never discards anything. While active,
// clicking a card's link overlay toggles selection instead of
// navigating - this is the ONE mechanism for discarding, covering both
// "discard this one bad take" (select just one) and true bulk discarding.

let gallerySelectMode = false;
const selectedRelpaths = new Set();

function toggleSelectMode() {
  gallerySelectMode = !gallerySelectMode;
  const grid = document.getElementById("unpublished-grid");
  const btn = document.getElementById("gallery-select-toggle-btn");
  const actions = document.getElementById("discard-actions");
  if (grid) grid.classList.toggle("select-active", gallerySelectMode);
  if (btn) btn.classList.toggle("active", gallerySelectMode);
  if (actions) actions.classList.toggle("hidden", !gallerySelectMode);
  if (!gallerySelectMode) {
    selectedRelpaths.clear();
    if (grid) grid.querySelectorAll(".gallery-item.selected").forEach(el => el.classList.remove("selected"));
    updateDiscardButton();
  }
}

function updateDiscardButton() {
  const btn = document.getElementById("discard-selected-btn");
  if (!btn) return;
  btn.textContent = `Discard selected (${selectedRelpaths.size})`;
  btn.disabled = selectedRelpaths.size === 0;
}

function initGallerySelect() {
  const grid = document.getElementById("unpublished-grid");
  if (!grid) return;
  grid.addEventListener("click", e => {
    if (!gallerySelectMode) return;
    const link = e.target.closest(".card-link-overlay");
    if (!link) return;
    e.preventDefault();
    const item = link.closest(".gallery-item");
    const relpath = item.dataset.relpath;
    if (selectedRelpaths.has(relpath)) {
      selectedRelpaths.delete(relpath);
      item.classList.remove("selected");
    } else {
      selectedRelpaths.add(relpath);
      item.classList.add("selected");
    }
    updateDiscardButton();
  });
}

async function discardSelected(channelKey) {
  if (selectedRelpaths.size === 0) return;
  await withButtonLoading(document.getElementById("discard-selected-btn"), "Discarding…", async () => {
    const res = await apiFetch(`/channels/${channelKey}/videos/discard`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({relpaths: [...selectedRelpaths]}),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.error || "Failed to discard.");
      return;
    }
    location.reload();
  });
}

document.addEventListener("DOMContentLoaded", initGallerySelect);

// ---------------------------------------------------------------------
// Activity: every video in flight, on one page
//
// Deliberately its own renderer rather than a reuse of pollJob() above.
// That function drives one job through a fixed set of element ids — a
// heading, a stage tracker, a log — and is the right shape for the page
// where you just pressed the button and are watching one thing happen.
// This page's subject is the order: which one is going, what is behind
// it, and when each will be done. Sharing code between the two would mean
// parameterising every id in pollJob for a page that wants none of them.
// ---------------------------------------------------------------------

const ACTIVITY_POLL_MS = 2000;

function activityTimeOfDay(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
}

function activityRow(job) {
  const running = job.status === "running";
  const stageLine = running
    ? `${job.stage_label || "Starting"} &middot; step ${job.stage || 1} of ${job.stage_total || 5}`
    : (job.queue_position ? `Waiting &mdash; ${job.queue_position} in the queue` : "Waiting");

  // An indeterminate bar while a stage runs without a percentage of its
  // own; a real one during the encode, which is the only stage that
  // reports progress. Better than a fake percentage derived from the
  // stage number, which would move in five jumps and mean nothing.
  const pct = job.progress_percent;
  const fill = !running ? `<div class="job-progress-bar-fill" style="width:0%"></div>`
    : (pct === null || pct === undefined)
      ? `<div class="job-progress-bar-fill indeterminate"></div>`
      : `<div class="job-progress-bar-fill" style="width:${pct}%"></div>`;

  const eta = job.eta_label
    ? `<span class="activity-eta">${escapeHtml(job.eta_label)} left<span class="activity-eta-at"> &middot; done around ${activityTimeOfDay(job.eta_at)}</span></span>`
    : "";

  return `
    <div class="card activity-item${running ? " activity-running" : ""}">
      <div class="activity-head">
        <div>
          <p class="meta">${escapeHtml(job.channel_name)}</p>
          <h3>${escapeHtml(job.title)}</h3>
        </div>
        ${eta}
      </div>
      <p class="meta">${stageLine}</p>
      <div class="job-progress-bar${running ? "" : " job-progress-bar-queued"}">
        <div class="job-progress-bar-track">${fill}</div>
      </div>
      <p class="hint"><a href="/channels/${encodeURIComponent(job.channel_key)}/create">Open ${escapeHtml(job.channel_name)}'s progress view &rarr;</a></p>
    </div>`;
}

function activityFinishedRow(job) {
  if (job.status === "done" && job.result_path_rel) {
    return `
      <div class="card activity-item">
        <p class="meta">${escapeHtml(job.channel_name)} &middot; finished ${activityTimeOfDay(job.finished_at)}</p>
        <h3>${escapeHtml(job.title)}</h3>
        <p class="hint"><a href="/channels/${encodeURIComponent(job.channel_key)}/videos/${job.result_path_rel}">Watch it &rarr;</a></p>
      </div>`;
  }
  // A failure that scrolled past in a log is a failure nobody saw. Retry
  // is offered here because this page is where you find out it happened.
  return `
    <div class="card activity-item activity-failed">
      <p class="meta">${escapeHtml(job.channel_name)} &middot; ${escapeHtml(job.status)} ${activityTimeOfDay(job.finished_at)}</p>
      <h3>${escapeHtml(job.title)}</h3>
      <p class="review-flag review-flag-warn">${escapeHtml(job.error || "Something went wrong.")}</p>
      <button type="button" class="btn-ghost" onclick="activityRetry('${job.id}', this)">Retry</button>
    </div>`;
}

async function activityRetry(jobId, button) {
  await withButtonLoading(button, "Retrying…", async () => {
    const res = await apiFetch(`/api/jobs/${jobId}/retry`, {method: "POST"});
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      alert(data.error || "Couldn't retry that job.");
      return;
    }
    refreshActivity();
  });
}

function renderActivity(data) {
  const list = document.getElementById("activity-list");
  const empty = document.getElementById("activity-empty");
  const recentSection = document.getElementById("activity-recent-section");
  const recent = document.getElementById("activity-recent");
  if (!list) return;

  list.innerHTML = data.active.map(activityRow).join("");
  empty.classList.toggle("hidden", data.active.length > 0);

  recent.innerHTML = data.recent.map(activityFinishedRow).join("");
  recentSection.classList.toggle("hidden", data.recent.length === 0);

  const subtitle = document.getElementById("activity-subtitle");
  if (subtitle) {
    const n = data.active.length;
    const basis = data.samples === 0
      ? " Times are a first guess until a video finishes."
      : ` Times are from ${data.samples} finished video${data.samples === 1 ? "" : "s"}.`;
    subtitle.textContent = n === 0
      ? "Nothing in flight."
      : `${n} video${n === 1 ? "" : "s"} in flight. One is made at a time — the rest wait their turn.${basis}`;
  }
}

async function refreshActivity() {
  try {
    const res = await apiFetch("/api/activity");
    if (!res.ok) return;
    renderActivity(await res.json());
  } catch (err) {
    // A dropped poll is not worth a message: the next one is two
    // seconds away and the page still shows the last good state.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("activity-app");
  if (!root) return;
  renderActivity({
    active: JSON.parse(root.dataset.active),
    recent: JSON.parse(root.dataset.recent),
    samples: parseInt(root.dataset.samples || "0", 10),
  });
  setInterval(refreshActivity, ACTIVITY_POLL_MS);
});

// ---------------------------------------------------------------------
// Review queue
//
// The daily loop: watch, decide, move on. Cross-channel and
// keyboard-first, because this is a repetitive judgement task and those
// are the ones worth making fast. State lives in one array and an index;
// nothing navigates, so the video element is never torn down and
// rebuilt.
// ---------------------------------------------------------------------

let reviewItems = [];
let reviewIndex = 0;

function reviewCurrent() {
  return reviewItems[reviewIndex] || null;
}

function initReview() {
  const root = document.getElementById("review-app");
  if (!root) return;

  reviewItems = JSON.parse(root.dataset.items || "[]");
  const reasons = JSON.parse(root.dataset.reasons || "[]");

  const reasonBox = document.getElementById("review-reasons");
  reasonBox.innerHTML = reasons
    .map(([id, label]) => `<button type="button" class="btn-ghost" onclick="reviewDiscard('${id}')">${escapeHtml(label)}</button>`)
    .join("");

  renderReview();
  document.addEventListener("keydown", reviewKeys);
}

function reviewKeys(e) {
  // Never hijack keys while someone is typing a title or a link.
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || e.metaKey || e.ctrlKey) return;

  if (e.key === "p" || e.key === "P") { e.preventDefault(); reviewPublish(); }
  else if (e.key === "d" || e.key === "D") {
    e.preventDefault();
    document.querySelector(".review-discard").open = true;
  } else if (e.key === "ArrowRight") { e.preventDefault(); reviewSkip(); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); reviewBack(); }
}

function renderReview() {
  const item = reviewCurrent();
  if (!item) {
    document.querySelector(".review-layout").innerHTML =
      `<div class="empty-state"><p><strong>Done.</strong></p>
       <p>Nothing left in the queue.</p>
       <a class="btn btn-ghost" href="/insights">See how it's going</a></div>`;
    document.querySelector(".review-bar").classList.add("hidden");
    document.getElementById("review-counter").textContent = "All caught up.";
    return;
  }

  const video = document.getElementById("review-video");
  video.src = `/videos/${item.relpath}`;
  video.load();

  document.getElementById("review-channel").textContent = item.channel_name;
  document.getElementById("review-name").textContent = item.title || item.name;
  document.getElementById("review-created").textContent = item.created_label || "";
  document.getElementById("review-script").textContent = item.meta_text || "(no script recorded)";
  document.getElementById("review-download").href = `/videos/${item.relpath}/download`;

  document.getElementById("review-title").value = item.title || "";
  document.getElementById("review-description").value = item.description || "";
  for (const field of ["youtube_url", "tiktok_url", "instagram_url"]) {
    document.getElementById(`review-${field}`).value = (item.links || {})[field] || "";
  }

  // Alternative titles the script call already produced — one click to
  // swap, rather than regenerating anything.
  const alts = document.getElementById("review-title-options");
  const options = (item.title_options || []).filter(t => t && t !== item.title);
  alts.innerHTML = options.length
    ? options.map(t => `<button type="button" class="title-alt" onclick="useTitle(this)">${escapeHtml(t)}</button>`).join("")
    : "";

  // The two "looks mass-produced" flags, shown where the decision is
  // made rather than buried in a log.
  const flags = [];
  if (item.script_suspect) {
    flags.push(`<p class="review-flag review-flag-warn">A line reads like a note about a line rather than a line: &ldquo;${escapeHtml(item.script_suspect)}&rdquo; &mdash; it is spoken aloud as written.</p>`);
  }
  if (item.footage_degraded) {
    flags.push(`<p class="review-flag review-flag-warn">Footage was picked without scoring &mdash; the matching step failed. Watch this one closely.</p>`);
  }
  if (item.footage_repeated) {
    flags.push(`<p class="review-flag review-flag-warn">Reused a footage clip &mdash; the library ran short.</p>`);
  }
  if (item.similarity_flagged) {
    flags.push(`<p class="review-flag review-flag-warn">Wording is close to ${escapeHtml(item.similarity_closest || "an earlier video")}.</p>`);
  }
  if (item.cost && item.cost.total_usd != null) {
    const c = item.cost.total_usd;
    flags.push(`<p class="review-flag">Cost ${c < 0.01 ? "$" + c.toFixed(4) : "$" + c.toFixed(2)}${item.shot_count ? " &middot; " + item.shot_count + " shots" : ""}</p>`);
  }
  document.getElementById("review-flags").innerHTML = flags.join("");

  // Only offered for channels that are actually connected — an upload
  // button that always fails is worse than no button.
  const uploadCard = document.getElementById("review-upload-card");
  uploadCard.hidden = !item.youtube_connected || Boolean((item.links || {}).youtube_url);
  document.getElementById("review-upload-note").textContent = "";
  document.getElementById("review-upload-btn").disabled = false;

  document.getElementById("review-position").textContent =
    `${reviewIndex + 1} of ${reviewItems.length}`;
  document.querySelector(".review-discard").open = false;
}

// Uploads the current video, then drains it from the queue the same way
// Publish does — recording the returned link IS what marks it published,
// so there is one notion of "published" rather than two.
async function reviewUploadYouTube() {
  const item = reviewCurrent();
  if (!item) return;
  await reviewSaveMeta();

  const button = document.getElementById("review-upload-btn");
  const note = document.getElementById("review-upload-note");
  note.textContent = "";

  await withButtonLoading(button, "Uploading…", async () => {
    const res = await apiFetch(`/api/videos/${item.relpath}/upload-youtube`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        channel_key: item.channel_key,
        privacy: document.getElementById("review-privacy").value,
        title: document.getElementById("review-title").value,
        description: document.getElementById("review-description").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) { note.textContent = data.error || "The upload failed."; return; }

    if (data.locked_private) {
      // Expected on an unaudited project, and confusing if unexplained —
      // say it here rather than letting them find a private video later.
      alert("Uploaded, but YouTube forced it to private because the API "
          + "project hasn't passed a compliance audit. Make it public in "
          + "YouTube Studio:\n\n" + data.url);
    }
    reviewDrop();
  });
}

function useTitle(button) {
  document.getElementById("review-title").value = button.textContent;
}

function copyField(id, button) {
  const value = document.getElementById(id).value;
  navigator.clipboard.writeText(value).then(() => {
    const original = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = original; }, 1200);
  });
}

async function reviewSaveMeta() {
  const item = reviewCurrent();
  if (!item) return;
  const title = document.getElementById("review-title").value;
  const description = document.getElementById("review-description").value;
  if (title === (item.title || "") && description === (item.description || "")) return;
  item.title = title;
  item.description = description;
  await apiFetch(`/api/videos/${item.relpath}/meta`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({title, description}),
  });
}

function reviewDrop() {
  // Remove the current item and stay at the same index, which is now the
  // next one — so the queue drains under the cursor instead of jumping.
  reviewItems.splice(reviewIndex, 1);
  if (reviewIndex >= reviewItems.length) reviewIndex = Math.max(0, reviewItems.length - 1);
  document.getElementById("review-counter").textContent =
    reviewItems.length ? `${reviewItems.length} video${reviewItems.length === 1 ? "" : "s"} waiting, oldest first.` : "All caught up.";
  decrementNavCount();
  renderReview();
}

function decrementNavCount() {
  // The header's waiting-count badge is rendered once, server-side, on
  // page load — nothing about publishing or discarding here reloads the
  // page, so without this it sits stale until the next navigation.
  const badge = document.querySelector('a[href="/review"] .nav-count');
  if (!badge) return;
  const next = parseInt(badge.textContent, 10) - 1;
  if (next > 0) badge.textContent = String(next);
  else badge.remove();
}

async function reviewPublish() {
  const item = reviewCurrent();
  if (!item) return;
  await reviewSaveMeta();

  const links = {};
  for (const field of ["youtube_url", "tiktok_url", "instagram_url"]) {
    links[field] = document.getElementById(`review-${field}`).value.trim();
  }
  if (!Object.values(links).some(Boolean)) {
    alert("Paste at least one link to where you posted it, then press Publish.");
    document.getElementById("review-youtube_url").focus();
    return;
  }

  const res = await apiFetch(`/api/videos/${item.relpath}/publish`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(links),
  });
  const data = await res.json();
  if (!res.ok) { alert(data.error || "Couldn't mark that published."); return; }
  reviewDrop();
}

async function reviewDiscard(reason) {
  const item = reviewCurrent();
  if (!item) return;
  const res = await apiFetch(`/api/videos/${item.relpath}/discard`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({reason}),
  });
  if (!res.ok) { alert("Couldn't discard that one."); return; }
  reviewDrop();
}

async function reviewSkip() {
  await reviewSaveMeta();
  if (reviewIndex < reviewItems.length - 1) reviewIndex += 1;
  else reviewIndex = 0;
  renderReview();
}

function reviewBack() {
  reviewIndex = reviewIndex > 0 ? reviewIndex - 1 : reviewItems.length - 1;
  renderReview();
}

document.addEventListener("DOMContentLoaded", initReview);

// ---------------------------------------------------------------------
// Footage library
// ---------------------------------------------------------------------

function footageCard(button) {
  return button.closest(".footage-card");
}

async function redescribeClip(button) {
  const card = footageCard(button);
  const filename = card.dataset.filename;
  await withButtonLoading(button, "Looking…", async () => {
    const res = await apiFetch(`/api/footage/${encodeURIComponent(filename)}/describe`, {method: "POST"});
    const data = await res.json();
    if (!res.ok) { alert(data.error || "Couldn't re-describe that clip."); return; }
    card.querySelector(".footage-desc").textContent = data.description;
  });
}

async function confirmLicense(button) {
  const card = footageCard(button);
  const filename = card.dataset.filename;
  const text = prompt(
    "What licence does this clip carry? Record exactly what the source publishes.",
    "Pexels License - free for commercial use, no attribution required");
  if (!text) return;
  const res = await apiFetch(`/api/footage/${encodeURIComponent(filename)}/license`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({license: text}),
  });
  const data = await res.json();
  if (!res.ok) { alert(data.error || "Couldn't save that."); return; }
  card.querySelector(".footage-stats").innerHTML =
    card.querySelector(".footage-stats").innerHTML.replace(
      /&middot; <span class="footage-warn">.*?<\/span>/, "");
  button.remove();
}

async function deleteClip(button) {
  const card = footageCard(button);
  const filename = card.dataset.filename;
  if (!confirm(`Delete ${filename}? The file and its library entry both go, permanently.`)) return;
  const res = await apiFetch(`/api/footage/${encodeURIComponent(filename)}/delete`, {method: "POST"});
  if (!res.ok) { alert("Couldn't delete that clip."); return; }
  card.remove();
}

// ---------------------------------------------------------------------
// Script preview
//
// The style prompt is the highest-leverage field in the system, and the
// only way to see what a change did was to generate a whole video. This
// runs script generation alone — about a cent, a few seconds.
// ---------------------------------------------------------------------

async function previewScript(channelKey, button) {
  const panel = document.getElementById("script-preview");
  panel.classList.remove("hidden");
  panel.innerHTML = `<p class="meta"><span class="spinner"></span> Writing a script with the current settings…</p>`;

  await withButtonLoading(button, "Writing…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/preview-script`, {method: "POST"});
    const data = await res.json();
    if (!res.ok) {
      panel.innerHTML = `<p class="error">${escapeHtml(data.error || "Couldn't generate a preview.")}</p>`;
      return;
    }
    const segments = data.script.segments.map((s, i) => `
      <div class="preview-segment">
        <p class="meta">Segment ${i + 1}</p>
        <p>${escapeHtml(s.text)}</p>
        <p class="meta preview-brief">On screen: ${escapeHtml(s.shot_brief || "(none)")}</p>
      </div>`).join("");
    panel.innerHTML = `
      <p class="meta">Seed: ${escapeHtml(data.seed)}</p>
      <p class="preview-title">${escapeHtml(data.script.title || "(no title)")}</p>
      ${segments}
      <p class="meta">Cost about ${escapeHtml(data.cost)} &middot; no video was rendered.</p>`;
  });
}

// Applies the currently-selected Voice Lab combination to a channel.
// The Lab already knows the voice, speed and cadence; asking someone to
// memorise an ID and retype it on another page was the only missing step.
// Says which channel is about to be overwritten, before the click. The
// dropdown is a list of names with no other context, and applying a voice
// to the wrong channel is silent and easy.
function showApplyTarget() {
  const option = document.getElementById("apply-channel").selectedOptions[0];
  const note = document.getElementById("apply-target-note");
  if (!option || !note) return;
  const published = parseInt(option.dataset.published || "0", 10);
  note.textContent = published
    ? `${option.dataset.name} has ${published} published video${published === 1 ? "" : "s"} — changing its voice now means it sounds different from here on.`
    : `Will overwrite the voice, speed and pacing on ${option.dataset.name}.`;
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("apply-channel")) showApplyTarget();
});

async function applyVoiceToChannel(button) {
  const select = document.getElementById("apply-channel");
  const channelKey = select.value;
  const option = select.selectedOptions[0];
  const published = parseInt(option?.dataset.published || "0", 10);
  const name = option?.dataset.name || channelKey;

  // Confirmed always, because there is no undo and the dropdown does not
  // remember what you last picked. Worded harder once a channel has
  // published, since the voice is then part of what the audience knows.
  const warning = published
    ? `${name} has ${published} published video${published === 1 ? "" : "s"}.

`
      + `Changing its voice, speed and pacing now means every future video sounds `
      + `different from the ones already out. Continue?`
    : `Overwrite the voice, speed and pacing on ${name}?`;
  if (!confirm(warning)) return;

  // Read the same controls the "Test this combo" button reads, so what
  // you apply is exactly what you just listened to.
  const voiceInput = document.querySelector('input[name="voice_id"]:checked');
  const preset = document.getElementById("preset-select").value;
  const speed = parseFloat(document.getElementById("speed-slider").value);
  const result = document.getElementById("apply-result");

  if (!voiceInput) { result.textContent = "Pick a voice first."; return; }

  await withButtonLoading(button, "Applying…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/voice`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({voice_id: voiceInput.value, speed, preset}),
    });
    const data = await res.json();
    result.textContent = res.ok
      ? `Applied to ${data.channel}.`
      : (data.error || "Couldn't apply that.");
  });
}

// Footage cards show a cached poster and only load the real clip while
// hovered — sixty concurrent <video> elements never reliably paint, and
// loading sixty videos just to show sixty stills would be wasteful even
// if they did.
function playClip(box) {
  if (box.querySelector("video")) return;
  const video = document.createElement("video");
  video.src = box.dataset.src;
  video.muted = true;
  video.loop = true;
  video.playsInline = true;
  box.appendChild(video);
  video.play().catch(() => {});
}

function stopClip(box) {
  const video = box.querySelector("video");
  if (video) video.remove();
}

// Settings tabs. One <form> underneath, so Save still submits every
// panel regardless of which is visible — the tabs are presentation only.
function showFormTab(button) {
  const name = button.dataset.tab;
  for (const tab of document.querySelectorAll(".form-tab")) {
    tab.classList.toggle("active", tab === button);
  }
  for (const panel of document.querySelectorAll(".form-panel")) {
    panel.classList.toggle("active", panel.dataset.panel === name);
  }
  // Remembered per browser, so returning to settings lands where you
  // left off rather than always on the first tab.
  try { localStorage.setItem("settingsTab", name); } catch (e) { /* private mode */ }
}

document.addEventListener("DOMContentLoaded", () => {
  if (!document.querySelector(".form-tabs")) return;
  let saved = null;
  try { saved = localStorage.getItem("settingsTab"); } catch (e) { /* private mode */ }
  const target = saved && document.querySelector(`.form-tab[data-tab="${saved}"]`);
  if (target) showFormTab(target);
});

// --- Caption preview --------------------------------------------------
//
// The Look tab used to be six hex strings in text boxes. You could not
// tell from them whether a 4px outline held up against bright footage or
// where 68px wrapped. So every change here re-renders a real frame
// server-side, through the same code that renders the video — no CSS
// impression of a caption, which would be a different thing looking
// approximately right.
//
// Debounced, because a colour picker fires continuously while dragging
// and each render is a real Pillow composite.
const PREVIEW_DEBOUNCE_MS = 220;

// Three independent preview surfaces share this machinery: captions,
// the title card, and the outro card. Fields relevant to any of them are
// scattered across several fieldsets (and, for the channel name and
// outro subtext, outside the Look section entirely), so the payload is
// gathered from the whole form rather than scoped to one container —
// each backend route only reads the keys it cares about and ignores the
// rest. State (which request is newest) is tracked per surface name
// rather than in one shared variable, since captions/title/outro can
// all be mid-request at once and must never cancel each other.
function previewPayload() {
  const body = new URLSearchParams();
  for (const field of document.querySelectorAll("[data-preview-field]")) {
    // A checkbox's .value is its (usually unhelpful) HTML attribute
    // regardless of whether it's ticked - .checked is the real state.
    const value = field.type === "checkbox" ? (field.checked ? "1" : "0") : field.value;
    body.set(field.dataset.previewField, value);
  }
  return body;
}

const _previewState = {};

async function renderPreview(root, name, endpoint, extra) {
  const image = root.querySelector(`[data-preview-image="${name}"]`);
  const spinner = root.querySelector(`[data-preview-spinner="${name}"]`);
  if (!image) return;
  if (spinner) spinner.hidden = false;

  // Newest request wins: dragging a slider queues several, and they can
  // come back out of order, which would leave the preview showing a
  // value the form no longer holds.
  const token = {};
  _previewState[name] = token;
  try {
    const body = previewPayload();
    if (extra) for (const [k, v] of Object.entries(extra)) body.set(k, v);
    const response = await apiFetch(endpoint, { method: "POST", body });
    if (!response.ok) throw new Error(response.status);
    const blob = await response.blob();
    if (_previewState[name] !== token) return;
    const url = URL.createObjectURL(blob);
    const previous = image.src;
    image.src = url;
    image.hidden = false;
    if (previous.startsWith("blob:")) URL.revokeObjectURL(previous);
  } catch (e) {
    // A failed preview is cosmetic: keep the last good frame rather than
    // replacing the panel with an error the user can't act on.
    console.warn(`${name} preview failed`, e);
  } finally {
    if (_previewState[name] === token && spinner) spinner.hidden = true;
  }
}

const _previewTimers = {};

function queuePreview(root, name, endpoint, extra) {
  clearTimeout(_previewTimers[name]);
  _previewTimers[name] = setTimeout(() => renderPreview(root, name, endpoint, extra), PREVIEW_DEBOUNCE_MS);
}

function renderCaptionPreview(root) { return renderPreview(root, "caption", "/api/caption-preview"); }
function queueCaptionPreview(root) { return queuePreview(root, "caption", "/api/caption-preview"); }

function renderCardPreview(root, channelKey, card) {
  return renderPreview(root, card, `/api/channels/${channelKey}/card-preview`, { card });
}
function queueCardPreview(root, channelKey, card) {
  return queuePreview(root, card, `/api/channels/${channelKey}/card-preview`, { card });
}

// Keeps a <input type="color"> and its hex text box in step, in both
// directions. Two controls rather than one because the picker cannot be
// typed into and the text box cannot be browsed — and because the outro
// background is stored as R,G,B,A, which no colour input speaks.
function bindColorPickers(root) {
  for (const picker of root.querySelectorAll("[data-color-for]")) {
    const text = root.querySelector(`[name="${picker.dataset.colorFor}"]`);
    if (!text) continue;
    const rgba = picker.hasAttribute("data-rgba");

    if (rgba) picker.value = rgbaToHex(text.value);

    picker.addEventListener("input", () => {
      text.value = rgba ? hexToRgba(picker.value, text.value) : picker.value.toUpperCase();
      text.dispatchEvent(new Event("input", { bubbles: true }));
    });
    text.addEventListener("input", () => {
      const hex = rgba ? rgbaToHex(text.value) : text.value.trim();
      if (/^#[0-9a-fA-F]{6}$/.test(hex)) picker.value = hex;
    });
  }
}

function rgbaToHex(value) {
  const parts = (value || "").split(",").map((n) => parseInt(n.trim(), 10));
  if (parts.length < 3 || parts.slice(0, 3).some((n) => Number.isNaN(n))) return "#000000";
  return "#" + parts.slice(0, 3)
    .map((n) => Math.min(255, Math.max(0, n)).toString(16).padStart(2, "0"))
    .join("");
}

// Preserves whatever alpha was already there: the picker has no opacity
// channel, and silently resetting it to 255 would quietly un-fade an
// outro someone had deliberately made translucent.
function hexToRgba(hex, current) {
  const alpha = (current || "").split(",")[3];
  const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return rgb.concat([alpha !== undefined ? alpha.trim() : "255"]).join(",");
}

document.addEventListener("DOMContentLoaded", () => {
  const root = document.querySelector("[data-caption-preview]");
  if (!root) return;
  const channelKey = root.dataset.channelKey;

  bindColorPickers(root);

  // The note lives under the select rather than inside each option: the
  // dropdown is only as wide as its column, and "Very heavy and
  // condensed. Fits more words per line" truncated to "Very heavy and
  // cond…" told you nothing.
  const fontSelect = root.querySelector("[data-font-select]");
  const fontNote = root.querySelector("[data-font-note]");
  if (fontSelect && fontNote) {
    const showNote = () => {
      fontNote.textContent = fontSelect.selectedOptions[0]?.dataset.note || "";
    };
    fontSelect.addEventListener("change", showNote);
    showNote();
  }

  const refreshPreviews = () => {
    queueCaptionPreview(root);
    if (channelKey) {
      queueCardPreview(root, channelKey, "title");
      queueCardPreview(root, channelKey, "outro");
    }
  };

  // Every field any of the three previews reads from, not just captions'
  // own — the channel name and outro subtext live outside this root
  // entirely (the Channel section), and the title/outro cards need both.
  for (const field of document.querySelectorAll("[data-preview-field]")) {
    field.addEventListener("input", () => {
      const output = field.parentElement.querySelector(".slider-value");
      if (output) output.value = field.value;
      refreshPreviews();
    });
  }

  renderCaptionPreview(root);
  if (channelKey) {
    renderCardPreview(root, channelKey, "title");
    renderCardPreview(root, channelKey, "outro");
  }
});

// --- Topic plan -------------------------------------------------------
//
// Both actions cost real money, so both say what they are doing and
// neither is silent while it works — an outline call takes ten seconds or
// so, and a page that looks frozen invites a second click.

// full_usd already scales with topic_count server-side (curriculum_gen.
// estimate_cost) - this just re-evaluates the same formula as the number
// input changes, instead of a figure frozen at the page's default count.
function updateCurriculumCostDot() {
  const topics = document.getElementById("curriculum-topics");
  const dot = document.getElementById("curriculum-cost-dot");
  if (!topics || !dot) return;
  const outline = parseFloat(topics.dataset.costOutline) || 0;
  const perTopic = parseFloat(topics.dataset.costPerTopic) || 0;
  const count = Number(topics.value) || 0;
  const full = outline + perTopic * count;
  dot.dataset.tooltip = `Designing the outline: about $${outline.toFixed(2)}. `
    + `Filling all ${count} topics eventually: about $${full.toFixed(2)}, spread over time.`;
}

document.addEventListener("DOMContentLoaded", updateCurriculumCostDot);

async function makeOutline(event, key) {
  event.preventDefault();
  const button = document.getElementById("curriculum-outline-btn");
  const status = document.getElementById("curriculum-status");
  status.textContent = "";

  await withButtonLoading(button, "Designing…", async () => {
    const res = await apiFetch(`/api/channels/${key}/curriculum/outline`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        subject: document.getElementById("curriculum-subject").value,
        topic_count: document.getElementById("curriculum-topics").value,
        total_subtopics: document.getElementById("curriculum-subtopics").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't design a plan."; return; }
    window.location.reload();
  });
  return false;
}

async function fillTopics(key, count, topicId) {
  const button = document.getElementById(
    topicId ? `curriculum-fill-${topicId}`
            : count > 1 ? "curriculum-fill-many-btn" : "curriculum-fill-btn");
  const status = document.getElementById("curriculum-status");
  status.textContent = "";

  await withButtonLoading(button, "Writing…", async () => {
    const res = await apiFetch(`/api/channels/${key}/curriculum/fill`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({count, topic_id: topicId || ""}),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't write those subtopics."; return; }
    window.location.reload();
  });
}


// Saving a channel that has already published asks first. The settings
// form carries every tab at once, so a save intended to fix a link also
// commits whatever else is on the page — including a voice or caption
// change made and forgotten about. On a channel with an audience that is
// worth one click to confirm.
function confirmSettingsSave() {
  const warning = document.getElementById("published-warning");
  if (!warning) return true;
  const count = parseInt(warning.dataset.published || "0", 10);
  const name = warning.dataset.name || "this channel";
  return confirm(
    `${name} has ${count} published video${count === 1 ? "" : "s"}.

`
    + `This saves every tab, not just the one you are looking at. Continue?`);
}

// --- Settings: unsaved changes ---------------------------------------
//
// The old wizard committed on Next, with no indication that it had. This
// says plainly whether anything is outstanding, and warns on the way out.
// Both matter more than usual here because one form carries every section.

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("settings-form");
  if (!form) return;

  const state = document.getElementById("settings-save-state");
  let dirty = false;

  function markDirty() {
    if (dirty) return;
    dirty = true;
    if (state) {
      state.textContent = "Unsaved changes";
      state.classList.add("dirty");
    }
  }

  form.addEventListener("input", markDirty);
  form.addEventListener("change", markDirty);
  // Submitting is not leaving with unsaved work.
  form.addEventListener("submit", () => { dirty = false; });

  window.addEventListener("beforeunload", (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  // Highlights the section you are actually looking at. Scroll position
  // rather than the clicked link, so it stays right when you scroll by
  // hand or land on an anchor.
  const links = [...document.querySelectorAll(".settings-nav-link")];
  const sections = links
    .map(link => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  if (sections.length && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const index = sections.indexOf(entry.target);
        links.forEach((link, i) => link.classList.toggle("active", i === index));
      }
    }, {rootMargin: "-20% 0px -70% 0px"});
    sections.forEach(section => observer.observe(section));
  }
});

// --- Create page: the topic table ---------------------------------------
//
// Used to be three levels of dropdown (topic, then "within it", then
// maybe a specific subtopic) that never showed you the plan you were
// choosing from. Now: a small table of topics, colour-coded by status,
// highlighting whichever one the channel's ordering policy would pick
// next — click a different row to make that topic's next one instead.
// The same renderer drives the settings page's ordering-preview
// animation (see below), parameterised only by where the rows come from.

const TOPIC_CHIP_CLASS = {
  published: "topic-chip-published",
  used: "topic-chip-used",
  pending: "topic-chip-pending",
};

// `rows` is the plain shape core.curriculum.table_rows returns (or the
// same shape built client-side for the ordering-preview animation).
// `selectedTopicId` controls which row renders as selected; `onSelect`,
// when given, makes rows clickable (omitted for the read-only simulator).
function renderTopicTable(container, rows, selectedTopicId, onSelect) {
  container.innerHTML = rows.map((row, i) => {
    const chips = row.subtopics.map((s) => {
      const cls = s.is_next ? "topic-chip-next" : (TOPIC_CHIP_CLASS[s.status] || "topic-chip-pending");
      return `<span class="topic-chip ${cls}" title="${escapeHtml(s.title)}"></span>`;
    }).join("");
    const madeCount = row.done + row.published;
    const selected = row.topic_id === selectedTopicId;
    const tag = onSelect ? "button" : "div";
    return `
      <${tag} type="${onSelect ? "button" : ""}"
              class="topic-row ${selected ? "selected" : ""} ${row.total === 0 ? "topic-row-empty" : ""}"
              data-row-index="${i}">
        <span class="topic-row-title">${escapeHtml(row.title)}</span>
        <span class="topic-row-chips">${chips || '<span class="hint">not written yet</span>'}</span>
        <span class="topic-row-count">${madeCount}/${row.total}</span>
      </${tag}>`;
  }).join("");

  if (!onSelect) return;
  for (const btn of container.querySelectorAll("[data-row-index]")) {
    btn.addEventListener("click", () => onSelect(rows[Number(btn.dataset.rowIndex)]));
  }
}

async function selectTopicRow(channelKey, row) {
  const table = document.getElementById("topic-table");
  const status = document.getElementById("topic-table-status");
  status.textContent = "";

  if (row.total === 0) {
    status.textContent = "Writing this topic's subtopics…";
    const res = await apiFetch(`/api/channels/${channelKey}/curriculum/fill`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({count: 1, topic_id: row.topic_id}),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't write those."; return; }
    // The table's whole data is now stale (this topic went from empty to
    // having subtopics) - simplest correct thing is to get the fresh
    // page rather than reconstruct what the template already computed.
    window.location.reload();
    return;
  }
  if (row.pending === 0) {
    status.textContent = "Every subtopic in this topic has been made already.";
    return;
  }

  table.dataset.selectedTopic = row.topic_id;
  const rows = JSON.parse(table.dataset.rows);
  renderTopicTable(table, rows, row.topic_id, (r) => selectTopicRow(channelKey, r));
  previewTopicPick(channelKey);
}

// Separate from getSeed()/#seed-preview (used by the quote and flat-
// topic-list flow below): the table has to stay on screen while its
// preview updates, where getSeed's flow hides the whole picker the
// moment a candidate is fetched. Simpler to keep the two flows apart
// than to make one function serve two different panel layouts.
async function previewTopicPick(channelKey) {
  const status = document.getElementById("topic-table-status");
  status.textContent = "";
  const res = await apiFetch(`/api/channels/${channelKey}/seed`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(currentPick()),
  });
  const data = await res.json();
  if (!res.ok) { status.textContent = data.error || "Failed to fetch a candidate."; return; }
  currentSeed = data.seed;

  const history = data.history || {};
  const repeat = history.count
    ? `<p class="meta seed-repeat">Already used ${history.count} time${history.count === 1 ? "" : "s"}` +
      `${history.last ? ", most recently " + escapeHtml(history.last) : ""}.</p>`
    : "";
  document.getElementById("topic-preview-text").innerHTML =
    `<p><strong>${escapeHtml(currentSeed.topic)}</strong></p>${repeat}`;
  document.getElementById("topic-preview").classList.remove("hidden");
}

document.addEventListener("DOMContentLoaded", () => {
  const table = document.getElementById("topic-table");
  if (!table) return;
  const rows = JSON.parse(table.dataset.rows || "[]");
  const channelKey = table.dataset.channelKey;
  renderTopicTable(table, rows, table.dataset.selectedTopic,
    (row) => selectTopicRow(channelKey, row));
  // The preview starts in step with whichever row is selected, the same
  // way clicking a different row immediately re-previews it.
  if (table.dataset.selectedTopic) previewTopicPick(channelKey);
});

// --- Ordering settings: "watch it happen" -------------------------------
//
// A single stickiness number doesn't say what it does — this runs the
// real core.ordering.choose_next_subtopic (via the ordering-preview
// route) against a small dummy plan built from whatever's currently
// sitting in the form, unsaved, and replays the resulting sequence one
// pick at a time on the same table renderer the real Create Video page
// uses. Never a second, JS implementation of the ordering rules: the
// animation can't show behaviour the channel wouldn't actually produce.

let orderingPreviewTimer = null;

async function runOrderingPreview(channelKey) {
  const status = document.getElementById("ordering-preview-status");
  const table = document.getElementById("ordering-preview-table");
  status.textContent = "";
  clearInterval(orderingPreviewTimer);

  const settings = {
    mode: document.querySelector('[name="ordering_mode"]').value,
    topic_order: document.querySelector('[name="ordering_topic_order"]').value,
    subtopic_order: document.querySelector('[name="ordering_subtopic_order"]').value,
    grouping: document.querySelector('[name="ordering_grouping"]').value,
    stickiness: parseFloat(document.querySelector('[name="ordering_stickiness"]').value),
  };

  await withButtonLoading(event.target.closest("button"), "Simulating…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/ordering-preview`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(settings),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't run the preview."; return; }
    table.classList.remove("hidden");
    animateOrderingPreview(table, data.rows, data.steps, status);
  });
}

function animateOrderingPreview(table, rows, steps, status) {
  const byTopic = Object.fromEntries(rows.map((r) => [r.topic_id, r]));
  const bySubtopic = {};
  for (const row of rows) for (const s of row.subtopics) bySubtopic[s.id] = s;

  let i = 0;
  renderTopicTable(table, rows, null);
  status.textContent = `Replaying ${steps.length} simulated videos…`;

  orderingPreviewTimer = setInterval(() => {
    if (i >= steps.length) {
      clearInterval(orderingPreviewTimer);
      status.textContent = `Done — ${steps.length} simulated videos, in the order this setting would make them.`;
      return;
    }
    const step = steps[i];
    const sub = bySubtopic[step.subtopic_id];
    const row = byTopic[step.topic_id];
    if (sub) sub.status = "used";
    if (row) { row.pending -= 1; row.done += 1; }
    renderTopicTable(table, rows, step.topic_id);
    i += 1;
  }, 350);
}

// --- Background picture ------------------------------------------------
//
// Searching is free and returns preview URLs the browser loads directly.
// Nothing is downloaded until a picture is chosen, so browsing costs one
// API call and no disk.

async function searchBackgrounds(channelKey) {
  const button = document.getElementById("background-search-btn");
  const status = document.getElementById("background-status");
  const grid = document.getElementById("background-results");
  status.textContent = "";

  await withButtonLoading(button, "Searching…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/background/search`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({query: document.getElementById("background-query").value}),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Search failed."; return; }

    grid.innerHTML = data.results.map(r => `
      <button type="button" class="background-option"
              onclick='chooseBackground(${JSON.stringify(channelKey)}, ${JSON.stringify(r)})'>
        <img src="${r.preview}" alt="" loading="lazy">
        <span class="hint">${escapeHtml(r.source)}${r.credit ? " · " + escapeHtml(r.credit) : ""}</span>
      </button>`).join("");
    status.textContent = `${data.results.length} found for "${data.query}".`;
  });
}

async function chooseBackground(channelKey, result) {
  const status = document.getElementById("background-status");
  status.textContent = "Downloading…";
  const res = await apiFetch(`/api/channels/${channelKey}/background/choose`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      url: result.full, source: result.source,
      credit: result.credit, link: result.link,
      blur: document.getElementById("background-blur")?.value || 0,
      dim: document.getElementById("background-dim")?.value || 0,
    }),
  });
  const data = await res.json();
  if (!res.ok) { status.textContent = data.error || "Couldn't use that one."; return; }
  status.textContent = "Saved.";
  showBackground(channelKey);
}

async function applyBackgroundEdits(channelKey) {
  const button = document.getElementById("background-apply-btn");
  const status = document.getElementById("background-status");
  await withButtonLoading(button, "Applying…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/background/edit`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        blur: document.getElementById("background-blur").value,
        dim: document.getElementById("background-dim").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't apply that."; return; }
    status.textContent = "";
    showBackground(channelKey);
  });
}

async function clearBackground(channelKey) {
  if (!confirm("Remove this channel's background picture?")) return;
  await apiFetch(`/api/channels/${channelKey}/background/clear`, {method: "POST"});
  document.getElementById("background-current").hidden = true;
  document.getElementById("background-status").textContent = "Removed.";
}

// The file is rewritten in place, so the URL alone would show a cached
// copy and the edits would look like they had done nothing.
function showBackground(channelKey) {
  const image = document.getElementById("background-preview");
  image.src = `/channels/${channelKey}/background.jpg?t=${Date.now()}`;
  document.getElementById("background-current").hidden = false;
}

// --- Suggest a look --------------------------------------------------
//
// Writes real colour values into the existing fields and dispatches the
// same "input" event a hand-typed edit would, so the colour-picker sync
// and the live caption preview both react exactly as if you'd picked the
// colours yourself. Nothing is written to the channel until the normal
// Save button is pressed — this only changes what's on the page.

async function suggestLook(channelKey) {
  const button = document.getElementById("suggest-look-btn");
  const status = document.getElementById("suggest-look-status");
  status.textContent = "";

  await withButtonLoading(button, "Thinking…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/suggest-look`, {method: "POST"});
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't suggest a look."; return; }

    for (const [field, value] of Object.entries(data.colors)) {
      const input = document.querySelector(`[name="style_${field}"]`);
      if (!input) continue;
      input.value = value;
      input.dispatchEvent(new Event("input", {bubbles: true}));
    }

    const fontSelect = document.querySelector('[name="style_font_face"]');
    if (fontSelect) {
      fontSelect.value = data.font_key;
      fontSelect.dispatchEvent(new Event("change", {bubbles: true}));
      fontSelect.dispatchEvent(new Event("input", {bubbles: true}));
    }

    status.textContent = `${data.palette} + ${data.font_label} (${data.cost}). ${data.reason}`;
  });
}

// --- Style & tone picker ------------------------------------------------
//
// Generates real short samples from real candidate prompts, shows them
// side by side, and only writes anything once a candidate is explicitly
// chosen. Nothing here auto-saves.

function collectStyleChoices() {
  const choices = {};
  for (const input of document.querySelectorAll('#style-picker-form input[type="radio"]:checked')) {
    choices[input.name.replace(/^axis_/, "")] = input.value;
  }
  return choices;
}

// The real per-unit cost is already known server-side (measured, not
// guessed - see pipeline.style_gen.COST_PER_CANDIDATE_USD); this just
// recomputes the product as the slider moves instead of showing a figure
// frozen at whatever count the page happened to load with.
function updateCandidateCostDot() {
  const slider = document.getElementById("candidate-count");
  const dot = document.getElementById("candidate-cost-dot");
  if (!slider || !dot) return;
  const perUnit = parseFloat(slider.dataset.costPerUnit) || 0;
  const count = Number(slider.value);
  const total = perUnit * count;
  dot.dataset.tooltip = `About ${total < 0.01 ? "$" + total.toFixed(4) : "$" + total.toFixed(2)} for ${count} candidates.`;
}

document.addEventListener("DOMContentLoaded", updateCandidateCostDot);

async function generateStyleCandidates(channelKey) {
  const button = document.getElementById("generate-candidates-btn");
  const status = document.getElementById("style-setup-status");
  const container = document.getElementById("style-candidates");
  status.textContent = "";
  container.innerHTML = "";

  await withButtonLoading(button, "Writing and comparing…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/style-setup/candidates`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        choices: collectStyleChoices(),
        count: document.getElementById("candidate-count").value,
      }),
    });
    const data = await res.json();
    if (!res.ok) { status.textContent = data.error || "Couldn't generate candidates."; return; }

    status.textContent = `${data.candidates.length} candidates, about "${data.seed}" (${data.cost}).`;
    container.innerHTML = data.candidates.map((c, i) => renderStyleCandidate(c, i)).join("");
    // Listeners attached programmatically rather than inline onclick with
    // serialised text in an HTML attribute — a sample or a drafted prompt
    // containing a double quote would otherwise truncate the attribute at
    // that character, silently dropping the rest of the call (found by
    // actually clicking the button, not by reading the template).
    wireStyleCandidateButtons(channelKey, data.candidates);
  });
}

function renderStyleCandidate(candidate, index) {
  if (!candidate.sample) {
    return `
      <div class="card style-candidate style-candidate-failed">
        <p class="meta"><strong>${escapeHtml(candidate.blurb)}</strong></p>
        <p class="error">${escapeHtml(candidate.error || "This one failed to generate.")}</p>
      </div>`;
  }
  return `
    <div class="card style-candidate" data-candidate-index="${index}">
      <p class="meta"><strong>${escapeHtml(candidate.blurb)}</strong></p>
      <p class="style-candidate-sample">${candidate.sample.map(escapeHtml).join("</p><p class=\"style-candidate-sample\">")}</p>
      <details>
        <summary class="summary-heading">Full style prompt</summary>
        <p class="hint">${escapeHtml(candidate.style_prompt)}</p>
      </details>
      <div class="actions">
        <button type="button" class="btn-ghost" data-listen-btn>Listen</button>
        <button type="button" class="btn btn-primary" data-choose-btn>Use this one</button>
      </div>
      <audio class="style-candidate-audio" hidden controls></audio>
    </div>`;
}

// Attaches the Listen/Use-this-one handlers after the cards are in the
// DOM, closing over the real candidate objects rather than round-tripping
// their text through an HTML attribute.
function wireStyleCandidateButtons(channelKey, candidates) {
  for (const card of document.querySelectorAll(".style-candidate[data-candidate-index]")) {
    const candidate = candidates[Number(card.dataset.candidateIndex)];
    if (!candidate || !candidate.sample) continue;

    const listenBtn = card.querySelector("[data-listen-btn]");
    if (listenBtn) {
      listenBtn.addEventListener("click", () =>
        listenToCandidate(channelKey, listenBtn, candidate.sample.join(" ")));
    }
    const chooseBtn = card.querySelector("[data-choose-btn]");
    if (chooseBtn) {
      chooseBtn.addEventListener("click", () =>
        chooseStyleCandidate(channelKey, candidate.style_prompt));
    }
  }
}

async function listenToCandidate(channelKey, button, text) {
  const card = button.closest(".style-candidate");
  const audio = card.querySelector("audio");
  await withButtonLoading(button, "Loading…", async () => {
    const res = await apiFetch(`/api/channels/${channelKey}/style-setup/listen`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text}),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || "Couldn't generate audio for this one."); return; }
    audio.src = data.url;
    audio.hidden = false;
    audio.play();
  });
}

function chooseStyleCandidate(channelKey, stylePrompt) {
  if (!confirm("Save this as the channel's style prompt? You can still "
             + "edit the wording afterward in Settings.")) return;
  const form = document.createElement("form");
  form.method = "post";
  form.action = `/channels/${channelKey}/style-setup/choose`;
  const promptField = document.createElement("input");
  promptField.type = "hidden";
  promptField.name = "style_prompt";
  promptField.value = stylePrompt;
  const csrfField = document.createElement("input");
  csrfField.type = "hidden";
  csrfField.name = "csrf_token";
  csrfField.value = CSRF_TOKEN;
  form.appendChild(promptField);
  form.appendChild(csrfField);
  document.body.appendChild(form);
  form.submit();
}

// ---------------------------------------------------------------------
// Script notebook
//
// A topic's scripts, written together and read one at a time — tabs
// down the side, arrow keys to flip through, the same "one array and an
// index" shape the review queue uses. Dynamic text only ever lands in a
// text node via escapeHtml(), never in an HTML attribute string: an
// earlier version of this project put JSON.stringify'd text inside an
// onclick="..." attribute and a stray double quote in the generated text
// silently truncated the handler. The edit form below avoids the same
// class of bug a second way — it builds empty inputs from a static
// template and fills them in via .value afterward, so a script
// containing a quote can never break out of an attribute at all.
// ---------------------------------------------------------------------

let notebookState = null;

function initScriptNotebook() {
  const root = document.getElementById("script-notebook");
  if (!root) return;

  notebookState = {
    key: root.dataset.key,
    topicId: root.dataset.topicId,
    subtopics: JSON.parse(root.dataset.subtopics || "[]"),
    selectedIndex: 0,
    editing: false,
  };
  const hash = window.location.hash.slice(1);
  if (hash) {
    const idx = notebookState.subtopics.findIndex((s) => s.id === hash);
    if (idx >= 0) notebookState.selectedIndex = idx;
  }
  renderNotebook();
  document.addEventListener("keydown", notebookKeys);
}

function notebookKeys(e) {
  if (!notebookState) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || e.metaKey || e.ctrlKey) return;
  if (e.key === "ArrowRight") { e.preventDefault(); selectNotebookTab(notebookState.selectedIndex + 1); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); selectNotebookTab(notebookState.selectedIndex - 1); }
}

function selectNotebookTab(index) {
  const n = notebookState.subtopics.length;
  notebookState.selectedIndex = ((index % n) + n) % n;
  notebookState.editing = false;
  renderNotebook();
}

function renderNotebook() {
  const root = document.getElementById("script-notebook");
  const {subtopics, selectedIndex} = notebookState;
  const current = subtopics[selectedIndex];
  history.replaceState(null, "", `#${current.id}`);

  const tabs = subtopics.map((s, i) => `
    <button type="button"
            class="notebook-tab ${i === selectedIndex ? "selected" : ""} ${!s.script ? "no-script" : ""}"
            data-tab-index="${i}">${escapeHtml(s.title)}</button>`).join("");

  root.innerHTML = `
    <div class="notebook-tabs">${tabs}</div>
    <div class="notebook-panel card" id="notebook-panel"></div>`;

  for (const btn of root.querySelectorAll("[data-tab-index]")) {
    btn.addEventListener("click", () => selectNotebookTab(Number(btn.dataset.tabIndex)));
  }
  renderNotebookPanel();
}

function renderNotebookPanel() {
  const panel = document.getElementById("notebook-panel");
  const current = notebookState.subtopics[notebookState.selectedIndex];

  if (notebookState.editing) {
    panel.innerHTML = editScriptForm();
    wireEditForm(current);
    return;
  }

  if (!current.script) {
    panel.innerHTML = `
      <p class="meta"><strong>${escapeHtml(current.title)}</strong></p>
      ${current.angle ? `<p class="hint">${escapeHtml(current.angle)}</p>` : ""}
      <p class="meta">No script yet.</p>
      <div class="actions">
        <button type="button" class="btn btn-primary" data-write-one-btn>Write this one</button>
      </div>
      <p class="hint" id="notebook-status"></p>`;
    panel.querySelector("[data-write-one-btn]")
      .addEventListener("click", (e) => regenerateNotebookScript(e.target, ""));
    return;
  }

  const script = current.script;
  const segmentsHtml = script.segments.map((seg) => `
    <div class="notebook-segment">
      <p class="notebook-segment-text">${escapeHtml(seg.text)}</p>
      <p class="hint">shot: ${escapeHtml(seg.shot_brief || "")}</p>
      <p class="hint">keywords: ${escapeHtml((seg.keywords || []).join(", "))}</p>
    </div>`).join("");

  panel.innerHTML = `
    <p class="meta"><strong>${escapeHtml(current.title)}</strong></p>
    ${current.angle ? `<p class="hint">${escapeHtml(current.angle)}</p>` : ""}
    ${(script.title_options || []).length
      ? `<p class="meta">Title options: ${script.title_options.map(escapeHtml).join(" &middot; ")}</p>` : ""}
    ${segmentsHtml}
    ${script.description_body
      ? `<details><summary class="summary-heading">Description</summary>
          <p class="hint">${escapeHtml(script.description_body)}</p></details>` : ""}
    <div class="actions">
      <button type="button" class="btn-ghost" data-regenerate-btn>Regenerate</button>
      <button type="button" class="btn-ghost" data-edit-btn>Edit</button>
    </div>
    <div class="notebook-instruction">
      <label>Regenerate with instructions
        <input type="text" id="notebook-instruction" placeholder="Also mention…">
      </label>
      <button type="button" class="btn-ghost" data-regenerate-prompted-btn>Regenerate with this</button>
    </div>
    <p class="hint" id="notebook-status"></p>`;

  panel.querySelector("[data-regenerate-btn]")
    .addEventListener("click", (e) => regenerateNotebookScript(e.target, ""));
  panel.querySelector("[data-regenerate-prompted-btn]")
    .addEventListener("click", (e) =>
      regenerateNotebookScript(e.target, document.getElementById("notebook-instruction").value));
  panel.querySelector("[data-edit-btn]").addEventListener("click", () => {
    notebookState.editing = true;
    renderNotebookPanel();
  });
}

async function regenerateNotebookScript(button, instruction) {
  const current = notebookState.subtopics[notebookState.selectedIndex];
  await withButtonLoading(button, "Writing…", async () => {
    const res = await apiFetch(
      `/api/channels/${notebookState.key}/curriculum/${current.id}/regenerate-script`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({instruction: instruction || ""}),
      });
    const data = await res.json();
    const status = document.getElementById("notebook-status");
    if (!res.ok) { if (status) status.textContent = data.error || "Couldn't write that script."; return; }
    current.script = data.script;
    renderNotebookPanel();
    renderNotebookTabsOnly();
  });
}

// Redraws just the tab strip's "no-script" state after a write, without
// losing the panel that was just re-rendered above it.
function renderNotebookTabsOnly() {
  const root = document.getElementById("script-notebook");
  const {subtopics, selectedIndex} = notebookState;
  const tabStrip = root.querySelector(".notebook-tabs");
  if (!tabStrip) return;
  tabStrip.innerHTML = subtopics.map((s, i) => `
    <button type="button"
            class="notebook-tab ${i === selectedIndex ? "selected" : ""} ${!s.script ? "no-script" : ""}"
            data-tab-index="${i}">${escapeHtml(s.title)}</button>`).join("");
  for (const btn of tabStrip.querySelectorAll("[data-tab-index]")) {
    btn.addEventListener("click", () => selectNotebookTab(Number(btn.dataset.tabIndex)));
  }
}

// The edit form's markup carries no dynamic text at all — every field
// starts empty and is filled in afterward via .value, which is always
// safe regardless of what characters the script contains.
function editScriptForm() {
  const current = notebookState.subtopics[notebookState.selectedIndex];
  const segmentCount = current.script ? current.script.segments.length : 1;
  const rowsHtml = Array.from({length: segmentCount}, (_, i) => notebookSegmentRowHtml(i + 1)).join("");

  return `
    <form method="post"
          action="/channels/${notebookState.key}/curriculum/${current.id}/edit-script"
          class="channel-form" id="notebook-edit-form">
      <input type="hidden" name="csrf_token" value="${CSRF_TOKEN}">
      <div id="notebook-edit-segments">${rowsHtml}</div>
      <button type="button" class="btn-ghost" id="notebook-add-segment">Add another segment</button>
      <label>Title options (one per line)
        <textarea name="title_options" rows="3"></textarea>
      </label>
      <label>Description
        <textarea name="description_body" rows="3"></textarea>
      </label>
      <div class="actions">
        <button type="submit" class="btn btn-primary">Save</button>
        <button type="button" class="btn-ghost" id="notebook-cancel-edit">Cancel</button>
      </div>
    </form>`;
}

function notebookSegmentRowHtml(number) {
  return `
    <div class="notebook-edit-segment">
      <label>Segment ${number} text
        <textarea name="segment_text" rows="2"></textarea>
      </label>
      <label>Shot brief
        <input type="text" name="segment_shot_brief">
      </label>
      <label>Keywords (comma separated)
        <input type="text" name="segment_keywords">
      </label>
    </div>`;
}

function wireEditForm(current) {
  const script = current.script || {segments: [{text: "", shot_brief: "", keywords: []}],
                                    title_options: [], description_body: ""};
  const rows = document.querySelectorAll("#notebook-edit-segments .notebook-edit-segment");
  script.segments.forEach((seg, i) => {
    const row = rows[i];
    if (!row) return;
    row.querySelector('[name="segment_text"]').value = seg.text || "";
    row.querySelector('[name="segment_shot_brief"]').value = seg.shot_brief || "";
    row.querySelector('[name="segment_keywords"]').value = (seg.keywords || []).join(", ");
  });
  document.querySelector('#notebook-edit-form [name="title_options"]').value =
    (script.title_options || []).join("\n");
  document.querySelector('#notebook-edit-form [name="description_body"]').value =
    script.description_body || "";

  document.getElementById("notebook-add-segment").addEventListener("click", () => {
    const container = document.getElementById("notebook-edit-segments");
    const div = document.createElement("div");
    div.innerHTML = notebookSegmentRowHtml(container.children.length + 1);
    container.appendChild(div.firstElementChild);
  });
  document.getElementById("notebook-cancel-edit").addEventListener("click", () => {
    notebookState.editing = false;
    renderNotebookPanel();
  });
}

async function writeTopicScripts(key, topicId) {
  const button = document.getElementById(`write-scripts-${topicId}`);
  const status = document.getElementById("write-scripts-status");
  if (status) status.textContent = "";
  await withButtonLoading(button, "Writing…", async () => {
    const res = await apiFetch(`/api/channels/${key}/curriculum/${topicId}/write-scripts`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) {
      if (status) status.textContent = data.error || "Couldn't write those scripts.";
      else alert(data.error || "Couldn't write those scripts.");
      return;
    }
    window.location.href = `/channels/${key}/curriculum/${topicId}/scripts`;
  });
}

document.addEventListener("DOMContentLoaded", initScriptNotebook);

