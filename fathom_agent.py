#!/usr/bin/env python3
"""
Hatfield Fathom Video Agent — pulls meeting summaries and transcripts via REST API
Base URL: https://api.fathom.ai/external/v1
Auth: X-Api-Key header
"""
import os
import re
import requests
from datetime import datetime, timezone
from pathlib import Path
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

def get_meeting_detail(meeting_id):
    """Fetch full meeting detail including transcript."""
    try:
        response = requests.get(
            f"{FATHOM_BASE}/meetings/{meeting_id}",
            headers=get_headers(),
            params={"include_transcript": True},
            timeout=20
        )
        if response.status_code == 200:
            return response.json()
        else:
            audit("ERROR", "fathom-agent", f"Detail fetch failed: {response.status_code} — {response.text[:200]}")
            return {}
    except Exception as e:
        audit("ERROR", "fathom-agent", f"Exception in get_meeting_detail: {e}")
        return {}

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
                desc = item.get("description", "") if isinstance(item, dict) else str(item)
                if desc:
                    lines.append(f"   • {desc[:100]}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")
    return "\n".join(lines)

def save_meetings_to_memory(meetings):
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
                desc = item.get("description", "") if isinstance(item, dict) else str(item)
                content += f"- {desc}\n"
        filename = f"{date}-{title[:50].replace(' ', '-')}.md"
        (memory_dir / filename).write_text(content)
        saved += 1
    return saved

def save_transcript_to_onedrive(meeting):
    """Save verbatim transcript (utterances only) to OneDrive/Meetings/ as plain text."""
    from onedrive_agent import save_file
    title = (meeting.get("title") or meeting.get("meeting_title") or "Untitled").replace("/", "-")
    raw_date = meeting.get("created_at") or meeting.get("scheduled_start_time") or ""
    date_str = raw_date[:10] if raw_date else "unknown"
    utterances = meeting.get("transcript") or meeting.get("utterances") or []

    lines = []
    for u in utterances:
        speaker = u.get("speaker") or u.get("speaker_name") or "Unknown"
        text = (u.get("text") or u.get("content") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")

    content = "\n\n".join(lines) if lines else "(No transcript available)"
    safe_title = title[:50].replace(" ", "-")
    filename = f"{date_str}-{safe_title}.txt"
    result = save_file(filename, content, folder="Meetings")
    audit("INFO", "fathom-agent", f"Verbatim transcript saved to OneDrive/Meetings: {filename}")
    return result

def save_transcript_docx(meeting):
    """Save Peak 10 format meeting notes .docx. Returns file path."""
    from transcript_formatter import save_formatted_docx

    title = meeting.get("title") or meeting.get("meeting_title") or "Untitled"
    raw_date = meeting.get("created_at") or meeting.get("scheduled_start_time") or ""
    date_str = raw_date[:10] if raw_date else "unknown"

    summary = meeting.get("default_summary", {}) or {}
    summary_text = summary.get("markdown_formatted", "")
    action_items = meeting.get("action_items", []) or []

    # Build attendees string from invitees list if available
    invitees = meeting.get("calendar_invitees", []) or []
    if invitees:
        attendees_str = ", ".join(
            i.get("name") or i.get("email", "") for i in invitees if i
        )
    else:
        attendees_str = meeting.get("organizer_email", "")

    utterances = meeting.get("transcript") or meeting.get("utterances") or []

    return save_formatted_docx(
        title=title,
        date_str=date_str,
        attendees_str=attendees_str,
        summary_text=summary_text,
        action_items_raw=action_items,
        utterances=utterances,
        source_tag="fathom-agent"
    )

def send_transcript_email(file_bytes, filename, meeting_title, date_str):
    """Email formatted meeting notes .docx as attachment via Microsoft Graph API."""
    import base64
    import msal

    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    MS_USER_EMAIL = os.getenv("MS_USER_EMAIL", "nfisher@peak10group.com")
    TO_EMAIL = "nfisher@peak10group.com"

    if not all([AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET]):
        audit("ERROR", "fathom-agent", "Azure credentials missing — skipping email")
        return "⚠️ Email skipped: Azure credentials not configured"

    if not file_bytes:
        return "⚠️ Email skipped: no file bytes available"

    try:
        app = msal.ConfidentialClientApplication(
            AZURE_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{AZURE_TENANT_ID}",
            client_credential=AZURE_CLIENT_SECRET
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        token = result.get("access_token")
        if not token:
            raise Exception(f"Token acquisition failed: {result.get('error_description')}")

        attachment_b64 = base64.b64encode(file_bytes).decode("utf-8")
        payload = {
            "message": {
                "subject": f"Meeting Notes: {meeting_title} ({date_str})",
                "body": {
                    "contentType": "Text",
                    "content": f"Meeting notes attached for:\n\n{meeting_title}\nDate: {date_str}"
                },
                "toRecipients": [{"emailAddress": {"address": TO_EMAIL}}],
                "attachments": [{
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "contentBytes": attachment_b64
                }]
            }
        }

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/sendMail",
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code == 202:
            audit("SUCCESS", "fathom-agent", f"Email sent: {meeting_title}")
            return f"✅ Emailed to {TO_EMAIL}"
        else:
            raise Exception(f"Graph API error {response.status_code}: {response.text[:200]}")

    except Exception as e:
        audit("ERROR", "fathom-agent", f"Email failed: {e}")
        return f"❌ Email failed: {e}"

def run_fathom_pipeline(limit=5):
    """Full pipeline: fetch meetings → fetch detail + transcript → save docx → email each one."""
    meetings = get_recent_meetings(limit)
    if not meetings:
        return "No meetings found in Fathom."

    results = []
    for m in meetings:
        title = m.get("title") or m.get("meeting_title") or "Untitled"
        raw_date = m.get("created_at") or m.get("scheduled_start_time") or ""
        date_str = raw_date[:10] if raw_date else "unknown"
        meeting_id = m.get("id") or m.get("meeting_id") or ""

        # Fetch full detail with transcript
        detail = get_meeting_detail(meeting_id) if meeting_id else {}
        full_meeting = {**m, **(detail if detail else {})}

        # Save formatted notes docx to OneDrive/Meeting Notes
        onedrive_url, docx_bytes, docx_filename = save_transcript_docx(full_meeting)

        # Save verbatim transcript to OneDrive/Meetings
        save_transcript_to_onedrive(full_meeting)

        # Save to local memory
        save_meetings_to_memory([full_meeting])

        # Email formatted notes as attachment
        email_result = send_transcript_email(docx_bytes, docx_filename, title, date_str)

        saved_loc = onedrive_url or "OneDrive upload failed"
        results.append(f"📄 *{title}* ({date_str})\n   Saved: {saved_loc}\n   {email_result}")

    return "\n\n".join(results)

if __name__ == "__main__":
    print("Testing Fathom pipeline...")
    print(run_fathom_pipeline(3))
