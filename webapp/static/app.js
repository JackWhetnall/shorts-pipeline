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

async function getSeed(channelKey) {
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
}

async function startGenerate(channelKey) {
  if (!currentSeed) return;
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
  const res = await fetch("/api/voice-lab/refresh-voices", {method: "POST"});
  const data = await res.json();
  if (!res.ok) {
    alert(data.error || "Failed to refresh the voice list.");
    return;
  }
  location.reload();
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

  const button = document.querySelector('button[onclick="testVoiceCombo()"]');
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Generating… (first time for this combo can take a bit)";

  try {
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
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}
