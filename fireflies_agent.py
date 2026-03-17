#!/usr/bin/env python3
"""
Hatfield Fireflies Agent — pulls meeting transcripts and summaries via GraphQL
"""
import os
import requests
from datetime import datetime, timezone
from vault_secrets import get_secrets
get_secrets()

FIREFLIES_API_KEY = os.getenv("FIREFLIES_API_KEY")
FIREFLIES_URL = "https://api.fireflies.ai/graphql"
AUDIT_LOG = "/opt/clawbot/logs/audit.log"

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass

def graphql(query, variables=None):
    headers = {
        "Authorization": f"Bearer {FIREFLIES_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    response = requests.post(FIREFLIES_URL, headers=headers, json=payload, timeout=15)
    return response.json()

def get_recent_transcripts(limit=5):
    query = """
    query {
        transcripts(limit: %d) {
            id
            title
            date
            duration
            summary {
                overview
                action_items
            }
            organizer_email
        }
    }
    """ % limit
    try:
        data = graphql(query)
        transcripts = data.get("data", {}).get("transcripts", [])
        audit("INFO", "fireflies-agent", f"Retrieved {len(transcripts)} transcripts")
        return transcripts
    except Exception as e:
        audit("ERROR", "fireflies-agent", f"Exception: {e}")
        return []

def format_transcripts(transcripts):
    if not transcripts:
        return "No recent meetings found in Fireflies."
    lines = [f"🎙️ *Recent Meetings* ({len(transcripts)} found)\n"]
    for t in transcripts:
        title = t.get("title", "Untitled")
        raw_date = t.get("date", "")
        try:
            from datetime import datetime
            if isinstance(raw_date, (int, float)):
                date = datetime.fromtimestamp(raw_date).strftime("%Y-%m-%d")
            else:
                date = str(raw_date)[:10]
        except:
            date = str(raw_date)[:10]
        duration = t.get("duration", 0)
        duration_str = f"{duration // 60}min" if duration else "—"
        summary = t.get("summary", {})
        overview = summary.get("overview", "") if summary else ""
        action_items = summary.get("action_items", []) if summary else []
        if overview and len(overview) > 200:
            overview = overview[:200] + "..."
        lines.append(f"📅 *{title}*")
        lines.append(f"   Date: {date} | Duration: {duration_str}")
        if overview:
            lines.append(f"   {overview}")
        if action_items:
            clean_actions = [a.strip() for a in action_items if a and len(a.strip()) > 3]
            if clean_actions:
                lines.append(f"   Actions: {chr(10).join(f'   • {a[:100]}' for a in clean_actions[:3])}")
        lines.append("")
    return "\n".join(lines)

def get_transcript_detail(transcript_id):
    query = """
    query($id: String!) {
        transcript(id: $id) {
            title
            date
            duration
            summary {
                overview
                action_items
                keywords
            }
            sentences {
                text
                speaker_name
            }
        }
    }
    """
    try:
        data = graphql(query, {"id": transcript_id})
        return data.get("data", {}).get("transcript", {})
    except Exception as e:
        return {"error": str(e)}

def save_transcripts_to_memory(transcripts):
    """Save meeting summaries to Droplet memory for context."""
    from pathlib import Path
    memory_dir = Path("/root/.openclaw/workspace-hatfield/memory/meetings")
    memory_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for t in transcripts:
        title = (t.get("title", "Untitled")).replace("/", "-")
        date = str(t.get("date", "unknown"))[:10]
        summary = t.get("summary", {}) or {}
        overview = summary.get("overview", "No summary available")
        action_items = summary.get("action_items", [])
        content = f"# {title}\nDate: {date}\n\n## Summary\n{overview}\n"
        if action_items:
            content += "\n## Action Items\n" + "\n".join(f"- {a}" for a in action_items)
        filename = f"{date}-{title[:50].replace(' ', '-')}.md"
        (memory_dir / filename).write_text(content)
        saved += 1
    return saved

if __name__ == "__main__":
    print("Testing Fireflies connection...")
    transcripts = get_recent_transcripts(3)
    print(format_transcripts(transcripts))
