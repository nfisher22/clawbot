#!/usr/bin/env node

require("dotenv").config({ path: "/root/.env" });
const https = require("https");
const http = require("http");
const url = require("url");
const { exec } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { MongoClient } = require("mongodb");
let db;
MongoClient.connect(process.env.MONGO_URI, { family: 4 })
  .then(client => {
    db = client.db("mrsoul");
    console.log("[Logger] MongoDB connected");
  })
  .catch(err => console.error("[Logger] MongoDB connection failed:", err.message));
const { getAgent, routeAgent, listAgents } = require("./agents/index");

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY || "";
const ANTHROPIC_API_KEY  = process.env.ANTHROPIC_API_KEY  || "";

// Model routing
const MODELS = {
  SONNET:  "anthropic/claude-sonnet-4.6",
  HAIKU:   "anthropic/claude-haiku-4.5",
  MINIMAX: "minimax/minimax-m2.5",
};
const SIMPLE_KEYWORDS = ["summarize","format","reformat","convert","translate","list","bullet","short answer","yes or no","quick","simple"];
const PORT = 3000;
const PASSWORD = process.env.CLAWBOT_PASSWORD || "Dead1969!";
const INTERNAL_KEY = process.env.INTERNAL_KEY || "";

// ─── STATE ────────────────────────────────────────────────────────────────────
let tasks = [];
let chatHistory = [];
let conversationHistory = [];

// ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────
const SYSTEM_PROMPT = `You are ClawBot, a smart personal AI assistant for Nate Fisher, CEO of Peak 10 Group. You help with:
- Writing, reviewing, and debugging code (JavaScript, Python, Node.js, bash, etc.)
- Building and explaining scripts, APIs, and automation workflows
- Summarizing emails and meeting notes
- Researching topics on the web
- Managing a to-do list
- Drafting professional emails and messages
- Real estate operations, finance, and business tasks for Peak 10 Group
Always be concise, professional, and direct. Never say you cannot write or help with code.`;

// ─── MODEL ROUTER ─────────────────────────────────────────────────────────────
function routeModel(messages) {
  const last = messages.filter(m => m.role === "user").pop();
  const prompt = (last ? last.content : "").toLowerCase();
  const isCoding = /\b(code|function|script|debug|refactor|implement|class|module|node|python|javascript|typescript|api|endpoint|bug|error|fix)\b/i.test(prompt);
  if (isCoding) return MODELS.MINIMAX;
  const isSimple = SIMPLE_KEYWORDS.some(k => prompt.includes(k));
  if (isSimple || prompt.length < 300) return MODELS.HAIKU;
  return MODELS.SONNET;
}

function askModel(messages) {
  const model = routeModel(messages);
  console.log(`[Router] → ${model}`);
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ model, messages, max_tokens: 1000 });
    const req = https.request({
      hostname: "openrouter.ai",
      path: "/api/v1/chat/completions",
      method: "POST",
      family: 4,
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${OPENROUTER_API_KEY}`,
        "HTTP-Referer": "https://clawbot.peak10group.com",
        "Content-Length": Buffer.byteLength(body),
      },
    }, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          if (parsed.error) return reject(parsed.error.message || JSON.stringify(parsed.error));
          resolve(parsed.choices[0].message.content);
        } catch (e) { reject("Failed to parse response"); }
      });
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

function executeCode(language, code) {
  return new Promise((resolve) => {
    const ext = language === "python" ? "py" : "js";
    const tmpFile = path.join(os.tmpdir(), `clawbot_exec_${Date.now()}.${ext}`);
    fs.writeFileSync(tmpFile, code);
    const cmd = language === "python" ? `python3 ${tmpFile}` : `node ${tmpFile}`;
    exec(cmd, { timeout: 10000 }, (error, stdout, stderr) => {
      fs.unlinkSync(tmpFile);
      if (error) return resolve(`Error:\n${stderr || error.message}`);
      resolve(stdout || "Code ran successfully with no output.");
    });
  });
}

// ─── HTML DASHBOARD ───────────────────────────────────────────────────────────
const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ClawBot</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #111118;
    --surface2: #1a1a24;
    --border: #2a2a3a;
    --accent: #7c6aff;
    --accent2: #ff6a9e;
    --text: #e8e8f0;
    --muted: #6b6b80;
    --success: #4fffb0;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'JetBrains Mono', monospace;
    height: 100vh;
    overflow: hidden;
    display: grid;
    grid-template-columns: 280px 1fr 280px;
    grid-template-rows: 60px 1fr;
  }

  /* HEADER */
  header {
    grid-column: 1 / -1;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 24px;
    gap: 12px;
  }
  .logo {
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 20px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.5px;
  }
  .status-dot {
    width: 8px; height: 8px;
    background: var(--success);
    border-radius: 50%;
    box-shadow: 0 0 8px var(--success);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .status-text { color: var(--muted); font-size: 12px; }
  .header-right { margin-left: auto; display: flex; gap: 16px; align-items: center; }
  .clear-btn {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 6px 14px;
    border-radius: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .clear-btn:hover { border-color: var(--accent); color: var(--accent); }

  /* SIDEBAR LEFT - Tasks */
  .sidebar-left {
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .sidebar-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    font-family: 'Syne', sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    color: var(--muted);
    text-transform: uppercase;
  }
  .task-input-wrap {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 8px;
  }
  .task-input {
    flex: 1;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 8px 10px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    outline: none;
    transition: border-color 0.2s;
  }
  .task-input:focus { border-color: var(--accent); }
  .add-btn {
    background: var(--accent);
    border: none;
    color: white;
    padding: 8px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    transition: opacity 0.2s;
  }
  .add-btn:hover { opacity: 0.8; }
  .tasks-list { flex: 1; overflow-y: auto; padding: 8px; }
  .task-item {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    margin-bottom: 4px;
    transition: background 0.2s;
    cursor: pointer;
  }
  .task-item:hover { background: var(--surface2); }
  .task-check {
    width: 16px; height: 16px;
    border: 1.5px solid var(--border);
    border-radius: 4px;
    flex-shrink: 0;
    margin-top: 1px;
    transition: all 0.2s;
    display: flex; align-items: center; justify-content: center;
  }
  .task-item.done .task-check {
    background: var(--success);
    border-color: var(--success);
  }
  .task-item.done .task-check::after { content: '✓'; font-size: 10px; color: #000; }
  .task-text { font-size: 12px; line-height: 1.4; }
  .task-item.done .task-text { text-decoration: line-through; color: var(--muted); }
  .tasks-empty { padding: 20px; text-align: center; color: var(--muted); font-size: 12px; }

  /* CHAT */
  .chat-area {
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .messages {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .messages::-webkit-scrollbar { width: 4px; }
  .messages::-webkit-scrollbar-track { background: transparent; }
  .messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  .message {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-width: 80%;
    animation: fadeUp 0.3s ease;
  }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .message.user { align-self: flex-end; align-items: flex-end; }
  .message.assistant { align-self: flex-start; align-items: flex-start; }
  .msg-label { font-size: 10px; color: var(--muted); letter-spacing: 1px; text-transform: uppercase; }
  .msg-bubble {
    padding: 12px 16px;
    border-radius: 12px;
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
  }
  .message.user .msg-bubble {
    background: linear-gradient(135deg, var(--accent), #5a4adf);
    color: white;
    border-bottom-right-radius: 4px;
  }
  .message.assistant .msg-bubble {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    border-bottom-left-radius: 4px;
  }
  .typing .msg-bubble { color: var(--muted); }
  .typing-dots { display: inline-flex; gap: 4px; }
  .typing-dots span {
    width: 6px; height: 6px;
    background: var(--muted);
    border-radius: 50%;
    animation: dot 1.2s infinite;
  }
  .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
  .typing-dots span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes dot {
    0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
    40% { transform: scale(1); opacity: 1; }
  }
  .chat-input-area {
    padding: 16px 24px;
    border-top: 1px solid var(--border);
    display: flex;
    gap: 12px;
    align-items: flex-end;
  }
  .chat-input {
    flex: 1;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    padding: 12px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    outline: none;
    resize: none;
    min-height: 44px;
    max-height: 120px;
    transition: border-color 0.2s;
    line-height: 1.5;
  }
  .chat-input:focus { border-color: var(--accent); }
  .send-btn {
    background: linear-gradient(135deg, var(--accent), #5a4adf);
    border: none;
    color: white;
    width: 44px; height: 44px;
    border-radius: 12px;
    cursor: pointer;
    font-size: 18px;
    transition: opacity 0.2s, transform 0.1s;
    flex-shrink: 0;
  }
  .send-btn:hover { opacity: 0.85; }
  .send-btn:active { transform: scale(0.95); }
  .send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  /* SIDEBAR RIGHT - History */
  .sidebar-right {
    background: var(--surface);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .history-list { flex: 1; overflow-y: auto; padding: 8px; }
  .history-item {
    padding: 10px 12px;
    border-radius: 8px;
    margin-bottom: 4px;
    font-size: 11px;
    color: var(--muted);
    line-height: 1.4;
    cursor: default;
    transition: background 0.2s;
  }
  .history-item:hover { background: var(--surface2); color: var(--text); }
  .history-item .hist-role {
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 3px;
  }
  .history-item .hist-role.user { color: var(--accent); }
  .history-item .hist-role.assistant { color: var(--accent2); }
  .history-text { overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .history-empty { padding: 20px; text-align: center; color: var(--muted); font-size: 12px; }

  /* LOGIN */
  #login-screen {
    position: fixed; inset: 0;
    background: var(--bg);
    display: flex; align-items: center; justify-content: center;
    z-index: 100;
  }
  .login-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 40px;
    width: 340px;
    text-align: center;
  }
  .login-logo {
    font-family: 'Syne', sans-serif;
    font-weight: 800;
    font-size: 36px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }
  .login-sub { color: var(--muted); font-size: 12px; margin-bottom: 32px; }
  .login-input {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 12px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    outline: none;
    margin-bottom: 12px;
    transition: border-color 0.2s;
  }
  .login-input:focus { border-color: var(--accent); }
  .login-btn {
    width: 100%;
    background: linear-gradient(135deg, var(--accent), #5a4adf);
    border: none;
    color: white;
    padding: 12px;
    border-radius: 8px;
    font-family: 'Syne', sans-serif;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    transition: opacity 0.2s;
  }
  .login-btn:hover { opacity: 0.85; }
  .login-error { color: var(--accent2); font-size: 12px; margin-top: 10px; display: none; }

  .quick-prompts {
    display: flex; gap: 8px; flex-wrap: wrap;
    padding: 0 24px 12px;
  }
  .qp {
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 5px 12px;
    border-radius: 20px;
    font-size: 11px;
    cursor: pointer;
    transition: all 0.2s;
    font-family: 'JetBrains Mono', monospace;
  }
  .qp:hover { border-color: var(--accent); color: var(--accent); }

  /* AGENT SELECTOR */
  .agent-selector-wrap {
    padding: 0 24px 0;
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: -4px;
  }
  .agent-label { font-size: 10px; color: var(--muted); letter-spacing: 1px; text-transform: uppercase; white-space: nowrap; }
  .agent-select {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    padding: 5px 10px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    outline: none;
    cursor: pointer;
    transition: border-color 0.2s;
  }
  .agent-select:focus { border-color: var(--accent); }
</style>
</head>
<body>

<!-- LOGIN -->
<div id="login-screen">
  <div class="login-box">
    <div class="login-logo">ClawBot</div>
    <div class="login-sub">Your personal AI agent</div>
    <input class="login-input" type="password" id="pw-input" placeholder="Enter password" />
    <button class="login-btn" onclick="doLogin()">Enter</button>
    <div class="login-error" id="login-error">Incorrect password</div>
  </div>
</div>

<!-- HEADER -->
<header>
  <div class="logo">ClawBot</div>
  <div class="status-dot"></div>
  <div class="status-text">online</div>
  <div class="header-right">
    <button class="clear-btn" onclick="clearHistory()">Clear Chat</button>
  </div>
</header>

<!-- SIDEBAR LEFT: TASKS -->
<div class="sidebar-left">
  <div class="sidebar-header">Tasks</div>
  <div class="task-input-wrap">
    <input class="task-input" id="task-input" placeholder="Add a task..." onkeydown="if(event.key==='Enter')addTask()" />
    <button class="add-btn" onclick="addTask()">+</button>
  </div>
  <div class="tasks-list" id="tasks-list">
    <div class="tasks-empty">No tasks yet</div>
  </div>
</div>

<!-- CHAT -->
<div class="chat-area">
  <div class="messages" id="messages">
    <div class="message assistant">
      <div class="msg-label">ClawBot</div>
      <div class="msg-bubble">Hey Nate 👋 I'm ready to help. Ask me anything, or try a quick action below.</div>
    </div>
  </div>
  <div class="agent-selector-wrap">
    <span class="agent-label">Agent</span>
    <select class="agent-select" id="agent-select">
      <option value="clawbot">ClawBot (General)</option>
      <option value="mr-soul-cfo">Mr. Soul CFO</option>
      <option value="appfolio-reporter">AppFolio Reporter</option>
      <option value="email-drafter">Email Drafter</option>
    </select>
  </div>
  <div class="quick-prompts">
    <div class="qp" onclick="quickPrompt('Summarize this meeting: ')">📋 Summarize</div>
    <div class="qp" onclick="quickPrompt('Research: ')">🔍 Research</div>
    <div class="qp" onclick="quickPrompt('Draft an email about: ')">✉️ Draft Email</div>
    <div class="qp" onclick="quickPrompt('What should I prioritize today?')">⚡ Prioritize</div>
  </div>
  <div class="chat-input-area">
    <textarea class="chat-input" id="chat-input" placeholder="Message ClawBot..." rows="1"
      onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage()}"
      oninput="autoResize(this)"></textarea>
    <button class="send-btn" id="send-btn" onclick="sendMessage()">↑</button>
  </div>
</div>

<!-- SIDEBAR RIGHT: HISTORY -->
<div class="sidebar-right">
  <div class="sidebar-header">History</div>
  <div class="history-list" id="history-list">
    <div class="history-empty">No history yet</div>
  </div>
</div>

<script>
  // ── AUTH ──
  const SESSION_KEY = 'clawbot_auth';
  function doLogin() {
    const pw = document.getElementById('pw-input').value;
    fetch('/api/login', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({password: pw}) })
      .then(r => r.json()).then(d => {
        if (d.ok) {
          sessionStorage.setItem(SESSION_KEY, '1');
          document.getElementById('login-screen').style.display = 'none';
        } else {
          document.getElementById('login-error').style.display = 'block';
        }
      });
  }
  document.getElementById('pw-input').addEventListener('keydown', e => { if(e.key==='Enter') doLogin(); });
  if (sessionStorage.getItem(SESSION_KEY)) document.getElementById('login-screen').style.display = 'none';

  // ── TASKS ──
  let tasks = [];
  function addTask() {
    const input = document.getElementById('task-input');
    const text = input.value.trim();
    if (!text) return;
    tasks.push({ text, done: false });
    input.value = '';
    renderTasks();
  }
  function toggleTask(i) {
    tasks[i].done = !tasks[i].done;
    renderTasks();
  }
  function renderTasks() {
    const el = document.getElementById('tasks-list');
    if (tasks.length === 0) { el.innerHTML = '<div class="tasks-empty">No tasks yet</div>'; return; }
    el.innerHTML = tasks.map((t, i) => \`
      <div class="task-item \${t.done ? 'done' : ''}" onclick="toggleTask(\${i})">
        <div class="task-check"></div>
        <div class="task-text">\${t.text}</div>
      </div>\`).join('');
  }

  // ── CHAT ──
  let history = [];
  async function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    autoResize(input);
    document.getElementById('send-btn').disabled = true;

    appendMessage('user', 'You', text);
    addHistory('user', text);

    const typing = appendTyping();

    try {
      const agentId = document.getElementById('agent-select').value;
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ message: text, history, agent: agentId })
      });
      const data = await res.json();
      typing.remove();
      appendMessage('assistant', data.agentName || 'ClawBot', data.reply);
      addHistory('assistant', data.reply);
      history.push({ role: 'user', content: text });
      history.push({ role: 'assistant', content: data.reply });
    } catch(e) {
      typing.remove();
      appendMessage('assistant', 'ClawBot', '❌ Error connecting to server.');
    }
    document.getElementById('send-btn').disabled = false;
  }

  function appendMessage(role, label, text) {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = \`message \${role}\`;
    div.innerHTML = \`<div class="msg-label">\${label}</div><div class="msg-bubble">\${text}</div>\`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function appendTyping() {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'message assistant typing';
    div.innerHTML = \`<div class="msg-label">ClawBot</div><div class="msg-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>\`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  function addHistory(role, text) {
    const el = document.getElementById('history-list');
    const empty = el.querySelector('.history-empty');
    if (empty) empty.remove();
    const div = document.createElement('div');
    div.className = 'history-item';
    div.innerHTML = \`<div class="hist-role \${role}">\${role === 'user' ? 'You' : 'ClawBot'}</div><div class="history-text">\${text}</div>\`;
    el.insertBefore(div, el.firstChild);
  }

  function clearHistory() {
    history = [];
    document.getElementById('messages').innerHTML = \`
      <div class="message assistant">
        <div class="msg-label">ClawBot</div>
        <div class="msg-bubble">Chat cleared. How can I help you, Nate?</div>
      </div>\`;
    document.getElementById('history-list').innerHTML = '<div class="history-empty">No history yet</div>';
  }

  function quickPrompt(text) {
    const input = document.getElementById('chat-input');
    input.value = text;
    input.focus();
    autoResize(input);
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }
</script>
</body>
</html>`;

// ─── SERVER ───────────────────────────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);

  // CORS
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  // Serve HTML
  if (req.method === "GET" && parsed.pathname === "/") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(HTML);
    return;
  }

  // Login
  if (req.method === "POST" && parsed.pathname === "/api/login") {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      const { password } = JSON.parse(body);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: password === PASSWORD }));
    });
    return;
  }

  // Chat
  if (req.method === "POST" && parsed.pathname === "/api/chat") {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", async () => {
      const { message, history, agent } = JSON.parse(body);
      const agentModule = getAgent(agent) || (agent === "clawbot" ? routeAgent(message) : null);
      const systemPrompt = agentModule ? agentModule.systemPrompt : SYSTEM_PROMPT;
      const agentName = agentModule ? agentModule.name : "ClawBot";
      const messages = [
        { role: "system", content: systemPrompt },
        ...(history || []).slice(-10),
        { role: "user", content: message },
      ];
      try {
        let reply;
        if (agentModule && agentModule.apiCall) {
          // Agent has a dedicated API — call it directly (e.g. Mr Soul CFO on port 8002)
          reply = await agentModule.apiCall(message);
        } else {
          reply = await askModel(messages);
        }
        const codeMatch = reply.match(/```(python|javascript|js)\n([\s\S]*?)```/);
        if (codeMatch) {
          const lang = codeMatch[1] === "js" ? "javascript" : codeMatch[1];
          const code = codeMatch[2];
          const execResult = await executeCode(lang, code);
          reply += "\n\n**Execution Result:**\n```\n" + execResult + "\n```";
        }
        if (db) {
          db.collection("queries").insertOne({
            timestamp: new Date(),
            agent: agent || "clawbot",
            message,
            reply,
          }).catch(err => console.error("[Logger] Write failed:", err.message));
        }
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ reply, agentName }));
      } catch (err) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ reply: `Error: ${err}`, agentName: "ClawBot" }));
      }
    });
    return;
  }


  // ── Brain auth guard ────────────────────────────────────────────────────────
  // Hard 403 for cfo/dayton browser origins. Requires x-internal-key on all calls.
  if (parsed.pathname.startsWith("/api/brain/")) {
    const origin = (req.headers["origin"] || req.headers["referer"] || "").toLowerCase();
    if (origin.includes("cfo.peak10group.com") || origin.includes("dayton.peak10group.com")) {
      res.writeHead(403, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Forbidden: brain endpoints are clawbot-only." }));
      return;
    }
    const key = req.headers["x-internal-key"] || "";
    if (!INTERNAL_KEY || key !== INTERNAL_KEY) {
      res.writeHead(403, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Forbidden: missing or invalid x-internal-key." }));
      return;
    }
  }

  // ── /api/brain/ask — Mr. Soul CFO analysis — clawbot ONLY ──────────────────
  if (req.method === "POST" && parsed.pathname === "/api/brain/ask") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      let payload;
      try { payload = JSON.parse(body); } catch (e) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Invalid JSON" }));
        return;
      }
      const user = payload.user || {
        name: "Nate Fisher", email: "nfisher@peak10group.com", role: "owner", properties: "all",
      };
      const outBody = JSON.stringify({ message: payload.message, user, messages: payload.messages });
      const proxyReq = http.request({
        hostname: "localhost",
        port: 3001,
        path: "/api/internal/ask",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(outBody),
          "x-internal-key": INTERNAL_KEY,
        },
      }, (proxyRes) => {
        let data = "";
        proxyRes.on("data", (c) => (data += c));
        proxyRes.on("end", () => {
          res.writeHead(proxyRes.statusCode, { "Content-Type": "application/json" });
          res.end(data);
        });
      });
      proxyReq.on("error", (err) => {
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: `Brain (Mr. Soul) unavailable: ${err.message}` }));
      });
      proxyReq.setTimeout(90000, () => { proxyReq.destroy(); });
      proxyReq.write(outBody);
      proxyReq.end();
    });
    return;
  }

  // ── /api/brain/agent — Hatfield / Tracy — clawbot ONLY ─────────────────────
  if (req.method === "POST" && parsed.pathname === "/api/brain/agent") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", async () => {
      let payload;
      try { payload = JSON.parse(body); } catch (e) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Invalid JSON" }));
        return;
      }
      const { message, agent: agentId } = payload;
      const agentModule = getAgent(agentId) || routeAgent(message);
      if (!agentModule) {
        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: `No agent found for: ${agentId || "(auto-route)"}` }));
        return;
      }
      try {
        let reply;
        if (agentModule.apiCall) {
          reply = await agentModule.apiCall(message);
        } else {
          const msgs = [
            { role: "system", content: agentModule.systemPrompt || SYSTEM_PROMPT },
            { role: "user", content: message },
          ];
          reply = await askModel(msgs);
        }
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ reply, agent: agentModule.name }));
      } catch (err) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: err.message }));
      }
    });
    return;
  }

  // ── /api/brain/report — .docx report — clawbot ONLY ─────────────────────────
  // Proxies to mrsoul /api/internal/report. Returns docx blob directly.
  // type defaults to 'finance' (Nate = owner). Pass { type: 'operations' } to override.
  if (req.method === "POST" && parsed.pathname === "/api/brain/report") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      let payload;
      try { payload = JSON.parse(body); } catch (e) {
        res.writeHead(400, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Invalid JSON" }));
        return;
      }
      const user = payload.user || {
        name: "Nate Fisher", email: "nfisher@peak10group.com", role: "owner", properties: "all",
      };
      const outBody = JSON.stringify({ user, type: payload.type || "finance" });
      const proxyReq = http.request({
        hostname: "localhost",
        port: 3001,
        path: "/api/internal/report",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(outBody),
          "x-internal-key": INTERNAL_KEY,
        },
      }, (proxyRes) => {
        const ct  = proxyRes.headers["content-type"]        || "application/octet-stream";
        const cd  = proxyRes.headers["content-disposition"] || 'attachment; filename="report.docx"';
        res.writeHead(proxyRes.statusCode, { "Content-Type": ct, "Content-Disposition": cd });
        proxyRes.pipe(res);
      });
      proxyReq.on("error", (err) => {
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: `Brain (Mr. Soul) unavailable: ${err.message}` }));
      });
      proxyReq.setTimeout(90000, () => { proxyReq.destroy(); });
      proxyReq.write(outBody);
      proxyReq.end();
    });
    return;
  }

  res.writeHead(404);
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`🤖 ClawBot Web UI running at http://localhost:${PORT}`);
  console.log(`📡 Access via your droplet IP: http://64.225.24.92:${PORT}`);
});
