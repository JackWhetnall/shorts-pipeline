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
  document.getElementById("seed-preview").classList.add("hidden");
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

async function getSeed(channelKey) {
  await withButtonLoading(event.target.closest("button"), "Fetching…", async () => {
    const res = await fetch(`/api/channels/${channelKey}/seed`, {method: "POST"});
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

    document.getElementById("seed-idle").classList.add("hidden");
    document.getElementById("seed-preview").classList.remove("hidden");
  });
}

async function startGenerate(channelKey) {
  if (!currentSeed) return;
  await withButtonLoading(event.target.closest("button"), "Starting…", async () => {
    const res = await fetch(`/api/channels/${channelKey}/generate`, {
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
    const res = await fetch(`/api/channels/${channelKey}/current-job`);
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
    const res = await fetch(`/api/channels/${channelKey}/last-failed-job`);
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
// webapp/jobs.py's _STAGE_MARKERS). A stage is "done" once job.stage has
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
// up via job_context.report_detail (see webapp/jobs.py's _update_detail
// and tts_captions.py/footage_library.py's calls into it). Re-rendered
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
// completed (script/voiceover/footage picks - see webapp/jobs.py's
// retry_job and the checkpointing in main.py/tts_captions.py/
// footage_library.py) rather than starting over from nothing. Available
// on both a live "error"/"interrupted" job (shown by pollJob below) and
// a past one surfaced on page load (resumeRunningJob).
async function retryCurrentJob() {
  if (!currentJobId) return;
  const btn = document.getElementById("job-retry-btn");
  await withButtonLoading(btn, "Retrying…", async () => {
    let res;
    try {
      res = await fetch(`/api/jobs/${currentJobId}/retry`, {method: "POST"});
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
// itself persists to disk and reloads at startup (see webapp/jobs.py's
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
      res = await fetch(`/api/jobs/${jobId}`);
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
      // job.error is a plain-English summary (webapp/jobs.py's
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

function toggleContentModeFields() {
  const select = document.getElementById("content-mode-select");
  if (!select) return;
  const staticFields = document.getElementById("static_corpus-fields");
  const topicFields = document.getElementById("topic-fields");
  if (staticFields) staticFields.classList.toggle("hidden", select.value !== "static_corpus");
  if (topicFields) topicFields.classList.toggle("hidden", select.value !== "topic");
}

document.addEventListener("DOMContentLoaded", toggleContentModeFields);

// --- Voice Lab ---

async function refreshVoiceList() {
  await withButtonLoading(event.target.closest("button"), "Refreshing…", async () => {
    const res = await fetch("/api/voice-lab/refresh-voices", {method: "POST"});
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
    const res = await fetch("/api/voice-lab/test", {
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
    const res = await fetch(`/api/channels/${channelKey}/logo/generate`, {
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
  const res = await fetch(`/api/channels/${channelKey}/logo/select`, {
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
    const res = await fetch(`/api/channels/${channelKey}/logo/variants/generate`, {method: "POST"});
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
        await fetch("/api/channels/reorder", {
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
    const res = await fetch(`/channels/${channelKey}/generate-now`, {method: "POST"});
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
    const res = await fetch("/api/channels/generate-all", {method: "POST"});
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
        const res = await fetch(`/api/jobs/${jobId}`);
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
        // server restarts (see webapp/jobs.py's load_persisted_jobs).
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
    const res = await fetch(`/channels/${channelKey}/videos/discard`, {
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
