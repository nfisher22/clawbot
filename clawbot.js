#!/usr/bin/env node

const https = require("https");
const readline = require("readline");
const { exec } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const OPENAI_API_KEY = process.env.OPENAI_API_KEY || "YOUR_OPENAI_API_KEY_HERE";
const MODEL = "gpt-4o";

// ─── TASK LIST (in-memory) ─────────────────────────────────────────────────────
let tasks = [];

// ─── SYSTEM PROMPT ────────────────────────────────────────────────────────────
const SYSTEM_PROMPT = `You are ClawBot, a smart personal AI assistant and agent. You help your owner Nate with:
- Summarizing emails and meeting notes
- Researching topics
- Managing a to-do list
- Drafting professional emails and messages
- Monitoring and alerting on topics

Current task list: ${JSON.stringify(tasks)}

Commands Nate can use:
  /summarize [text]   - Summarize meeting notes or emails
  /research [topic]   - Research a topic
  /draft [context]    - Draft an email or message
  /add [task]         - Add a task to the to-do list
  /tasks              - Show all tasks
  /done [task number] - Mark a task complete
  /help               - Show available commands

For any other input, respond helpfully as a smart assistant.
Always be concise, professional, and friendly.`;

// ─── OPENAI API CALL ──────────────────────────────────────────────────────────
function askOpenAI(messages) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ model: MODEL, messages, max_tokens: 1000 });

    const req = https.request(
      {
        hostname: "api.openai.com",
        path: "/v1/chat/completions",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${OPENAI_API_KEY}`,
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          try {
            const parsed = JSON.parse(data);
            if (parsed.error) return reject(parsed.error.message);
            resolve(parsed.choices[0].message.content);
          } catch (e) {
            reject("Failed to parse response");
          }
        });
      }
    );

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

// ─── HANDLE COMMANDS ──────────────────────────────────────────────────────────
function handleCommand(input) {
  if (input.startsWith("/tasks")) {
    if (tasks.length === 0) return console.log("\n📋 No tasks yet!\n");
    console.log("\n📋 Your Tasks:");
    tasks.forEach((t, i) =>
      console.log(`  ${i + 1}. [${t.done ? "✅" : "  "}] ${t.text}`)
    );
    console.log();
    return true;
  }

  if (input.startsWith("/add ")) {
    const task = input.slice(5).trim();
    tasks.push({ text: task, done: false });
    console.log(`\n✅ Task added: "${task}"\n`);
    return true;
  }

  if (input.startsWith("/done ")) {
    const num = parseInt(input.slice(6).trim()) - 1;
    if (tasks[num]) {
      tasks[num].done = true;
      console.log(`\n✅ Marked done: "${tasks[num].text}"\n`);
    } else {
      console.log("\n❌ Task not found.\n");
    }
    return true;
  }

  if (input === "/help") {
    console.log(`
🤖 ClawBot Commands:
  /summarize [text]   - Summarize meeting notes or emails
  /research [topic]   - Research a topic
  /draft [context]    - Draft an email or message
  /add [task]         - Add a task
  /tasks              - Show all tasks
  /done [number]      - Mark task complete
  /help               - Show this help
  exit                - Quit ClawBot
    `);
    return true;
  }

  return false;
}

// ─── MAIN LOOP ────────────────────────────────────────────────────────────────
async function main() {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  const conversationHistory = [{ role: "system", content: SYSTEM_PROMPT }];

  console.log("\n🤖 ClawBot is ready! Type /help for commands or just chat.");
  console.log('Type "exit" to quit.\n');

  const ask = () => {
    rl.question("You: ", async (input) => {
      input = input.trim();
      if (!input) return ask();
      if (input.toLowerCase() === "exit") {
        console.log("\n👋 ClawBot signing off. See you later, Nate!\n");
        rl.close();
        return;
      }

      // Handle local commands
      if (handleCommand(input)) return ask();

      // Send to OpenAI
      conversationHistory.push({ role: "user", content: input });

      try {
        process.stdout.write("\nClawBot: ");
        let response = await askOpenAI(conversationHistory);
        const codeMatch = response.match(/```(python|javascript|js)\n([\s\S]*?)```/);
        if (codeMatch) {
          const lang = codeMatch[1] === "js" ? "javascript" : codeMatch[1];
          const code = codeMatch[2];
          const execResult = await executeCode(lang, code);
          response += "\n\n**Execution Result:**\n```\n" + execResult + "\n```";
        }
        console.log(response + "\n");
        conversationHistory.push({ role: "assistant", content: response });
      } catch (err) {
        console.log(`\n❌ Error: ${err}\n`);
      }

      ask();
    });
  };

  ask();
}

main();
