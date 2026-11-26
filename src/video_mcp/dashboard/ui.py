"""Self-contained HTML/CSS/JS single-page dashboard UI."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Video Automation MCP — Live Dashboard</title>
  <style>
    :root {
      --bg: #0b0f17;
      --panel: #131a26;
      --panel-2: #1a2333;
      --border: #263248;
      --text: #e6edf7;
      --muted: #8fa1bc;
      --accent: #4f8cff;
      --green: #22c55e;
      --amber: #f59e0b;
      --red: #ef4444;
      --purple: #a855f7;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 16px 24px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 12px; font-weight: 700; font-size: 17px; }
    .live-pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
      background: rgba(34, 197, 94, 0.14); color: var(--green); border: 1px solid rgba(34, 197, 94, 0.35);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); animation: pulse 1.6s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
    nav { display: flex; gap: 8px; }
    .tab-btn {
      background: transparent; color: var(--muted); border: 1px solid transparent;
      padding: 8px 14px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 13px;
    }
    .tab-btn.active { background: var(--panel-2); color: var(--text); border-color: var(--border); }
    main { max-width: 1320px; margin: 0 auto; padding: 20px 24px 48px; }
    .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 20px; }
    .kpi {
      background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
    }
    .kpi-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
    .kpi-val { font-size: 26px; font-weight: 700; margin-top: 4px; }
    .grid-2 { display: grid; grid-template-columns: 1.55fr 1fr; gap: 18px; }
    @media (max-width: 980px) { .grid-2 { grid-template-columns: 1fr; } }
    .card {
      background: var(--panel); border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
    }
    .card-head {
      display: flex; justify-content: space-between; align-items: center;
      padding: 12px 16px; border-bottom: 1px solid var(--border); font-weight: 600; font-size: 14px;
    }
    .card-body { padding: 14px 16px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--border); }
    th { color: var(--muted); font-weight: 600; font-size: 12px; }
    tr.clickable:hover { background: var(--panel-2); cursor: pointer; }
    .badge {
      display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.03em;
    }
    .b-draft { background: rgba(143,161,188,0.16); color: var(--muted); }
    .b-rendering { background: rgba(79,140,255,0.2); color: var(--accent); }
    .b-ready_for_review { background: rgba(168,85,247,0.2); color: var(--purple); }
    .b-pending_approval { background: rgba(245,158,11,0.2); color: var(--amber); }
    .b-approved, .b-published { background: rgba(34,197,94,0.2); color: var(--green); }
    .b-rejected, .b-failed { background: rgba(239,68,68,0.2); color: var(--red); }
    .activity-list { max-height: 500px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; }
    .act-item {
      background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; font-size: 13px;
    }
    .act-meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); margin-bottom: 3px; }
    .btn {
      background: var(--accent); color: #fff; border: none; border-radius: 8px;
      padding: 7px 12px; font-size: 12px; font-weight: 600; cursor: pointer;
    }
    .btn-sec { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); }
    .btn-green { background: #16a34a; }
    .btn-red { background: #dc2626; }
    .btn:disabled { opacity: 0.45; cursor: not-allowed; }
    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 760px) { .form-grid { grid-template-columns: 1fr; } }
    label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; font-weight: 600; }
    input[type="text"], input[type="number"], textarea {
      width: 100%; background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 8px 10px; font-size: 13px;
    }
    .hidden { display: none; }
    .thumbs { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 8px; }
    .thumbs img { max-width: 200px; border-radius: 8px; border: 1px solid var(--border); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .toast {
      position: fixed; bottom: 20px; right: 20px; background: var(--panel-2);
      border: 1px solid var(--accent); color: var(--text); padding: 10px 16px;
      border-radius: 10px; font-size: 13px; z-index: 50; display: none;
    }
    .upload-box {
      display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
      padding: 14px 16px; border: 1px dashed var(--border); border-radius: 10px;
      background: var(--panel-2); transition: border-color 0.2s;
    }
    .upload-box.dragover { border-color: var(--accent); }
    select {
      background: var(--panel); color: var(--text); border: 1px solid var(--border);
      border-radius: 8px; padding: 8px 10px; font-size: 13px;
    }
    .progress-wrap { width: 100%; height: 6px; background: var(--panel); border-radius: 999px; overflow: hidden; display: none; }
    .progress-bar { height: 100%; width: 0%; background: var(--accent); transition: width 0.15s; }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span>Video Automation MCP</span>
      <span class="live-pill"><span class="dot"></span><span id="conn-label">LIVE</span></span>
    </div>
    <nav>
      <button class="tab-btn active" onclick="switchTab('live', this)">Live Processing</button>
      <button class="tab-btn" onclick="switchTab('config', this)">Configuration</button>
      <button class="tab-btn" onclick="refreshAll()">Refresh</button>
    </nav>
  </header>

  <main>
    <section id="tab-live">
      <div class="kpis" id="kpis"></div>

      <div class="card" style="margin-bottom: 18px;">
        <div class="card-head">
          <span>Ingest Video (Device Upload or YouTube / URL)</span>
          <span class="mono" id="upload-status">Ready</span>
        </div>
        <div class="card-body">
          <div class="upload-box" id="drop-zone">
            <input type="file" id="video-file" accept="video/*,.mp4,.mov,.mkv,.webm" />
            <input type="text" id="upload-title" placeholder="Job title (optional)" style="max-width: 200px;" />
            <select id="upload-profile">
              <option value="both">Both (16:9 + 9:16 + metadata)</option>
              <option value="landscape_16x9">Landscape 16:9</option>
              <option value="vertical_9x16">Vertical 9:16</option>
            </select>
            <label style="display:inline-flex;align-items:center;gap:6px;margin:0;cursor:pointer;">
              <input type="checkbox" id="upload-autorender" checked />
              <span>Auto-render</span>
            </label>
            <label style="display:inline-flex;align-items:center;gap:6px;margin:0;cursor:pointer;">
              <input type="checkbox" id="upload-autocaption" />
              <span>Auto-caption (Whisper)</span>
            </label>
            <button class="btn" id="upload-btn" onclick="uploadSelectedVideo()">Upload File</button>
            <div style="width:100%;display:flex;gap:10px;align-items:center;margin-top:4px;">
              <input type="text" id="ingest-url" placeholder="Paste YouTube URL (youtube.com / youtu.be / shorts) or HTTP/S3 URL..." style="flex:1;" />
              <button class="btn btn-sec" id="ingest-url-btn" onclick="ingestUrl()">Ingest YouTube / URL</button>
            </div>
            <div class="progress-wrap" id="upload-progress-wrap">
              <div class="progress-bar" id="upload-progress-bar"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="card" style="margin-bottom: 18px;">
        <div class="card-head">
          <span>Clip Viral Dialogue (Transcript Search)</span>
          <span class="mono" id="dialogue-status">Select a source</span>
        </div>
        <div class="card-body">
          <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
            <select id="dialogue-source" style="min-width:220px;max-width:300px;"></select>
            <input type="text" id="dialogue-query" placeholder="Search dialogue (e.g. 'clutch') or leave blank for top moments" style="flex:1;min-width:220px;" />
            <input type="number" id="dialogue-padding" value="2" min="0" max="15" step="0.5" style="width:90px;" title="Buffer seconds before/after" />
            <button class="btn" id="dialogue-search-btn" onclick="findDialogueMoments()">Find &amp; Clip</button>
          </div>
          <div id="dialogue-results" style="margin-top:12px;"></div>
        </div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-head">
            <span>Processing Jobs</span>
            <span class="mono" id="jobs-count">0 jobs</span>
          </div>
          <div class="card-body" style="padding: 0 12px 12px; overflow-x: auto;">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Profile</th>
                  <th>Status</th>
                  <th>Ops</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody id="jobs-tbody"></tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <span>Live Activity Feed</span>
            <span class="mono" id="act-count">0 events</span>
          </div>
          <div class="card-body">
            <div class="activity-list" id="activity-list"></div>
          </div>
        </div>
      </div>

      <div class="card" id="inspector-card" style="margin-top: 18px; display: none;">
        <div class="card-head">
          <span id="insp-title">Job Inspector</span>
          <button class="btn btn-sec" onclick="closeInspector()">Close</button>
        </div>
        <div class="card-body" id="insp-body"></div>
      </div>
    </section>

    <section id="tab-config" class="hidden">
      <div class="card">
        <div class="card-head">
          <span>Server &amp; Pipeline Configuration</span>
          <span class="mono" id="cfg-path"></span>
        </div>
        <div class="card-body">
          <form id="config-form" onsubmit="saveConfig(event)">
            <div class="form-grid">
              <div>
                <label>Allowed Local Roots (comma-separated)</label>
                <input type="text" id="cfg-roots" />
              </div>
              <div>
                <label>Release Directory</label>
                <input type="text" id="cfg-release" />
              </div>
              <div>
                <label>Webhook URL (optional)</label>
                <input type="text" id="cfg-webhook" placeholder="https://..." />
              </div>
              <div>
                <label>FFmpeg Timeout (seconds)</label>
                <input type="number" id="cfg-ffmpeg-timeout" min="10" />
              </div>
              <div>
                <label>Max Remote Download (MiB)</label>
                <input type="number" id="cfg-max-dl" min="1" />
              </div>
              <div>
                <label>Download Timeout (seconds)</label>
                <input type="number" id="cfg-dl-timeout" min="5" />
              </div>
            </div>
            <div style="margin-top: 14px; display: flex; align-items: center; gap: 8px;">
              <input type="checkbox" id="cfg-private-urls" />
              <label for="cfg-private-urls" style="margin: 0;">Allow Private/Localhost URLs (disable SSRF block for local testing)</label>
            </div>
            <div style="margin-top: 16px;">
              <button type="submit" class="btn">Save Configuration</button>
            </div>
          </form>
        </div>
      </div>
    </section>
  </main>

  <div class="toast" id="toast"></div>

  <script>
    let selectedJobId = null;
    let lastInspectedSig = null;

    function showToast(msg) {
      const el = document.getElementById("toast");
      el.textContent = msg;
      el.style.display = "block";
      setTimeout(() => { el.style.display = "none"; }, 3200);
    }

    function switchTab(name, btn) {
      document.getElementById("tab-live").classList.toggle("hidden", name !== "live");
      document.getElementById("tab-config").classList.toggle("hidden", name !== "config");
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      if (btn) btn.classList.add("active");
      if (name === "config") loadConfig();
    }

    function fmtTime(iso) {
      if (!iso) return "";
      return new Date(iso).toLocaleTimeString();
    }

    async function refreshAll() {
      const res = await fetch("/api/overview");
      const data = await res.json();
      renderKPIs(data.summary);
      renderJobs(data.jobs);
      renderActivity(data.activity);
      renderSourceSelect(data.sources || []);
      if (selectedJobId) {
        const job = data.jobs.find(j => j.job_id === selectedJobId);
        if (job) renderInspector(job);
      }
    }

    function renderSourceSelect(sources) {
      const sel = document.getElementById("dialogue-source");
      if (!sel) return;
      const prev = sel.value;
      if (!sources.length) {
        sel.innerHTML = `<option value="">No sources ingested yet</option>`;
        return;
      }
      sel.innerHTML = sources.map(s => {
        const label = (s.probe && s.probe.youtube && s.probe.youtube.title) || s.filename;
        return `<option value="${s.source_id}">${label} (${s.source_id})</option>`;
      }).join("");
      if (prev && sources.some(s => s.source_id === prev)) sel.value = prev;
    }

    async function findDialogueMoments() {
      const sourceId = document.getElementById("dialogue-source").value;
      const query = document.getElementById("dialogue-query").value.trim();
      const padding = Number(document.getElementById("dialogue-padding").value || 2);
      const statusEl = document.getElementById("dialogue-status");
      const outEl = document.getElementById("dialogue-results");
      const btn = document.getElementById("dialogue-search-btn");
      if (!sourceId) {
        showToast("Ingest or upload a video first.");
        return;
      }
      btn.disabled = true;
      statusEl.textContent = "Transcribing / searching...";
      try {
        const res = await fetch(`/api/sources/${sourceId}/find_dialogue`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: query || null, padding_sec: padding, limit: 8 }),
        });
        const data = await res.json();
        if (!res.ok) {
          statusEl.textContent = "Search failed";
          showToast(`Error: ${data.error || res.status}`);
          return;
        }
        statusEl.textContent = `${data.match_count} match(es)`;
        if (!data.matches.length) {
          outEl.innerHTML = `<div style="color:var(--muted);font-size:13px;">No matching spoken dialogue found.</div>`;
          return;
        }
        outEl.innerHTML = data.matches.map((m, idx) => `
          <div class="act-item" style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:6px;">
            <div>
              <div class="mono" style="color:var(--accent)">[${m.start_sec}s → ${m.end_sec}s] (score: ${m.score})</div>
              <div>"${m.text}"</div>
            </div>
            <button class="btn" onclick="clipDialogueMoment('${sourceId}', ${m.start_sec}, ${m.end_sec}, ${idx})">Clip &amp; Render</button>
          </div>
        `).join("");
      } catch (err) {
        statusEl.textContent = "Search error";
        showToast(String(err));
      } finally {
        btn.disabled = false;
      }
    }

    async function clipDialogueMoment(sourceId, startSec, endSec, idx) {
      const profile = document.getElementById("upload-profile").value;
      const captionChecked = document.getElementById("upload-autocaption").checked;
      const ops = [{ op: "trim", start_sec: startSec, end_sec: endSec }];
      if (captionChecked) ops.push({ op: "auto_caption" });
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: `Viral Clip #${idx + 1} (${startSec}s-${endSec}s)`,
          source_ids: [sourceId],
          output_profile: profile,
          operations: ops,
          auto_render: true,
        }),
      });
      const data = await res.json();
      if (res.ok && data.job) {
        showToast(`Started clipping ${data.job.job_id}`);
        await refreshAll();
      } else {
        showToast(`Clip error: ${data.error || res.status}`);
      }
    }

    function renderKPIs(s) {
      const items = [
        ["Active Rendering", s.rendering || 0],
        ["Pending Approval", s.pending_approval || 0],
        ["Ready for Review", s.ready_for_review || 0],
        ["Published", s.published || 0],
        ["Total Jobs", s.total_jobs || 0],
        ["Ingested Sources", s.total_sources || 0],
      ];
      document.getElementById("kpis").innerHTML = items.map(([k, v]) =>
        `<div class="kpi"><div class="kpi-label">${k}</div><div class="kpi-val">${v}</div></div>`
      ).join("");
    }

    function renderJobs(jobs) {
      document.getElementById("jobs-count").textContent = `${jobs.length} jobs`;
      const tbody = document.getElementById("jobs-tbody");
      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted);">No jobs yet. Use MCP tools to ingest &amp; create a job.</td></tr>`;
        return;
      }
      tbody.innerHTML = jobs.map(j => `
        <tr class="clickable" onclick="selectJob('${j.job_id}')">
          <td><strong>${j.title}</strong><div class="mono" style="color:var(--muted)">${j.job_id}</div></td>
          <td class="mono">${j.output_profile}</td>
          <td><span class="badge b-${j.status}">${j.status.replaceAll("_", " ")}</span></td>
          <td>${(j.operations || []).length}</td>
          <td class="mono">${fmtTime(j.updated_at)}</td>
        </tr>
      `).join("");
    }

    function renderActivity(events) {
      document.getElementById("act-count").textContent = `${events.length} events`;
      const list = document.getElementById("activity-list");
      if (!events.length) {
        list.innerHTML = `<div style="color:var(--muted);font-size:13px;">No activity recorded yet.</div>`;
        return;
      }
      list.innerHTML = events.map(e => `
        <div class="act-item">
          <div class="act-meta">
            <span class="mono">[${e.category.toUpperCase()}] ${e.job_id || ""}</span>
            <span>${fmtTime(e.created_at)}</span>
          </div>
          <div>${e.message}</div>
        </div>
      `).join("");
    }

    async function selectJob(jobId) {
      selectedJobId = jobId;
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) return;
      const data = await res.json();
      renderInspector(data.job);
    }

    function closeInspector() {
      selectedJobId = null;
      lastInspectedSig = null;
      document.getElementById("inspector-card").style.display = "none";
    }

    function renderInspector(job) {
      const sig = `${job.job_id}:${job.status}:${job.updated_at}:${(job.artifacts || []).length}`;
      if (sig === lastInspectedSig) return;
      lastInspectedSig = sig;
      const card = document.getElementById("inspector-card");
      card.style.display = "block";
      document.getElementById("insp-title").textContent = `Job Inspector — ${job.title} (${job.job_id})`;

      const videos = (job.artifacts || []).filter(a => a.kind.startsWith("video_"));
      const thumbs = (job.artifacts || []).filter(a => a.kind === "thumbnail");
      const actions = [];
      const hasAutoCaption = (job.operations || []).some(op => op.op === "auto_caption");
      if (["draft", "ready_for_review", "rejected", "failed"].includes(job.status) && !hasAutoCaption) {
        actions.push(`<button class="btn btn-sec" onclick="jobAction('${job.job_id}','auto_caption')">Add Auto-Caption &amp; Re-render</button>`);
      }
      if (job.status === "ready_for_review" || job.status === "rejected") {
        actions.push(`<button class="btn" onclick="jobAction('${job.job_id}','request_approval')">Request Approval</button>`);
      }
      if (job.status === "pending_approval") {
        actions.push(`<button class="btn btn-green" onclick="jobAction('${job.job_id}','approve')">Approve</button>`);
        actions.push(`<button class="btn btn-red" onclick="jobAction('${job.job_id}','reject')">Reject</button>`);
      }
      if (job.status === "approved") {
        actions.push(`<button class="btn btn-sec" onclick="jobAction('${job.job_id}','publish_dry')">Publish (Dry Run)</button>`);
        actions.push(`<button class="btn btn-green" onclick="jobAction('${job.job_id}','publish')">Publish Release</button>`);
      }

      document.getElementById("insp-body").innerHTML = `
        <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:12px;">
          <span class="badge b-${job.status}">${job.status.replaceAll("_", " ")}</span>
          <span class="mono">Profile: ${job.output_profile}</span>
          ${job.approval_id ? `<span class="mono">Approval: ${job.approval_id}</span>` : ""}
          ${actions.join("")}
        </div>
        ${job.error ? `<div style="color:var(--red);margin-bottom:10px;">Error: ${job.error}</div>` : ""}
        <div><strong>Artifacts (${(job.artifacts || []).length}):</strong></div>
        <ul>
          ${(job.artifacts || []).map(a => `<li class="mono">${a.kind}: <a href="/api/files?path=${encodeURIComponent(a.path)}" target="_blank" style="color:var(--accent)">${a.path}</a> (${(a.size_bytes/1024).toFixed(1)} KB)</li>`).join("")}
        </ul>
        ${videos.length ? `<div style="margin-top:12px;"><strong>Rendered Video Preview:</strong><div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;">${videos.map(v => `<div><div class="mono" style="margin-bottom:4px;color:var(--muted)">${v.kind} (${v.metadata?.width || ''}x${v.metadata?.height || ''})</div><video controls preload="metadata" style="max-width:340px;max-height:360px;border-radius:8px;border:1px solid var(--border);background:#000" src="/api/files?path=${encodeURIComponent(v.path)}"></video></div>`).join("")}</div></div>` : ""}
        ${thumbs.length ? `<div style="margin-top:12px;"><strong>Preview Thumbnails:</strong><div class="thumbs">${thumbs.map(t => `<img src="/api/files?path=${encodeURIComponent(t.path)}" alt="${t.kind}" />`).join("")}</div></div>` : ""}
      `;
    }

    async function jobAction(jobId, action) {
      let body = {};
      if (action === "approve") {
        const reviewer = prompt("Reviewer name:", "abhay");
        if (!reviewer) return;
        body = { reviewer, notes: "Approved via dashboard" };
      } else if (action === "reject") {
        const reviewer = prompt("Reviewer name:", "abhay");
        const reason = prompt("Rejection reason:", "Needs adjustment");
        if (!reviewer || !reason) return;
        body = { reviewer, reason };
      }
      const res = await fetch(`/api/jobs/${jobId}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(`Error: ${data.error || "Action failed"}`);
      } else {
        showToast(`Action '${action}' completed.`);
        await refreshAll();
      }
    }

    async function loadConfig() {
      const res = await fetch("/api/config");
      const cfg = await res.json();
      document.getElementById("cfg-path").textContent = cfg.config_file || "";
      document.getElementById("cfg-roots").value = (cfg.allowed_local_roots || []).join(", ");
      document.getElementById("cfg-release").value = cfg.release_dir || "";
      document.getElementById("cfg-webhook").value = cfg.webhook_url || "";
      document.getElementById("cfg-ffmpeg-timeout").value = cfg.ffmpeg_timeout_sec;
      document.getElementById("cfg-max-dl").value = cfg.max_download_mb;
      document.getElementById("cfg-dl-timeout").value = cfg.download_timeout_sec;
      document.getElementById("cfg-private-urls").checked = !!cfg.allow_private_urls;
    }

    async function saveConfig(e) {
      e.preventDefault();
      const payload = {
        allowed_local_roots: document.getElementById("cfg-roots").value.split(",").map(s => s.trim()).filter(Boolean),
        release_dir: document.getElementById("cfg-release").value.trim(),
        webhook_url: document.getElementById("cfg-webhook").value.trim() || null,
        ffmpeg_timeout_sec: Number(document.getElementById("cfg-ffmpeg-timeout").value),
        max_download_mb: Number(document.getElementById("cfg-max-dl").value),
        download_timeout_sec: Number(document.getElementById("cfg-dl-timeout").value),
        allow_private_urls: document.getElementById("cfg-private-urls").checked,
      };
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        showToast(`Config error: ${data.error}`);
      } else {
        showToast("Configuration saved & applied.");
      }
    }

    // Connect SSE for live updates + initial load
    function uploadSelectedVideo() {
      const input = document.getElementById("video-file");
      const file = input.files && input.files[0];
      if (!file) {
        showToast("Please select a video file first.");
        return;
      }
      uploadFile(file);
    }

    function uploadFile(file) {
      const btn = document.getElementById("upload-btn");
      const statusEl = document.getElementById("upload-status");
      const wrap = document.getElementById("upload-progress-wrap");
      const bar = document.getElementById("upload-progress-bar");
      btn.disabled = true;
      wrap.style.display = "block";
      bar.style.width = "0%";
      statusEl.textContent = `Uploading ${file.name}...`;

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload", true);
      xhr.setRequestHeader("X-Filename", encodeURIComponent(file.name));
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100);
          bar.style.width = pct + "%";
          statusEl.textContent = `Uploading ${file.name} (${pct}%)`;
        }
      };
      xhr.onload = async () => {
        btn.disabled = false;
        try {
          const data = JSON.parse(xhr.responseText || "{}");
          if (xhr.status >= 400) {
            statusEl.textContent = "Upload failed";
            showToast(`Upload error: ${data.error || xhr.status}`);
            return;
          }
          const src = data.source;
          statusEl.textContent = `${data.status}: ${src.source_id}`;
          showToast(`Uploaded ${src.filename} (${src.source_id})`);
          inputReset();

          await maybeCreateJob(src);
          await refreshAll();
        } catch (err) {
          statusEl.textContent = "Upload error";
          showToast(String(err));
        }
      };
      xhr.onerror = () => {
        btn.disabled = false;
        statusEl.textContent = "Network error";
        showToast("Upload failed due to network error.");
      };
      xhr.send(file);
    }

    async function maybeCreateJob(src) {
      if (!document.getElementById("upload-autorender").checked) return;
      const ytTitle = src.probe && src.probe.youtube && src.probe.youtube.title;
      const title = document.getElementById("upload-title").value.trim() || ytTitle || src.filename;
      const profile = document.getElementById("upload-profile").value;
      const ops = document.getElementById("upload-autocaption").checked ? [{ op: "auto_caption" }] : [];
      const jobRes = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          source_ids: [src.source_id],
          output_profile: profile,
          operations: ops,
          auto_render: true,
        }),
      });
      const jobData = await jobRes.json();
      if (jobRes.ok && jobData.job) {
        showToast(`Started rendering ${jobData.job.job_id}`);
      } else if (!jobRes.ok) {
        showToast(`Job error: ${jobData.error || jobRes.status}`);
      }
    }

    async function ingestUrl() {
      const urlInput = document.getElementById("ingest-url");
      const btn = document.getElementById("ingest-url-btn");
      const statusEl = document.getElementById("upload-status");
      const uri = urlInput.value.trim();
      if (!uri) {
        showToast("Please paste a YouTube or media URL first.");
        return;
      }
      btn.disabled = true;
      statusEl.textContent = "Ingesting URL...";
      try {
        const res = await fetch("/api/ingest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ uri }),
        });
        const data = await res.json();
        if (!res.ok) {
          statusEl.textContent = "Ingest failed";
          showToast(`Ingest error: ${data.error || res.status}`);
          return;
        }
        const src = data.source;
        statusEl.textContent = `${data.status}: ${src.source_id}`;
        showToast(`Ingested ${src.filename} (${src.source_id})`);
        urlInput.value = "";
        await maybeCreateJob(src);
        await refreshAll();
      } catch (err) {
        statusEl.textContent = "Ingest error";
        showToast(String(err));
      } finally {
        btn.disabled = false;
      }
    }

    function inputReset() {
      document.getElementById("video-file").value = "";
      document.getElementById("upload-title").value = "";
      setTimeout(() => {
        document.getElementById("upload-progress-wrap").style.display = "none";
      }, 1500);
    }

    const dropZone = document.getElementById("drop-zone");
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("dragover"); });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        uploadFile(e.dataTransfer.files[0]);
      }
    });

    refreshAll();
    const evtSource = new EventSource("/api/events");
    evtSource.onmessage = () => refreshAll();
    evtSource.onerror = () => {
      document.getElementById("conn-label").textContent = "POLLING";
    };
    setInterval(refreshAll, 3000);
  </script>
</body>
</html>
"""
