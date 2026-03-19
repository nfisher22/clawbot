#!/usr/bin/env python3
"""
Hatfield Orchestrator — routes tasks to the right agent.

Financial tasks are automatically delegated to Mr Soul CFO.
All other tasks are handled directly.

Usage:
  python hatfield.py "Review the Q3 budget variance"
  python hatfield.py "Schedule a team meeting for next Tuesday"
  python hatfield.py  (interactive mode)
"""

import anyio
import sys
import os
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage, SystemMessage
from agent import MR_SOUL_CFO

ORCHESTRATOR_PROMPT = """You are Hatfield's personal AI assistant and chief of staff.

You have a team of specialist agents available to you. When a task falls within a specialist's domain, delegate it to them using the Agent tool — do not attempt it yourself.

## Your Team

**Mr Soul CFO** — delegate ALL financial tasks to him, including:
- Budget analysis, P&L review, cash flow, burn rate, runway
- Financial report generation (board decks, investor memos, summaries)
- Drafting financial emails or communications
- Any task involving numbers, spreadsheets, or financial data

## For Everything Else
Handle non-financial tasks directly using your available tools.

## Delegation Style
When delegating to Mr Soul CFO, pass the full task context so he can work autonomously.
After he completes the task, summarize his output for Hatfield if needed.
"""


async def run_task(task: str, working_dir: str) -> None:
    print(f"\nHatfield\n{'─' * 60}")
    print(f"Task: {task}")
    print(f"Working directory: {working_dir}")
    print('─' * 60)

    session_id = None

    async for message in query(
        prompt=task,
        options=ClaudeAgentOptions(
            cwd=working_dir,
            system_prompt=ORCHESTRATOR_PROMPT,
            model="claude-opus-4-6",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "Agent"],
            agents={"mr-soul-cfo": MR_SOUL_CFO},
            permission_mode="bypassPermissions",
            max_turns=60,
        ),
    ):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            session_id = message.session_id

        if isinstance(message, ResultMessage):
            print(f"\n{'─' * 60}")
            print(message.result)
            if session_id:
                print(f"\nSession: {session_id}")


def interactive_mode(working_dir: str) -> None:
    print("Hatfield — Interactive Mode")
    print("Financial tasks will be routed to Mr Soul CFO automatically.")
    print("Type 'exit' or Ctrl-C to quit.\n")
    while True:
        try:
            task = input("Task: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not task:
            continue
        if task.lower() in ("exit", "quit", "q"):
            print("Goodbye.")
            break

        anyio.run(run_task, task, working_dir)
        print()


def main() -> None:
    args = sys.argv[1:]

    working_dir = os.getcwd()
    if args and Path(args[-1]).is_dir():
        working_dir = str(Path(args[-1]).resolve())
        args = args[:-1]

    if args:
        task = " ".join(args)
        anyio.run(run_task, task, working_dir)
    else:
        interactive_mode(working_dir)


if __name__ == "__main__":
    main()
