#!/usr/bin/env node

require("dotenv").config({ path: "/root/.env" });
const https = require("https");
const fs = require("fs");
const { exec } = require("child_process");
const os = require("os");
const path = require("path");

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const TELEGRAM_TOKEN     = process.env.TELEGRAM_TOKEN  || "8755322526:AAFt34EZfF7sOgEM9BygLM16_Mol9xyxspg";
const ALLOWED_CHAT_ID    = process.env.ALLOWED_CHAT_ID || "8647502718";
const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY || "";
const TAVILY_API_KEY     = process.env.TAVILY_API_KEY || "";
const MEMORY_DIR         = "/root/.openclaw/workspace-hatfield/memory";

// ─── MODEL ROUTER ─────────────────────────────────────────────────────────────
const MODELS = {
  SONNET:  "anthropic/claude-sonnet-4.6",
  HAIKU:   "anthropic/claude-haiku-4.5",
  MINIMAX: "minimax/minimax-m2.5",
};
const SIMPLE_KEYWORDS = ["summarize","format","reformat","convert","translate","list","bullet","short","quick","simple"];

function routeModel(prompt) {
  const p = prompt.toLowerCase();
  const isCoding = /\b(code|function|script|debug|refactor|implement|class|module|node|python|javascript|typescript|api|endpoint|bug|error|fix)\b/i.test(p);
  if (isCoding) return MODELS.MINIMAX;
  const isSimple = SIMPLE_KEYWORDS.some(k => p.includes(k));
  if (isSimple || prompt.length < 300) return MODELS.HAIKU;
  return MODELS.SONNET;
}

// ─── WEB SEARCH DETECTION ─────────────────────────────────────────────────────
const SEARCH_TRIGGERS = /\b(weather|news|today|current|latest|price|stock|market|rate|score|game|who won|what happened|right now|this week|forecast|update|recent)\b/i;

function needsSearch(prompt) {
  return TAVILY_API_KEY && SEARCH_TRIGGERS.test(prompt);
}

// ─── TAVILY SEARCH ────────────────────────────────────────────────────────────
async function tavilySearch(query) {
  const data = JSON.stringify({ api_key: TAVILY_API_KEY, query, search_depth: "basic", max_results: 5 });
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: "api.tavily.com",
      path: "/search",
      method: "POST",
      family: 4,
      headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(data) },
    }, (res) => {
      let result = "";
      res.on("data", c => result += c);
      res.on("end", () => {
        try {
          const json = JSON.parse(result);
          const snippets = (json.results || []).map(r => `- ${r.title}: ${r.content}`).join("\n");
          resolve(snippets || "No results found.");
        } catch (e) { resolve("Search unavailable."); }
      });
    });
    req.on("error", () => resolve("Search unavailable."));
    req.write(data);
    req.end();
  });
}

// ─── MEMORY / LOGGING ─────────────────────────────────────────────────────────
function appendToLog(role, message) {
  try {
    if (!fs.existsSync(MEMORY_DIR)) fs.mkdirSync(MEMORY_DIR, { recursive: true });
    const today = new Date().toISOString().split("T")[0];
    const logFile = MEMORY_DIR + "/" + today + ".md";
    const time = new Date().toTimeString().split(" ")[0].slice(0, 5);
    fs.appendFileSync(logFile, "[" + time + "] " + role + ": " + String(message).slice(0, 200) + "\n");
  } catch (e) { console.error("Log error:", e); }
}

// ─── CONVERSATION HISTORY ─────────────────────────────────────────────────────
let conversationHistory = [];

// ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────
const SYSTEM_PROMPT = `You are Hatfield Fisher, the personal AI agent for Nathan "Nate" Fisher. You serve as his strategic advisor, research assistant, document generator, and productivity engine.

## WHO NATE IS
Nate Fisher is a real estate investor and family office principal based in Columbus, Ohio. He has 25+ years of experience in multi-family real estate. He is the CEO/CIO of the Fisher Family Office and is actively transitioning from active operator to passive investor over the next 5-7 years.

## FISHER FAMILY OFFICE
- Board of Directors: Nate Fisher, Kyle Fisher, Clare Brofford
- CEO/CIO: Nate Fisher
- External advisors: Estate planning, tax strategy, insurance
- Goal: Long-term wealth preservation and multi-generational planning

## INVESTMENT CRITERIA
- Target IRR: 17%+
- Target cash-on-cash: 7-8% annually
- Preferred asset class: Multi-family commercial real estate
- Portfolio transition: Currently ~80% active / ~20% passive, target ~20% active / ~80% passive
- Liquidity reserve: 20-30% of portfolio maintained at all times

## CURRENT PRIORITIES
1. Fisher Family Office development and governance
2. Real estate portfolio management (Dayton, Ohio and other markets)
3. Transitioning toward passive LP investments and JVs
4. Building and refining the AI Brain knowledge system

## KEY METRICS NATE TRACKS
IRR, DSCR, NOI, Cap Rate, Occupancy Rate, Rent Growth

## HOW TO RESPOND TO NATE
- Be structured, strategic, concise, and actionable
- Avoid vague or generic advice
- Use sections, bullet points, and frameworks
- Present options as A / B / C with pros and cons
- Default response format: Summary, Key Insights, Recommendations
- Preferred output formats: DOCX, Excel, PDF, structured summaries

## WHAT YOU HELP NATE WITH
- Real estate financial analysis (P&L, rent rolls, cap rates, IRR)
- Passive deal evaluation against his investment criteria
- Investor reporting and updates
- Leasing strategy and property operations
- Family office strategy and governance decisions
- Document drafting (emails, memos, reports)
- Weekly reviews and prioritization
- AI workflow and knowledge management

## GUIDING PRINCIPLE
Always respond with: Context, Strategy, Structure, Action. When Nate asks a complex question: give a short direct answer first, then a structured breakdown, then offer to go deeper.`;

// ─── HTTP HELPER ──────────────────────────────────────────────────────────────
function httpPost(hostname, path, body, extraHeaders = {}) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const req = https.request({
      hostname,
      path,
      method: "POST",
      family: 4,
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(data),
        ...extraHeaders,
      },
    }, (res) => {
      let result = "";
      res.on("data", (chunk) => (result += chunk));
      res.on("end", () => {
        try { resolve(JSON.parse(result)); }
        catch (e) { reject("Parse error: " + result); }
      });
    });
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}

// ─── SEND TELEGRAM MESSAGE ────────────────────────────────────────────────────
async function sendMessage(chatId, text) {
  const chunks = text.match(/[\s\S]{1,4000}/g) || [text];
  for (const chunk of chunks) {
    await httpPost("api.telegram.org", `/bot${TELEGRAM_TOKEN}/sendMessage`, {
      chat_id: chatId,
      text: chunk,
      parse_mode: "Markdown",
    });
  }
}

// ─── ASK MODEL ────────────────────────────────────────────────────────────────
async function askModel(userMessage) {
  const model = routeModel(userMessage);
  console.log(`[Router] → ${model}`);

  let contextMessage = userMessage;
  if (needsSearch(userMessage)) {
    console.log("[Tavily] Searching...");
    const results = await tavilySearch(userMessage);
    contextMessage = `User question: ${userMessage}\n\nWeb search results (use these to answer):\n${results}`;
  }

  conversationHistory.push({ role: "user", content: contextMessage });
  if (conversationHistory.length > 20) conversationHistory = conversationHistory.slice(-20);

  const messages = [
    { role: "system", content: SYSTEM_PROMPT },
    ...conversationHistory,
  ];

  const response = await httpPost("openrouter.ai", "/api/v1/chat/completions",
    { model, messages, max_tokens: 1500 },
    {
      "Authorization": `Bearer ${OPENROUTER_API_KEY}`,
      "HTTP-Referer": "https://clawbot.peak10group.com",
    }
  );

  if (response.error) throw new Error(response.error.message || JSON.stringify(response.error));

  const reply = response.choices[0].message.content;
  conversationHistory.push({ role: "assistant", content: reply });
  return reply;
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

// ─── HANDLE MESSAGE ───────────────────────────────────────────────────────────
async function handleMessage(chatId, text) {
  if (String(chatId) !== ALLOWED_CHAT_ID) {
    await sendMessage(chatId, "Unauthorized.");
    return;
  }

  if (text === "/start") {
    await sendMessage(chatId, "👋 Hatfield Fisher online. How can I help you, Nate?");
    return;
  }
  if (text === "/clear") {
    conversationHistory = [];
    await sendMessage(chatId, "🧹 Conversation cleared.");
    return;
  }
  if (text === "/status") {
    const searchStatus = TAVILY_API_KEY ? "🔍 Web search enabled" : "🔍 Web search disabled (no key)";
    await sendMessage(chatId, `✅ Online\n🔁 History: ${conversationHistory.length} messages\n${searchStatus}`);
    return;
  }

  try {
    appendToLog("Nate", text);
    await sendMessage(chatId, "⏳ Thinking...");
    let reply = await askModel(text);
    const codeMatch = reply.match(/```(python|javascript|js)\n([\s\S]*?)```/);
    if (codeMatch) {
      const lang = codeMatch[1] === "js" ? "javascript" : codeMatch[1];
      const code = codeMatch[2];
      const execResult = await executeCode(lang, code);
      reply += "\n\n**Execution Result:**\n```\n" + execResult + "\n```";
    }
    appendToLog("Hatfield", reply);
    await sendMessage(chatId, reply);
  } catch (err) {
    console.error("Error:", err);
    await sendMessage(chatId, `❌ Error: ${err.message || err}`);
  }
}

// ─── POLLING ──────────────────────────────────────────────────────────────────
async function poll() {
  let offset = 0;
  const searchStatus = TAVILY_API_KEY ? "🔍 Tavily web search enabled" : "🔍 Web search disabled";
  console.log("🤖 Hatfield Fisher (Telegram) is running...");
  console.log(searchStatus);

  while (true) {
    try {
      const res = await httpPost("api.telegram.org", `/bot${TELEGRAM_TOKEN}/getUpdates`, {
        offset,
        timeout: 30,
      });

      if (res.result && res.result.length > 0) {
        for (const update of res.result) {
          offset = update.update_id + 1;
          if (update.message && update.message.text) {
            const chatId = update.message.chat.id;
            const text = update.message.text;
            console.log(`[${chatId}] ${text}`);
            handleMessage(chatId, text).catch(console.error);
          }
        }
      }
    } catch (err) {
      console.error("Polling error:", err);
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

poll();
