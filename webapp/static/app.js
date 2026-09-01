// Vanilla JS, no build step — matches the rest of this project's
// zero-dependency-tooling style.

let currentSeed = null;
let pollTimer = null;
let seenLogLength = 0;

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

    document.getElementById("seed-preview").classList.add("hidden");
    document.getElementById("job-progress").classList.remove("hidden");
    seenLogLength = 0;
    document.getElementById("job-log").textContent = "";
    pollJob(data.job_id);
  });
}

function pollJob(jobId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) return;
    const job = await res.json();

    const logEl = document.getElementById("job-log");
    if (job.log.length > seenLogLength) {
      logEl.textContent += job.log.slice(seenLogLength).join("\n") + "\n";
      seenLogLength = job.log.length;
      logEl.scrollTop = logEl.scrollHeight;
    }
    document.getElementById("job-current").textContent = job.current_progress || "";

    if (job.status === "done") {
      clearInterval(pollTimer);
      document.getElementById("job-progress").classList.add("hidden");
      document.getElementById("job-result").classList.remove("hidden");
      const videoUrl = `/videos/${job.result_path_rel}`;
      const videoEl = document.getElementById("result-video");
      videoEl.src = videoUrl;
      document.getElementById("result-link").href = videoUrl;
    } else if (job.status === "error") {
      clearInterval(pollTimer);
      logEl.textContent += "\n--- ERROR ---\n" + job.error;
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
