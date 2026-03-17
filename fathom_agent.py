#!/usr/bin/env python3
"""
Hatfield Fathom Video Agent — pulls meeting summaries via REST API
Base URL: https://api.fathom.ai/external/v1
Auth: X-Api-Key header
"""
import os
import requests
from datetime import datetime, timezone
from vault_secrets import get_secrets
get_secrets()

FATHOM_API_KEY = os.getenv("FATHOM_API_KEY")
FATHOM_BASE = "https://api.fathom.ai/external/v1"
AUDIT_LOG = "/opt/clawbot/logs/audit.log"

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass

def get_headers():
    return {"X-Api-Key": FATHOM_API_KEY, "Content-Type": "application/json"}

def get_recent_meetings(limit=5):
    try:
        response = requests.get(
            f"{FATHOM_BASE}/meetings",
            headers=get_headers(),
            params={
                "limit": limit,
                "include_summary": True,
                "include_action_items": True
            },
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            meetings = data.get("items", [])
            audit("INFO", "fathom-agent", f"Retrieved {len(meetings)} meetings")
            return meetings
        else:
            audit("ERROR", "fathom-agent", f"API error: {response.status_code} — {response.text[:200]}")
            return []
    except Exception as e:
        audit("ERROR", "fathom-agent", f"Exception: {e}")
        return []

def format_meetings(meetings):
    if not meetings:
        return "No recent meetings found in Fathom."
    lines = [f"🎙️ *Recent Fathom Meetings* ({len(meetings)} found)\n"]
    for m in meetings:
        title = m.get("title") or m.get("meeting_title") or "Untitled"
        date = (m.get("created_at") or m.get("scheduled_start_time") or "")[:10]
        url = m.get("url", "")
        summary = m.get("default_summary", {})
        overview = summary.get("markdown_formatted", "") if summary else ""
        if overview and len(overview) > 200:
            overview = overview[:200] + "..."
        action_items = m.get("action_items", []) or []
        lines.append(f"📅 *{title}*")
        lines.append(f"   Date: {date}")
        if overview:
            lines.append(f"   {overview.strip()}")
        if action_items:
            for item in action_items[:3]:
                desc = item.get("description", "")
                if desc:
                    lines.append(f"   • {desc[:100]}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")
    return "\n".join(lines)

def save_meetings_to_memory(meetings):
    from pathlib import Path
    memory_dir = Path("/root/.openclaw/workspace-hatfield/memory/meetings")
    memory_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for m in meetings:
        title = (m.get("title") or m.get("meeting_title") or "Untitled").replace("/", "-")
        date = (m.get("created_at") or "")[:10]
        summary = m.get("default_summary", {}) or {}
        overview = summary.get("markdown_formatted", "No summary available")
        action_items = m.get("action_items", []) or []
        content = f"# {title}\nDate: {date}\n\n## Summary\n{overview}\n"
        if action_items:
            content += "\n## Action Items\n"
            for item in action_items:
                content += f"- {item.get('description', '')}\n"
        filename = f"{date}-{title[:50].replace(' ', '-')}.md"
        (memory_dir / filename).write_text(content)
        saved += 1
    return saved

if __name__ == "__main__":
    print("Testing Fathom Video connection...")
    meetings = get_recent_meetings(3)
    print(format_meetings(meetings))
