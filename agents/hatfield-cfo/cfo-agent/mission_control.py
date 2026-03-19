#!/usr/bin/env python3
"""
Mission Control — ClawBot Activity Dashboard

Usage:
  python3 mission_control.py
  Open http://localhost:8000
"""

import json
import time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from claude_agent_sdk import list_sessions, get_session_messages
import uvicorn

app = FastAPI()


def parse_session(s) -> dict:
    ts_ms = s.last_modified or 0
    return {
        "session_id": s.session_id,
        "cwd": s.cwd or "",
        "first_prompt": s.first_prompt or "",
        "summary": s.summary or "",
        "custom_title": s.custom_title or "",
        "git_branch": s.git_branch or "",
        "file_size": s.file_size or 0,
        "last_modified_ms": ts_ms,
    }


def parse_messages(raw_msgs) -> dict:
    messages = []
    total_input = 0
    total_output = 0
    tool_calls = 0

    for m in raw_msgs:
        msg = m.message
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", m.type)
        content = msg.get("content", "")
        usage = msg.get("usage", {})

        total_input += usage.get("input_tokens", 0)
        total_output += usage.get("output_tokens", 0)

        # Extract text content
        text = ""
        tools_used = []
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tools_used.append(block.get("name", "unknown"))
                        tool_calls += 1
                    elif block.get("type") == "tool_result":
                        pass  # skip tool results in display

        messages.append({
            "role": role,
            "text": text[:500],
            "tools": tools_used,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "stop_reason": msg.get("stop_reason", ""),
            "model": msg.get("model", ""),
        })

    cost = (total_input * 3 + total_output * 15) / 1_000_000

    return {
        "messages": messages,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "tool_calls": tool_calls,
        "estimated_cost_usd": round(cost, 4),
    }


@app.get("/api/sessions")
def api_sessions():
    try:
        sessions = list_sessions()
        return JSONResponse({"sessions": [parse_session(s) for s in sessions]})
    except Exception as e:
        return JSONResponse({"sessions": [], "error": str(e)})


@app.get("/api/sessions/{session_id}")
def api_session_detail(session_id: str):
    try:
        raw = get_session_messages(session_id)
        return JSONResponse(parse_messages(raw))
    except Exception as e:
        return JSONResponse({"messages": [], "error": str(e)})


@app.get("/api/stats")
def api_stats():
    try:
        sessions = list_sessions()
        total_size = sum(s.file_size or 0 for s in sessions)
        latest = max((s.last_modified or 0 for s in sessions), default=0)
        return JSONResponse({
            "total_sessions": len(sessions),
            "total_size_bytes": total_size,
            "latest_activity_ms": latest,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)})


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CLAWBOT MISSION CONTROL</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Black+Ops+One&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:        #08080a;
    --bg2:       #0f0f12;
    --bg3:       #161619;
    --amber:     #e8a020;
    --amber-dim: #8a5e12;
    --gold:      #f5d485;
    --text:      #c8a96e;
    --text-dim:  #6a5838;
    --green:     #45c084;
    --red:       #e05540;
    --border:    #2a2416;
    --border-hi: #3d3420;
    --font-mono: 'Share Tech Mono', monospace;
    --font-disp: 'Black Ops One', cursive;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 13px;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* Scanline overlay */
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
      0deg,
      transparent,
      transparent 2px,
      rgba(0,0,0,0.08) 2px,
      rgba(0,0,0,0.08) 4px
    );
    pointer-events: none;
    z-index: 9999;
  }

  /* ── HEADER ── */
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
    height: 52px;
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    position: relative;
  }

  header::before {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--amber-dim), transparent);
  }

  .logo {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .logo-icon {
    width: 28px;
    height: 28px;
    border: 2px solid var(--amber);
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
  }

  .logo-icon::before {
    content: '◈';
    color: var(--amber);
    font-size: 16px;
    animation: pulse-icon 2s ease-in-out infinite;
  }

  @keyframes pulse-icon {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  .logo-text {
    font-family: var(--font-disp);
    font-size: 18px;
    color: var(--amber);
    letter-spacing: 0.12em;
    text-shadow: 0 0 20px rgba(232,160,32,0.4);
  }

  .logo-sub {
    font-size: 10px;
    color: var(--text-dim);
    letter-spacing: 0.2em;
    margin-top: 1px;
  }

  .stats-bar {
    display: flex;
    gap: 24px;
    align-items: center;
  }

  .stat-chip {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
  }

  .stat-value {
    font-family: var(--font-disp);
    font-size: 16px;
    color: var(--gold);
  }

  .stat-label {
    font-size: 9px;
    color: var(--text-dim);
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }

  .stat-divider {
    width: 1px;
    height: 28px;
    background: var(--border);
  }

  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: blink 1.6s ease-in-out infinite;
  }

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.2; }
  }

  .refresh-btn {
    background: none;
    border: 1px solid var(--border-hi);
    color: var(--text-dim);
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 4px 12px;
    cursor: pointer;
    letter-spacing: 0.1em;
    transition: all 0.15s;
  }

  .refresh-btn:hover {
    border-color: var(--amber);
    color: var(--amber);
  }

  /* ── MAIN ── */
  main {
    display: grid;
    grid-template-columns: 340px 1fr;
    flex: 1;
    overflow: hidden;
  }

  /* ── SESSION LIST ── */
  .session-panel {
    background: var(--bg2);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .panel-header {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }

  .panel-title {
    font-family: var(--font-disp);
    font-size: 11px;
    color: var(--amber);
    letter-spacing: 0.2em;
  }

  .count-badge {
    font-size: 10px;
    color: var(--text-dim);
    background: var(--bg3);
    padding: 2px 8px;
    border: 1px solid var(--border);
  }

  .session-list {
    overflow-y: auto;
    flex: 1;
    scrollbar-width: thin;
    scrollbar-color: var(--border-hi) transparent;
  }

  .session-item {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.1s;
    position: relative;
  }

  .session-item:hover {
    background: var(--bg3);
  }

  .session-item.active {
    background: var(--bg3);
    border-left: 2px solid var(--amber);
    padding-left: 14px;
  }

  .session-item.active::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, rgba(232,160,32,0.04), transparent);
    pointer-events: none;
  }

  .session-prompt {
    color: var(--text);
    line-height: 1.45;
    margin-bottom: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 12px;
  }

  .session-meta {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }

  .session-id {
    color: var(--amber-dim);
    font-size: 10px;
    letter-spacing: 0.05em;
  }

  .session-time {
    color: var(--text-dim);
    font-size: 10px;
  }

  .session-cwd {
    color: var(--text-dim);
    font-size: 10px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 160px;
  }

  /* ── DETAIL PANEL ── */
  .detail-panel {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--bg);
  }

  .detail-header {
    padding: 16px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--bg2);
    flex-shrink: 0;
  }

  .detail-task {
    font-size: 14px;
    color: var(--gold);
    line-height: 1.5;
    margin-bottom: 12px;
    font-family: var(--font-mono);
  }

  .detail-chips {
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
  }

  .detail-chip {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .chip-label {
    font-size: 9px;
    letter-spacing: 0.2em;
    color: var(--text-dim);
    text-transform: uppercase;
  }

  .chip-value {
    font-size: 13px;
    color: var(--amber);
  }

  .chip-value.green { color: var(--green); }
  .chip-value.red   { color: var(--red); }

  .detail-body {
    flex: 1;
    overflow-y: auto;
    padding: 16px 24px;
    scrollbar-width: thin;
    scrollbar-color: var(--border-hi) transparent;
  }

  .section-label {
    font-size: 9px;
    letter-spacing: 0.25em;
    color: var(--amber-dim);
    text-transform: uppercase;
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .section-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  .message-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 24px;
  }

  .msg-row {
    display: grid;
    grid-template-columns: 80px 1fr 80px;
    gap: 12px;
    padding: 8px 12px;
    border: 1px solid transparent;
    transition: border-color 0.1s;
    align-items: start;
  }

  .msg-row:hover {
    border-color: var(--border);
    background: var(--bg2);
  }

  .msg-row.user   { border-left: 2px solid var(--text-dim); }
  .msg-row.assistant { border-left: 2px solid var(--amber); }

  .msg-role {
    font-size: 9px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding-top: 2px;
  }

  .msg-role.user      { color: var(--text-dim); }
  .msg-role.assistant { color: var(--amber); }

  .msg-text {
    color: var(--text);
    line-height: 1.55;
    font-size: 12px;
    word-break: break-word;
  }

  .msg-tools {
    display: flex;
    flex-direction: column;
    gap: 3px;
    align-items: flex-end;
  }

  .tool-tag {
    font-size: 9px;
    color: var(--text-dim);
    background: var(--bg3);
    border: 1px solid var(--border);
    padding: 1px 6px;
    white-space: nowrap;
  }

  .msg-tokens {
    font-size: 9px;
    color: var(--text-dim);
    text-align: right;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 16px;
    color: var(--text-dim);
  }

  .empty-icon {
    font-size: 40px;
    opacity: 0.3;
    color: var(--amber);
  }

  .empty-text {
    font-family: var(--font-disp);
    letter-spacing: 0.15em;
    font-size: 13px;
    color: var(--text-dim);
  }

  .loading {
    color: var(--amber-dim);
    font-size: 11px;
    padding: 24px;
    letter-spacing: 0.1em;
    animation: loading-pulse 1s ease-in-out infinite;
  }

  @keyframes loading-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  .cost-highlight { color: var(--gold); }
  .error-text { color: var(--red); font-size: 11px; }
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon"></div>
    <div>
      <div class="logo-text">CLAWBOT MISSION CONTROL</div>
      <div class="logo-sub">AGENT ACTIVITY MONITOR</div>
    </div>
  </div>
  <div class="stats-bar">
    <div class="status-dot" id="status-dot"></div>
    <div class="stat-chip">
      <div class="stat-value" id="stat-sessions">—</div>
      <div class="stat-label">Sessions</div>
    </div>
    <div class="stat-divider"></div>
    <div class="stat-chip">
      <div class="stat-value" id="stat-activity">—</div>
      <div class="stat-label">Last Active</div>
    </div>
    <div class="stat-divider"></div>
    <button class="refresh-btn" onclick="loadSessions()">↺ REFRESH</button>
  </div>
</header>

<main>
  <div class="session-panel">
    <div class="panel-header">
      <span class="panel-title">SESSIONS</span>
      <span class="count-badge" id="session-count">0</span>
    </div>
    <div class="session-list" id="session-list">
      <div class="loading">LOADING SESSIONS...</div>
    </div>
  </div>

  <div class="detail-panel" id="detail-panel">
    <div class="empty-state">
      <div class="empty-icon">◈</div>
      <div class="empty-text">SELECT A SESSION</div>
    </div>
  </div>
</main>

<script>
let sessions = [];
let activeId = null;

function timeAgo(ms) {
  const diff = Date.now() - ms;
  const s = Math.floor(diff / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return d + 'd ago';
  if (h > 0) return h + 'h ago';
  if (m > 0) return m + 'm ago';
  return 'just now';
}

function shortPath(p) {
  if (!p) return '';
  return p.replace('/Users/', '~/').replace('/home/', '~/');
}

function fmtTokens(n) {
  if (!n) return '0';
  return n >= 1000 ? (n/1000).toFixed(1) + 'k' : String(n);
}

async function loadSessions() {
  document.getElementById('status-dot').style.background = 'var(--amber)';
  try {
    const r = await fetch('/api/sessions');
    const data = await r.json();
    sessions = data.sessions || [];

    document.getElementById('session-count').textContent = sessions.length;
    document.getElementById('stat-sessions').textContent = sessions.length;

    if (sessions.length > 0) {
      const latest = sessions.reduce((a, b) => (a.last_modified_ms > b.last_modified_ms ? a : b));
      document.getElementById('stat-activity').textContent = timeAgo(latest.last_modified_ms);
    }

    renderSessionList();
    document.getElementById('status-dot').style.background = 'var(--green)';
  } catch(e) {
    document.getElementById('status-dot').style.background = 'var(--red)';
    document.getElementById('session-list').innerHTML =
      '<div class="error-text" style="padding:16px">ERROR LOADING SESSIONS</div>';
  }
}

function renderSessionList() {
  const el = document.getElementById('session-list');
  if (!sessions.length) {
    el.innerHTML = '<div class="loading">NO SESSIONS FOUND</div>';
    return;
  }

  const sorted = [...sessions].sort((a, b) => b.last_modified_ms - a.last_modified_ms);

  el.innerHTML = sorted.map(s => {
    const prompt = (s.first_prompt || s.summary || '(no prompt)').slice(0, 80);
    const active = s.session_id === activeId ? 'active' : '';
    const t = timeAgo(s.last_modified_ms);
    return `
      <div class="session-item ${active}" onclick="selectSession('${s.session_id}')">
        <div class="session-prompt">${escHtml(prompt)}</div>
        <div class="session-meta">
          <span class="session-id">${s.session_id.slice(0,8)}…</span>
          <span class="session-time">${t}</span>
          <span class="session-cwd">${shortPath(s.cwd)}</span>
        </div>
      </div>`;
  }).join('');
}

async function selectSession(id) {
  activeId = id;
  renderSessionList();

  const panel = document.getElementById('detail-panel');
  panel.innerHTML = '<div class="loading">LOADING SESSION DATA...</div>';

  const session = sessions.find(s => s.session_id === id);
  const prompt = session ? (session.first_prompt || session.summary || '') : '';

  try {
    const r = await fetch(`/api/sessions/${id}`);
    const data = await r.json();
    renderDetail(session, data, prompt);
  } catch(e) {
    panel.innerHTML = '<div class="error-text" style="padding:24px">ERROR LOADING SESSION</div>';
  }
}

function renderDetail(session, data, prompt) {
  const panel = document.getElementById('detail-panel');
  const msgs = data.messages || [];
  const cost = data.estimated_cost_usd || 0;
  const inputTok = data.total_input_tokens || 0;
  const outputTok = data.total_output_tokens || 0;
  const toolCalls = data.tool_calls || 0;

  const costColor = cost > 1 ? 'red' : cost > 0.1 ? 'chip-value' : 'green';

  const msgHtml = msgs.map(m => {
    if (!m.text && !m.tools?.length) return '';
    const roleClass = m.role === 'user' ? 'user' : 'assistant';
    const toolsHtml = (m.tools || []).map(t =>
      `<span class="tool-tag">${escHtml(t)}</span>`
    ).join('');
    const tokHtml = m.output_tokens
      ? `<div class="msg-tokens">${fmtTokens(m.output_tokens)} tok</div>` : '';
    return `
      <div class="msg-row ${roleClass}">
        <div class="msg-role ${roleClass}">${m.role}</div>
        <div>
          <div class="msg-text">${escHtml(m.text || '')}</div>
          ${toolsHtml ? `<div class="msg-tools" style="margin-top:4px;flex-direction:row;flex-wrap:wrap;gap:3px;">${toolsHtml}</div>` : ''}
        </div>
        ${tokHtml ? `<div>${tokHtml}</div>` : '<div></div>'}
      </div>`;
  }).filter(Boolean).join('');

  panel.innerHTML = `
    <div class="detail-header">
      <div class="detail-task">${escHtml(prompt.slice(0, 200) || '(no prompt)')}</div>
      <div class="detail-chips">
        <div class="detail-chip">
          <div class="chip-label">Session</div>
          <div class="chip-value">${session ? session.session_id.slice(0,12) + '…' : '—'}</div>
        </div>
        <div class="detail-chip">
          <div class="chip-label">Directory</div>
          <div class="chip-value">${escHtml(shortPath(session?.cwd || ''))}</div>
        </div>
        <div class="detail-chip">
          <div class="chip-label">Last Active</div>
          <div class="chip-value">${session ? timeAgo(session.last_modified_ms) : '—'}</div>
        </div>
        <div class="detail-chip">
          <div class="chip-label">Input Tokens</div>
          <div class="chip-value">${fmtTokens(inputTok)}</div>
        </div>
        <div class="detail-chip">
          <div class="chip-label">Output Tokens</div>
          <div class="chip-value">${fmtTokens(outputTok)}</div>
        </div>
        <div class="detail-chip">
          <div class="chip-label">Tool Calls</div>
          <div class="chip-value">${toolCalls}</div>
        </div>
        <div class="detail-chip">
          <div class="chip-label">Est. Cost</div>
          <div class="chip-value ${costColor}">$${cost.toFixed(4)}</div>
        </div>
      </div>
    </div>
    <div class="detail-body">
      <div class="section-label">Message Log</div>
      <div class="message-list">${msgHtml || '<div class="loading">NO MESSAGES</div>'}</div>
    </div>`;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

// Load on start, auto-refresh every 30s
loadSessions();
setInterval(loadSessions, 30000);
</script>
</body>
</html>"""


@app.get("/")
def index():
    return HTMLResponse(DASHBOARD_HTML)


if __name__ == "__main__":
    print("\nClawBot Mission Control")
    print("─" * 40)
    print("Open → http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
