#!/usr/bin/env python3
"""
ClawBot — Telegram bot with Mr Soul CFO integration.

Usage:
  python3 clawbot.py

Commands:
  /cfo <task>   — Send directly to Mr Soul CFO
  /tasks        — Show task list
  /add <task>   — Add a task
  /done <n>     — Complete a task
  /clear        — Clear conversation history
  (anything else routes through the Hatfield orchestrator)
"""

import anyio
import httpx
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent import MR_SOUL_CFO
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

# ── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN  = "8755322526:AAGi3N1Es4TVTpV3CKfZY_yv6gE2Wye2cXo"
ALLOWED_CHAT_ID = "8647502718"
CFO_WORKING_DIR = str(Path(__file__).parent)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

HATFIELD_SYSTEM_PROMPT = """You are ClawBot, Nate's personal AI assistant. You handle general tasks directly.

For ANY financial task — budgets, P&L, cash flow, financial reports, cost analysis, financial emails — delegate to Mr Soul CFO using the Agent tool. He is the expert.

For everything else: help with research, summaries, drafting messages, answering questions, and general assistant tasks.
"""

# ── STATE ─────────────────────────────────────────────────────────────────────
tasks: list[dict] = []


# ── TELEGRAM HELPERS ──────────────────────────────────────────────────────────
async def tg_post(client: httpx.AsyncClient, method: str, payload: dict) -> dict:
    r = await client.post(f"{TELEGRAM_API}/{method}", json=payload, timeout=35)
    return r.json()


async def send(client: httpx.AsyncClient, chat_id: str, text: str) -> None:
    """Send a message, splitting if over Telegram's 4096-char limit."""
    limit = 4000
    chunks = [text[i:i+limit] for i in range(0, len(text), limit)]
    for chunk in chunks:
        await tg_post(client, "sendMessage", {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
        })


# ── AGENT RUNNERS ─────────────────────────────────────────────────────────────
async def run_mr_soul(task: str) -> str:
    """Run Mr Soul CFO directly and return his result."""
    result_text = ""
    async for msg in query(
        prompt=task,
        options=ClaudeAgentOptions(
            cwd=CFO_WORKING_DIR,
            system_prompt=MR_SOUL_CFO.prompt,
            model="claude-opus-4-6",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch"],
            agents={"mr-soul-cfo": MR_SOUL_CFO},
            permission_mode="bypassPermissions",

            max_turns=40,
        ),
    ):
        if isinstance(msg, ResultMessage):
            result_text = msg.result
    return result_text or "(Mr Soul CFO completed the task with no text output.)"


async def run_hatfield(task: str) -> str:
    """Route through Hatfield orchestrator (auto-delegates financial tasks to Mr Soul)."""
    result_text = ""
    async for msg in query(
        prompt=task,
        options=ClaudeAgentOptions(
            cwd=CFO_WORKING_DIR,
            system_prompt=HATFIELD_SYSTEM_PROMPT,
            model="claude-opus-4-6",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "Agent"],
            agents={"mr-soul-cfo": MR_SOUL_CFO},
            permission_mode="bypassPermissions",

            max_turns=60,
        ),
    ):
        if isinstance(msg, ResultMessage):
            result_text = msg.result
    return result_text or "(Task completed with no text output.)"


# ── MESSAGE HANDLER ───────────────────────────────────────────────────────────
async def handle(client: httpx.AsyncClient, chat_id: str, text: str) -> None:
    if chat_id != ALLOWED_CHAT_ID:
        await send(client, chat_id, "⛔ Unauthorized.")
        return

    text = text.strip()

    # ── Built-in commands ──────────────────────────────────────────────────────
    if text in ("/start", "/help"):
        await send(client, chat_id,
            "*ClawBot is ready.*\n\n"
            "*Commands:*\n"
            "`/cfo <task>` — Send directly to Mr Soul CFO\n"
            "`/tasks` — Show task list\n"
            "`/add <task>` — Add a task\n"
            "`/done <n>` — Complete a task\n"
            "`/clear` — Clear task list\n\n"
            "Or just message naturally — financial tasks auto-route to Mr Soul CFO."
        )
        return

    if text == "/tasks":
        if not tasks:
            await send(client, chat_id, "📋 No tasks yet.")
        else:
            lines = "\n".join(
                f"{i+1}. {'✅' if t['done'] else '⬜'} {t['text']}"
                for i, t in enumerate(tasks)
            )
            await send(client, chat_id, f"📋 *Tasks:*\n{lines}")
        return

    if text.startswith("/add "):
        task_text = text[5:].strip()
        tasks.append({"text": task_text, "done": False})
        await send(client, chat_id, f"✅ Added: _{task_text}_")
        return

    if text.startswith("/done "):
        try:
            idx = int(text[6:].strip()) - 1
            if 0 <= idx < len(tasks):
                tasks[idx]["done"] = True
                await send(client, chat_id, f"✅ Done: _{tasks[idx]['text']}_")
            else:
                await send(client, chat_id, "❌ Task not found.")
        except ValueError:
            await send(client, chat_id, "❌ Usage: /done <number>")
        return

    if text == "/clear":
        tasks.clear()
        await send(client, chat_id, "🧹 Task list cleared.")
        return

    # ── Agent routing ──────────────────────────────────────────────────────────
    if text.lower().startswith("/cfo "):
        cfo_task = text[5:].strip()
        await send(client, chat_id, "💼 Mr Soul CFO is on it...")
        result = await run_mr_soul(cfo_task)
        await send(client, chat_id, result)
        return

    # All other messages → Hatfield orchestrator
    await send(client, chat_id, "⏳ On it...")
    result = await run_hatfield(text)
    await send(client, chat_id, result)


# ── POLLING LOOP ──────────────────────────────────────────────────────────────
async def poll() -> None:
    offset = 0
    print("ClawBot running — waiting for messages...")

    async with httpx.AsyncClient() as client:
        while True:
            try:
                resp = await tg_post(client, "getUpdates", {
                    "offset": offset,
                    "timeout": 30,
                })

                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    if msg.get("text"):
                        chat_id = str(msg["chat"]["id"])
                        text = msg["text"]
                        print(f"[{chat_id}] {text[:80]}")
                        anyio.from_thread.run_sync(lambda: None)  # yield
                        await handle(client, chat_id, text)

            except Exception as e:
                print(f"Polling error: {e}")
                await anyio.sleep(5)


if __name__ == "__main__":
    anyio.run(poll)
