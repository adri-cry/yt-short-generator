// Minimal UI glue. No framework; just fetch + EventSource.

const $ = (sel) => document.querySelector(sel);

const form = $("#job-form");
const submitBtn = $("#submit-btn");
const formHint = $("#form-hint");
const currentCard = $("#current-card");
const currentStatus = $("#current-status");
const currentMeta = $("#current-meta");
const logsEl = $("#logs");
const resultEl = $("#current-result");
const historyEl = $("#history");

let activeStream = null;
let currentJobId = null;

async function loadDefaults() {
  try {
    const d = await fetch("/api/defaults").then((r) => r.json());
    $("#subtitles").checked = !!d.subtitles;
    $("#num_clips").value = d.num_clips || 3;
    $("#aspect_ratio").value = d.aspect_ratio || "9:16";
    $("#download_format").value = d.download_format || "720";
    $("#mode").value = d.mode || "local";
    if (typeof d.min_duration === "number") $("#min_duration").value = d.min_duration;
    if (typeof d.max_duration === "number") $("#max_duration").value = d.max_duration;
    // Leave the Whisper dropdown on "default" — the selected option
    // falls back to LOCAL_WHISPER_MODEL server-side.
  } catch (e) {
    /* ignore — defaults in the HTML are fine */
  }
}

async function refreshHistory() {
  try {
    const { jobs } = await fetch("/api/jobs?limit=25").then((r) => r.json());
    historyEl.innerHTML = "";
    for (const j of jobs) {
      const li = document.createElement("li");
      const url = j.params.youtube_url || "(no url)";
      const when = j.created_at ? new Date(j.created_at * 1000).toLocaleTimeString() : "";
      li.innerHTML = `
        <span class="status ${j.status}">${j.status}</span>
        <span class="h-id">${j.id}</span>
        <span class="h-url" title="${escapeHtml(url)}">${escapeHtml(url)}</span>
        <span class="h-time">${when}</span>
      `;
      li.addEventListener("click", () => openJob(j.id));
      historyEl.appendChild(li);
    }
  } catch (e) {
    // leave prior list untouched
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMeta(job) {
  const p = job.params || {};
  const bits = [
    `id: ${job.id}`,
    `mode: ${p.mode}`,
    `clips: ${p.num_clips}`,
    `ratio: ${p.aspect_ratio}`,
    `subs: ${p.subtitles === false ? "off" : "on"}`,
  ];
  if (p.min_duration || p.max_duration) {
    bits.push(`duration: ${p.min_duration || "?"}-${p.max_duration || "?"}s`);
  }
  if (p.whisper_model) bits.push(`whisper: ${p.whisper_model}`);
  if (p.language) bits.push(`lang: ${p.language}`);
  if (p.initial_prompt) bits.push(`prompt: "${p.initial_prompt.slice(0, 40)}${p.initial_prompt.length > 40 ? "..." : ""}"`);
  currentMeta.textContent = bits.join("  ·  ");
}

function renderResult(job) {
  if (job.status !== "succeeded" || !job.result) {
    if (job.status === "failed" && job.error) {
      resultEl.hidden = false;
      resultEl.innerHTML = `<div class="hint" style="color: var(--err)">${escapeHtml(job.error)}</div>`;
    } else {
      resultEl.hidden = true;
      resultEl.innerHTML = "";
    }
    return;
  }

  const shorts = job.result.shorts || [];
  if (!shorts.length) {
    resultEl.hidden = false;
    resultEl.innerHTML = `<div class="hint">Job finished, but no clips were rendered.</div>`;
    return;
  }

  const cards = shorts.map((s) => {
    const src = toClipUrl(s.clip_url);
    const hook = s.hook_sentence || s.virality_reason || "";
    return `
      <div class="short-card">
        ${src
          ? `<video controls preload="metadata" src="${escapeHtml(src)}"></video>`
          : `<div class="sc-body" style="padding:20px;color:var(--err)">Render failed${
              s.error ? `: ${escapeHtml(s.error)}` : ""
            }</div>`}
        <div class="sc-body">
          ${typeof s.score === "number" ? `<span class="sc-score">score ${s.score}</span>` : ""}
          <div class="sc-title">${escapeHtml(s.title || "(untitled)")}</div>
          <div class="sc-hook">${escapeHtml(hook)}</div>
          ${src ? `<a class="sc-link" href="${escapeHtml(src)}" download>download</a>` : ""}
        </div>
      </div>
    `;
  });

  resultEl.hidden = false;
  resultEl.innerHTML = `<div class="shorts-grid">${cards.join("")}</div>`;
}

function toClipUrl(clipUrl) {
  if (!clipUrl) return null;
  // API mode returns an https URL — use directly.
  if (/^https?:\/\//i.test(clipUrl)) return clipUrl;
  // Local mode returns "output\short_01.mp4" — serve via /clips/<relpath>.
  const normalised = clipUrl.replace(/\\/g, "/");
  // Strip leading output dir if present so /clips/short_01.mp4 resolves.
  const withoutOutput = normalised.replace(/^output\//, "");
  return `/clips/${encodeURIComponent(withoutOutput)}`;
}

async function openJob(jobId) {
  currentJobId = jobId;
  currentCard.hidden = false;
  logsEl.textContent = "";
  resultEl.hidden = true;

  const job = await fetch(`/api/jobs/${jobId}`).then((r) => r.json());
  currentStatus.className = `status ${job.status}`;
  currentStatus.textContent = job.status;
  renderMeta(job);
  if (job.logs && job.logs.length) {
    logsEl.textContent = job.logs.join("\n") + "\n";
    logsEl.scrollTop = logsEl.scrollHeight;
  }

  if (job.status === "succeeded" || job.status === "failed") {
    renderResult(job);
    return;
  }

  startLogStream(jobId);
}

function startLogStream(jobId) {
  if (activeStream) {
    activeStream.close();
    activeStream = null;
  }
  const es = new EventSource(`/api/jobs/${jobId}/logs`);
  activeStream = es;

  es.onmessage = (ev) => {
    if (!ev.data) return;
    let data;
    try {
      data = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (data.line) {
      appendLog(data.line);
    }
    if (data.event === "done") {
      currentStatus.className = `status ${data.status}`;
      currentStatus.textContent = data.status;
      // Refresh full job detail for the rendered result.
      fetch(`/api/jobs/${jobId}`)
        .then((r) => r.json())
        .then(renderResult)
        .catch(() => {});
      refreshHistory();
      es.close();
      activeStream = null;
    }
  };
  es.onerror = () => {
    // let the browser auto-reconnect unless the job is already finished
  };
}

function appendLog(line) {
  const atBottom = logsEl.scrollTop + logsEl.clientHeight >= logsEl.scrollHeight - 20;
  logsEl.textContent += line + "\n";
  if (atBottom) logsEl.scrollTop = logsEl.scrollHeight;
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  submitBtn.disabled = true;
  formHint.textContent = "submitting...";

  const minDur = parseInt($("#min_duration").value, 10) || 45;
  const maxDur = parseInt($("#max_duration").value, 10) || 90;
  if (maxDur < minDur) {
    formHint.textContent = `max duration (${maxDur}s) must be >= min duration (${minDur}s)`;
    submitBtn.disabled = false;
    return;
  }

  const body = {
    youtube_url: $("#youtube_url").value.trim(),
    mode: $("#mode").value,
    num_clips: parseInt($("#num_clips").value, 10) || 3,
    aspect_ratio: $("#aspect_ratio").value,
    download_format: $("#download_format").value,
    language: $("#language").value.trim() || null,
    subtitles: $("#subtitles").checked,
    min_duration: minDur,
    max_duration: maxDur,
    whisper_model: $("#whisper_model").value || null,
    initial_prompt: $("#initial_prompt").value.trim() || null,
  };

  try {
    const resp = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const err = await resp.text();
      formHint.textContent = `failed: ${err}`;
      submitBtn.disabled = false;
      return;
    }
    const job = await resp.json();
    formHint.textContent = `queued as ${job.id}`;
    await openJob(job.id);
    refreshHistory();
  } catch (e) {
    formHint.textContent = `failed: ${e}`;
  } finally {
    submitBtn.disabled = false;
    setTimeout(() => { formHint.textContent = ""; }, 4000);
  }
});

loadDefaults();
refreshHistory();
setInterval(refreshHistory, 5000);
