"""Self-contained 3D glassmorphic HTML/CSS/JS dashboard UI with live SVG graphics."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Video Automation MCP — 3D Studio Dashboard</title>
  <style>
    :root {
      --bg: #050811;
      --bg-2: #0a1020;
      --panel: rgba(15, 23, 42, 0.72);
      --panel-2: rgba(23, 34, 59, 0.78);
      --border: rgba(148, 163, 184, 0.16);
      --border-glow: rgba(99, 102, 241, 0.45);
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #3b82f6;
      --cyan: #06b6d4;
      --purple: #a855f7;
      --green: #22c55e;
      --amber: #f59e0b;
      --red: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: radial-gradient(circle at 15% 15%, #131c3a 0%, var(--bg) 55%),
                  radial-gradient(circle at 85% 80%, #1b1035 0%, var(--bg) 50%);
      color: var(--text);
      line-height: 1.45;
      min-height: 100vh;
      overflow-x: hidden;
      position: relative;
    }

    /* 3D Perspective Grid & Ambient Orbs */
    .bg-3d-grid {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 0;
      background-image:
        linear-gradient(to right, rgba(59, 130, 246, 0.06) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(59, 130, 246, 0.06) 1px, transparent 1px);
      background-size: 48px 48px;
      transform: perspective(600px) rotateX(45deg) scale(1.6) translateY(-10%);
      transform-origin: center top;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,0.45), transparent 80%);
    }
    .orb {
      position: fixed;
      border-radius: 50%;
      filter: blur(80px);
      opacity: 0.28;
      pointer-events: none;
      z-index: 0;
      animation: floatOrb 12s ease-in-out infinite alternate;
    }
    .orb-1 { width: 380px; height: 380px; background: #3b82f6; top: -120px; left: -80px; }
    .orb-2 { width: 420px; height: 420px; background: #a855f7; bottom: -140px; right: -80px; animation-delay: -5s; }
    .orb-3 { width: 260px; height: 260px; background: #06b6d4; top: 40%; left: 55%; animation-delay: -9s; }
    @keyframes floatOrb {
      0% { transform: translate(0, 0) scale(1); }
      100% { transform: translate(30px, -25px) scale(1.12); }
    }

    header {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 14px 28px;
      background: rgba(8, 13, 28, 0.82);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
    }
    .brand { display: flex; align-items: center; gap: 14px; font-weight: 800; font-size: 18px; letter-spacing: -0.02em; }
    .brand-title {
      background: linear-gradient(135deg, #ffffff 0%, #93c5fd 55%, #c084fc 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .live-pill {
      display: inline-flex; align-items: center; gap: 7px;
      padding: 4px 12px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
      background: rgba(34, 197, 94, 0.14); color: var(--green);
      border: 1px solid rgba(34, 197, 94, 0.4);
      box-shadow: 0 0 16px rgba(34, 197, 94, 0.25);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); animation: pulse 1.6s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.35; transform: scale(0.8); } }

    nav { display: flex; gap: 8px; }
    .tab-btn {
      background: rgba(255, 255, 255, 0.03);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 8px 16px;
      border-radius: 10px;
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
      transition: all 0.2s ease;
    }
    .tab-btn:hover { color: var(--text); border-color: var(--border-glow); transform: translateY(-1px); }
    .tab-btn.active {
      background: linear-gradient(135deg, rgba(59, 130, 246, 0.28), rgba(168, 85, 247, 0.24));
      color: #fff;
      border-color: rgba(96, 165, 250, 0.55);
      box-shadow: 0 6px 20px rgba(59, 130, 246, 0.25);
    }

    main {
      position: relative;
      z-index: 1;
      max-width: 1380px;
      margin: 0 auto;
      padding: 22px 26px 56px;
    }

    /* 3D Hero Studio Banner */
    .hero-3d {
      display: grid;
      grid-template-columns: 1.35fr 1fr;
      gap: 18px;
      margin-bottom: 20px;
      padding: 20px 24px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(20, 32, 64, 0.86), rgba(15, 23, 42, 0.78));
      border: 1px solid rgba(148, 163, 184, 0.22);
      box-shadow:
        0 20px 45px rgba(0, 0, 0, 0.5),
        inset 0 1px 0 rgba(255, 255, 255, 0.14);
      backdrop-filter: blur(18px);
      align-items: center;
    }
    @media (max-width: 960px) { .hero-3d { grid-template-columns: 1fr; } }
    .hero-title { font-size: 21px; font-weight: 800; margin: 0 0 6px; letter-spacing: -0.02em; }
    .hero-sub { font-size: 13px; color: var(--muted); margin: 0 0 14px; }
    .pipeline-flow {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .flow-node {
      padding: 6px 11px;
      border-radius: 10px;
      font-size: 11px;
      font-weight: 700;
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid var(--border);
      color: var(--muted);
      box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3);
      transition: all 0.25s ease;
    }
    .flow-node.active {
      color: #fff;
      border-color: rgba(56, 189, 248, 0.75);
      background: linear-gradient(135deg, rgba(59, 130, 246, 0.35), rgba(6, 182, 212, 0.28));
      box-shadow: 0 0 18px rgba(56, 189, 248, 0.35);
      transform: translateY(-2px);
    }
    .flow-arrow { color: rgba(148, 163, 184, 0.45); font-size: 12px; }

    .hero-graphics {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 18px;
    }
    .donut-wrap {
      display: flex;
      align-items: center;
      gap: 14px;
      padding: 10px 14px;
      border-radius: 14px;
      background: rgba(8, 13, 28, 0.65);
      border: 1px solid var(--border);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
    }
    .donut-legend { font-size: 11px; color: var(--muted); display: flex; flex-direction: column; gap: 3px; }
    .leg-row { display: flex; align-items: center; gap: 6px; }
    .leg-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }

    /* 3D KPI Cards */
    .kpis {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
      gap: 14px;
      margin-bottom: 20px;
      perspective: 1100px;
    }
    .kpi {
      background: linear-gradient(160deg, rgba(30, 41, 70, 0.75), rgba(13, 20, 38, 0.85));
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 15px 18px;
      box-shadow:
        0 14px 28px rgba(0, 0, 0, 0.38),
        inset 0 1px 0 rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(14px);
      transform-style: preserve-3d;
      transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
    }
    .kpi:hover {
      transform: translateY(-4px) rotateX(4deg) rotateY(-3deg);
      border-color: rgba(96, 165, 250, 0.55);
      box-shadow: 0 22px 38px rgba(15, 23, 42, 0.65), 0 0 24px rgba(59, 130, 246, 0.2);
    }
    .kpi-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 700; }
    .kpi-val {
      font-size: 28px; font-weight: 800; margin-top: 6px;
      background: linear-gradient(180deg, #ffffff 0%, #cbd5e1 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }

    .grid-2 { display: grid; grid-template-columns: 1.55fr 1fr; gap: 18px; }
    @media (max-width: 980px) { .grid-2 { grid-template-columns: 1fr; } }

    /* 3D Glass Cards */
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      backdrop-filter: blur(16px);
      box-shadow:
        0 18px 40px rgba(0, 0, 0, 0.45),
        inset 0 1px 0 rgba(255, 255, 255, 0.1);
    }
    .card-head {
      display: flex; justify-content: space-between; align-items: center;
      padding: 13px 18px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.02);
      font-weight: 700; font-size: 14px;
    }
    .card-body { padding: 16px 18px; }

    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { text-align: left; padding: 11px 8px; border-bottom: 1px solid rgba(148, 163, 184, 0.1); }
    th { color: var(--muted); font-weight: 700; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
    tr.clickable { transition: background 0.15s ease; }
    tr.clickable:hover { background: rgba(59, 130, 246, 0.1); cursor: pointer; }

    .badge {
      display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 10px; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.05em;
    }
    .b-draft { background: rgba(148,163,184,0.18); color: var(--muted); }
    .b-rendering { background: rgba(59,130,246,0.22); color: #60a5fa; box-shadow: 0 0 12px rgba(59,130,246,0.25); }
    .b-ready_for_review { background: rgba(168,85,247,0.22); color: #c084fc; }
    .b-pending_approval { background: rgba(245,158,11,0.22); color: #fbbf24; }
    .b-approved, .b-published { background: rgba(34,197,94,0.22); color: #4ade80; }
    .b-rejected, .b-failed { background: rgba(239,68,68,0.22); color: #f87171; }

    .activity-list { max-height: 500px; overflow-y: auto; display: flex; flex-direction: column; gap: 9px; }
    .act-item {
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px 13px;
      font-size: 13px;
      box-shadow: 0 6px 14px rgba(0, 0, 0, 0.25);
    }
    .act-meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); margin-bottom: 3px; }

    /* Tactile 3D Buttons */
    .btn {
      background: linear-gradient(180deg, #4f8cff 0%, #2563eb 100%);
      color: #fff;
      border: 1px solid rgba(147, 197, 253, 0.35);
      border-radius: 10px;
      padding: 8px 14px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 4px 0 #1d4ed8, 0 8px 16px rgba(37, 99, 235, 0.35);
      transition: transform 0.1s ease, box-shadow 0.1s ease, filter 0.15s ease;
    }
    .btn:hover { filter: brightness(1.08); }
    .btn:active { transform: translateY(2px); box-shadow: 0 2px 0 #1d4ed8, 0 4px 8px rgba(37, 99, 235, 0.25); }
    .btn-sec {
      background: linear-gradient(180deg, #24324d 0%, #172136 100%);
      border-color: var(--border);
      color: var(--text);
      box-shadow: 0 4px 0 #0c1322, 0 6px 14px rgba(0, 0, 0, 0.35);
    }
    .btn-sec:active { box-shadow: 0 2px 0 #0c1322; }
    .btn-green {
      background: linear-gradient(180deg, #22c55e 0%, #16a34a 100%);
      border-color: rgba(134, 239, 172, 0.35);
      box-shadow: 0 4px 0 #15803d, 0 8px 16px rgba(22, 163, 74, 0.35);
    }
    .btn-red {
      background: linear-gradient(180deg, #ef4444 0%, #dc2626 100%);
      border-color: rgba(252, 165, 165, 0.35);
      box-shadow: 0 4px 0 #991b1b, 0 8px 16px rgba(220, 38, 38, 0.35);
    }
    .btn:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }

    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 760px) { .form-grid { grid-template-columns: 1fr; } }
    label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; font-weight: 600; }
    input[type="text"], input[type="number"], textarea, select {
      background: rgba(8, 13, 28, 0.72);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 9px 11px;
      font-size: 13px;
      outline: none;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    input[type="text"]:focus, input[type="number"]:focus, select:focus {
      border-color: rgba(96, 165, 250, 0.7);
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.18);
    }
    input[type="text"], input[type="number"], textarea { width: 100%; }
    .hidden { display: none; }
    .thumbs { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; }
    .thumbs img {
      max-width: 210px; border-radius: 10px; border: 1px solid var(--border);
      box-shadow: 0 10px 22px rgba(0, 0, 0, 0.45);
    }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
    .toast {
      position: fixed; bottom: 22px; right: 22px;
      background: rgba(15, 23, 42, 0.94);
      backdrop-filter: blur(14px);
      border: 1px solid var(--accent);
      color: var(--text);
      padding: 11px 18px;
      border-radius: 12px;
      font-size: 13px;
      z-index: 50;
      display: none;
      box-shadow: 0 14px 30px rgba(0, 0, 0, 0.55);
    }
    .upload-box {
      display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
      padding: 16px; border: 1.5px dashed rgba(96, 165, 250, 0.35); border-radius: 14px;
      background: rgba(8, 13, 28, 0.52);
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    .upload-box.dragover {
      border-color: var(--cyan);
      box-shadow: 0 0 24px rgba(6, 182, 212, 0.22);
    }
    .progress-wrap { width: 100%; height: 7px; background: rgba(15,23,42,0.9); border-radius: 999px; overflow: hidden; display: none; }
    .progress-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #3b82f6, #06b6d4, #a855f7); transition: width 0.15s; }
  </style>
</head>
<body>
  <div class="bg-3d-grid"></div>
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>

  <header>
    <div class="brand">
      <!-- 3D Isometric Studio Cube SVG Icon -->
      <svg width="32" height="32" viewBox="0 0 36 36" fill="none" aria-hidden="true">
        <defs>
          <linearGradient id="cubeTop" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#60a5fa" />
            <stop offset="100%" stop-color="#a855f7" />
          </linearGradient>
          <linearGradient id="cubeLeft" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#2563eb" />
            <stop offset="100%" stop-color="#1e1b4b" />
          </linearGradient>
          <linearGradient id="cubeRight" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#06b6d4" />
            <stop offset="100%" stop-color="#0f172a" />
          </linearGradient>
        </defs>
        <polygon points="18,3 32,10.5 18,18 4,10.5" fill="url(#cubeTop)" />
        <polygon points="4,10.5 18,18 18,33 4,25.5" fill="url(#cubeLeft)" />
        <polygon points="32,10.5 18,18 18,33 32,25.5" fill="url(#cubeRight)" />
        <polygon points="15,13 23,17.5 15,22" fill="#ffffff" opacity="0.92" />
      </svg>
      <span class="brand-title">Video Automation MCP</span>
      <span class="live-pill"><span class="dot"></span><span id="conn-label">LIVE</span></span>
    </div>
    <nav>
      <button class="tab-btn active" onclick="switchTab('live', this)">Live Studio</button>
      <button class="tab-btn" onclick="switchTab('config', this)">Configuration</button>
      <button class="tab-btn" onclick="refreshAll()">Refresh</button>
    </nav>
  </header>

  <main>
    <section id="tab-live">
      <!-- 3D Studio Hero & Live Graphics -->
      <div class="hero-3d">
        <div>
          <h1 class="hero-title">3D AI Video Pipeline Studio</h1>
          <p class="hero-sub">Mixed-source ingest, Whisper transcription, OmniVoice AI dubbing, dual 16:9 + 9:16 rendering, and SHA-256 approval gating.</p>
          <div class="pipeline-flow" id="pipeline-flow">
            <span class="flow-node" data-stage="ingest">1. Ingest</span>
            <span class="flow-arrow">→</span>
            <span class="flow-node" data-stage="transcribe">2. Transcribe</span>
            <span class="flow-arrow">→</span>
            <span class="flow-node" data-stage="voice">3. AI Voice</span>
            <span class="flow-arrow">→</span>
            <span class="flow-node" data-stage="render">4. 16:9 + 9:16</span>
            <span class="flow-arrow">→</span>
            <span class="flow-node" data-stage="approve">5. Approve &amp; Publish</span>
          </div>
        </div>
        <div class="hero-graphics">
          <!-- Isometric Dual-Format Graphic -->
          <svg width="110" height="84" viewBox="0 0 110 84" fill="none" aria-hidden="true">
            <defs>
              <linearGradient id="scr16" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.85" />
                <stop offset="100%" stop-color="#1e293b" stop-opacity="0.95" />
              </linearGradient>
              <linearGradient id="scr9" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#a855f7" stop-opacity="0.9" />
                <stop offset="100%" stop-color="#06b6d4" stop-opacity="0.85" />
              </linearGradient>
            </defs>
            <rect x="6" y="14" width="66" height="42" rx="6" fill="url(#scr16)" stroke="#60a5fa" stroke-width="1.5" />
            <polygon points="34,27 46,35 34,43" fill="#fff" opacity="0.9" />
            <text x="12" y="50" fill="#93c5fd" font-size="8" font-family="monospace">16:9</text>
            <rect x="64" y="6" width="36" height="64" rx="7" fill="url(#scr9)" stroke="#e879f9" stroke-width="1.5" />
            <polygon points="78,31 89,38 78,45" fill="#fff" opacity="0.95" />
            <text x="71" y="62" fill="#f5d0fe" font-size="8" font-family="monospace">9:16</text>
          </svg>
          <!-- Live Status Donut Chart -->
          <div class="donut-wrap">
            <svg width="74" height="74" viewBox="0 0 74 74" id="status-donut">
              <circle cx="37" cy="37" r="28" stroke="rgba(148,163,184,0.16)" stroke-width="8" fill="none" />
              <g id="donut-segments" transform="rotate(-90 37 37)"></g>
              <text x="37" y="41" text-anchor="middle" fill="#f8fafc" font-size="14" font-weight="800" id="donut-total">0</text>
            </svg>
            <div class="donut-legend">
              <div class="leg-row"><span class="leg-dot" style="background:var(--green)"></span><span>Done / Pub</span></div>
              <div class="leg-row"><span class="leg-dot" style="background:var(--accent)"></span><span>Rendering</span></div>
              <div class="leg-row"><span class="leg-dot" style="background:var(--amber)"></span><span>Review</span></div>
              <div class="leg-row"><span class="leg-dot" style="background:var(--red)"></span><span>Failed</span></div>
            </div>
          </div>
        </div>
      </div>

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
            <label style="display:inline-flex;align-items:center;gap:6px;margin:0;cursor:pointer;">
              <input type="checkbox" id="upload-voiceclone" />
              <span>AI Voice Clone</span>
            </label>
            <button class="btn" id="upload-btn" onclick="uploadSelectedVideo()">Upload File</button>
            <div style="width:100%;display:flex;gap:10px;align-items:center;margin-top:4px;">
              <input type="text" id="ingest-url" placeholder="Paste YouTube URL (youtube.com / youtu.be / shorts) or HTTP/S3 URL..." style="flex:1;" />
              <button class="btn btn-sec" id="ingest-url-btn" onclick="ingestUrl()">Ingest YouTube / URL</button>
            </div>
            <div style="width:100%;display:flex;gap:10px;align-items:center;">
              <input type="text" id="voice-script-input" placeholder="Optional AI Voice Script (leave blank to auto-transcribe &amp; re-voice spoken audio)" style="flex:1;" />
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
          <div class="card-body" style="padding: 0 14px 14px; overflow-x: auto;">
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
    let hasActiveRender = false;

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
      renderStatusDonut(data.summary);
      renderJobs(data.jobs);
      renderPipelineFlow(data.jobs);
      renderActivity(data.activity);
      renderSourceSelect(data.sources || []);
      if (selectedJobId) {
        const job = data.jobs.find(j => j.job_id === selectedJobId);
        if (job) renderInspector(job);
      }
    }

    function renderStatusDonut(s) {
      const total = s.total_jobs || 0;
      document.getElementById("donut-total").textContent = total;
      const group = document.getElementById("donut-segments");
      if (!total) {
        group.innerHTML = "";
        return;
      }
      const slices = [
        { val: (s.published || 0) + (s.approved || 0), color: "#22c55e" },
        { val: s.rendering || 0, color: "#3b82f6" },
        { val: (s.ready_for_review || 0) + (s.pending_approval || 0) + (s.draft || 0), color: "#f59e0b" },
        { val: (s.failed || 0) + (s.rejected || 0), color: "#ef4444" },
      ];
      const circ = 2 * Math.PI * 28;
      let offset = 0;
      group.innerHTML = slices.filter(sl => sl.val > 0).map(sl => {
        const len = (sl.val / total) * circ;
        const el = `<circle cx="37" cy="37" r="28" fill="none" stroke="${sl.color}" stroke-width="8" stroke-dasharray="${len} ${circ - len}" stroke-dashoffset="${-offset}" stroke-linecap="round" />`;
        offset += len;
        return el;
      }).join("");
    }

    function renderPipelineFlow(jobs) {
      const active = jobs.find(j => j.status === "rendering");
      const nodes = document.querySelectorAll("#pipeline-flow .flow-node");
      nodes.forEach(n => n.classList.remove("active"));
      if (!active) return;
      const st = (active.progress_stage || "").toLowerCase();
      let target = "render";
      if (st.includes("prepar")) target = "ingest";
      else if (st.includes("transcrib") || st.includes("caption")) target = "transcribe";
      else if (st.includes("voice")) target = "voice";
      else if (st.includes("export")) target = "render";
      nodes.forEach(n => { if (n.dataset.stage === target) n.classList.add("active"); });
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
              <div class="mono" style="color:var(--cyan)">[${m.start_sec}s → ${m.end_sec}s] (score: ${m.score})</div>
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
      const voiceChecked = document.getElementById("upload-voiceclone").checked;
      const scriptText = document.getElementById("voice-script-input").value.trim() || null;
      const ops = [{ op: "trim", start_sec: startSec, end_sec: endSec }];
      if (voiceChecked) ops.push({ op: "voice_clone", script_text: scriptText });
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

    function fmtDur(sec) {
      if (sec === null || sec === undefined || isNaN(sec)) return "";
      const s = Math.max(0, Math.round(sec));
      const m = Math.floor(s / 60);
      const r = s % 60;
      return m > 0 ? `${m}m ${r}s` : `${r}s`;
    }

    function computeEtaText(j) {
      const pct = j.progress_pct || 0;
      const started = j.render_started_at ? Date.parse(j.render_started_at) : null;
      const elapsedSec = started ? Math.max(0, (Date.now() - started) / 1000) : null;
      let etaSec = j.eta_sec;
      if ((etaSec === null || etaSec === undefined) && elapsedSec !== null && pct >= 2 && pct < 100) {
        etaSec = elapsedSec * (100 - pct) / pct;
      }
      const parts = [];
      if (elapsedSec !== null) parts.push(`elapsed ${fmtDur(elapsedSec)}`);
      if (etaSec !== null && etaSec !== undefined && pct >= 2) {
        parts.push(`ETA ~${fmtDur(etaSec)}`);
      } else {
        parts.push("estimating ETA...");
      }
      return parts.join(" · ");
    }

    function renderJobs(jobs) {
      document.getElementById("jobs-count").textContent = `${jobs.length} jobs`;
      const tbody = document.getElementById("jobs-tbody");
      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--muted);">No jobs yet. Use MCP tools or ingest above to create a job.</td></tr>`;
        return;
      }
      tbody.innerHTML = jobs.map(j => {
        const pct = Math.round(j.progress_pct || 0);
        const isRendering = j.status === "rendering";
        const progressHtml = isRendering
          ? `<div style="margin-top:6px;min-width:165px;"><div style="height:6px;background:rgba(15,23,42,0.9);border-radius:999px;overflow:hidden;"><div style="height:100%;width:${pct}%;background:linear-gradient(90deg,#3b82f6,#06b6d4);transition:width 0.25s;"></div></div><div class="mono" style="font-size:11px;color:#60a5fa;margin-top:3px;">${pct}% · ${j.progress_stage || "Rendering"}</div><div class="mono" style="font-size:10px;color:var(--muted);">${computeEtaText(j)}</div></div>`
          : (pct > 0 ? `<div class="mono" style="font-size:11px;color:var(--muted);margin-top:2px;">${pct}%</div>` : "");
        return `
        <tr class="clickable" onclick="selectJob('${j.job_id}')">
          <td><strong>${j.title}</strong><div class="mono" style="color:var(--muted)">${j.job_id}</div></td>
          <td class="mono">${j.output_profile}</td>
          <td><span class="badge b-${j.status}">${j.status.replaceAll("_", " ")}</span>${progressHtml}</td>
          <td>${(j.operations || []).length}</td>
          <td class="mono">${fmtTime(j.updated_at)}</td>
        </tr>`;
      }).join("");
      hasActiveRender = jobs.some(j => j.status === "rendering");
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
      const sig = `${job.job_id}:${job.status}:${job.progress_pct}:${job.progress_stage}:${job.updated_at}:${(job.artifacts || []).length}`;
      if (sig === lastInspectedSig) return;
      lastInspectedSig = sig;
      const card = document.getElementById("inspector-card");
      card.style.display = "block";
      document.getElementById("insp-title").textContent = `Job Inspector — ${job.title} (${job.job_id})`;

      const videos = (job.artifacts || []).filter(a => a.kind.startsWith("video_"));
      const thumbs = (job.artifacts || []).filter(a => a.kind === "thumbnail");
      const actions = [];
      const hasAutoCaption = (job.operations || []).some(op => op.op === "auto_caption");
      const hasVoiceClone = (job.operations || []).some(op => op.op === "voice_clone");
      if (["draft", "ready_for_review", "rejected", "failed"].includes(job.status) && !hasAutoCaption) {
        actions.push(`<button class="btn btn-sec" onclick="jobAction('${job.job_id}','auto_caption')">Add Auto-Caption &amp; Re-render</button>`);
      }
      if (["draft", "ready_for_review", "rejected", "failed"].includes(job.status) && !hasVoiceClone) {
        actions.push(`<button class="btn btn-sec" onclick="jobAction('${job.job_id}','voice_clone')">Replace with AI Voice &amp; Re-render</button>`);
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
        ${job.status === "rendering" ? `<div style="margin-bottom:12px;"><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;"><span>${job.progress_stage || "Rendering"} (${computeEtaText(job)})</span><span class="mono">${Math.round(job.progress_pct || 0)}%</span></div><div style="height:8px;background:rgba(15,23,42,0.9);border-radius:999px;overflow:hidden;"><div style="height:100%;width:${Math.round(job.progress_pct || 0)}%;background:linear-gradient(90deg,#3b82f6,#06b6d4,#a855f7);transition:width 0.25s;"></div></div></div>` : ""}
        ${job.error ? `<div style="color:var(--red);margin-bottom:10px;">Error: ${job.error}</div>` : ""}
        <div><strong>Artifacts (${(job.artifacts || []).length}):</strong></div>
        <ul>
          ${(job.artifacts || []).map(a => `<li class="mono">${a.kind}: <a href="/api/files?path=${encodeURIComponent(a.path)}" target="_blank" style="color:#60a5fa">${a.path}</a> (${(a.size_bytes/1024).toFixed(1)} KB)</li>`).join("")}
        </ul>
        ${videos.length ? `<div style="margin-top:12px;"><strong>Rendered Video Preview:</strong><div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;">${videos.map(v => `<div><div class="mono" style="margin-bottom:4px;color:var(--muted)">${v.kind} (${v.metadata?.width || ''}x${v.metadata?.height || ''})</div><video controls preload="metadata" style="max-width:340px;max-height:360px;border-radius:10px;border:1px solid var(--border);background:#000;box-shadow:0 12px 26px rgba(0,0,0,0.5)" src="/api/files?path=${encodeURIComponent(v.path)}"></video></div>`).join("")}</div></div>` : ""}
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
      } else if (action === "voice_clone") {
        const script = prompt("Optional custom AI voice script (leave blank to auto-transcribe spoken dialogue):", "");
        if (script === null) return;
        body = { script_text: script.trim() || null };
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
      const ops = [];
      const scriptText = document.getElementById("voice-script-input").value.trim() || null;
      if (document.getElementById("upload-voiceclone").checked) ops.push({ op: "voice_clone", script_text: scriptText });
      if (document.getElementById("upload-autocaption").checked) ops.push({ op: "auto_caption" });
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
    setInterval(() => {
      if (hasActiveRender) refreshAll();
    }, 1000);
    setInterval(refreshAll, 3000);
  </script>
</body>
</html>
"""
