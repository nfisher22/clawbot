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
            meeting_attendees {
                displayName
                email
            }
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

def save_transcript_to_onedrive(transcript):
    """Save verbatim transcript (sentences only) to OneDrive/Meetings/ as plain text."""
    from onedrive_agent import save_file
    title = (transcript.get("title", "Untitled")).replace("/", "-")
    raw_date = transcript.get("date", "")
    try:
        if isinstance(raw_date, (int, float)):
            date_str = datetime.fromtimestamp(raw_date).strftime("%Y-%m-%d")
        else:
            date_str = str(raw_date)[:10]
    except Exception:
        date_str = str(raw_date)[:10]
    sentences = transcript.get("sentences", []) or []

    lines = []
    for s in sentences:
        speaker = s.get("speaker_name", "Unknown")
        text = (s.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")

    content = "\n\n".join(lines) if lines else "(No transcript available)"
    safe_title = title[:50].replace(" ", "-")
    filename = f"{date_str}-{safe_title}.txt"
    result = save_file(filename, content, folder="Meetings")
    audit("INFO", "fireflies-agent", f"Verbatim transcript saved to OneDrive/Meetings: {filename}")
    return result

def save_transcript_docx(transcript):
    """Save Peak 10 format meeting notes .docx. Returns the file path."""
    from transcript_formatter import save_formatted_docx

    title = transcript.get("title", "Untitled")
    raw_date = transcript.get("date", "")
    try:
        date_str = datetime.fromtimestamp(raw_date).strftime("%Y-%m-%d") if isinstance(raw_date, (int, float)) else str(raw_date)[:10]
    except Exception:
        date_str = str(raw_date)[:10]

    summary = transcript.get("summary", {}) or {}
    summary_text = summary.get("overview", "")
    action_items = summary.get("action_items", []) or []

    # Build attendees string
    attendees = transcript.get("meeting_attendees", []) or []
    if attendees:
        attendees_str = ", ".join(
            a.get("displayName") or a.get("email", "") for a in attendees if a
        )
    else:
        attendees_str = transcript.get("organizer_email", "")

    # Fireflies uses 'sentences' for transcript; map to common format
    sentences = transcript.get("sentences", []) or []
    utterances = [{"speaker": s.get("speaker_name", "Unknown"), "text": s.get("text", "")} for s in sentences]

    return save_formatted_docx(
        title=title,
        date_str=date_str,
        attendees_str=attendees_str,
        summary_text=summary_text,
        action_items_raw=action_items,
        utterances=utterances,
        source_tag="fireflies-agent"
    )


def send_transcript_email(file_bytes, filename, transcript_title, date_str):
    """Email formatted meeting notes .docx as attachment via Microsoft Graph API."""
    import base64
    import msal

    AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
    AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    MS_USER_EMAIL = os.getenv("MS_USER_EMAIL", "nfisher@peak10group.com")
    TO_EMAIL = "nfisher@peak10group.com"

    if not all([AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET]):
        audit("ERROR", "fireflies-agent", "Azure credentials missing — skipping email")
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
                "subject": f"Meeting Notes: {transcript_title} ({date_str})",
                "body": {
                    "contentType": "Text",
                    "content": f"Meeting notes attached for:\n\n{transcript_title}\nDate: {date_str}"
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
            audit("SUCCESS", "fireflies-agent", f"Email sent: {transcript_title}")
            return f"✅ Emailed to {TO_EMAIL}"
        else:
            raise Exception(f"Graph API error {response.status_code}: {response.text[:200]}")

    except Exception as e:
        audit("ERROR", "fireflies-agent", f"Email failed: {e}")
        return f"❌ Email failed: {e}"


def run_transcript_pipeline(limit=5):
    """Full pipeline: fetch transcripts → save docx → email each one."""
    transcripts = get_recent_transcripts(limit)
    if not transcripts:
        return "No transcripts found in Fireflies."

    results = []
    for t in transcripts:
        title = t.get("title", "Untitled")
        raw_date = t.get("date", "")
        try:
            date_str = datetime.fromtimestamp(raw_date).strftime("%Y-%m-%d") if isinstance(raw_date, (int, float)) else str(raw_date)[:10]
        except Exception:
            date_str = str(raw_date)[:10]

        # Fetch full transcript with sentences
        detail = get_transcript_detail(t["id"])
        full_transcript = {**t, **(detail if detail and not detail.get("error") else {})}

        # Save formatted notes docx to OneDrive/Meeting Notes
        onedrive_url, docx_bytes, docx_filename = save_transcript_docx(full_transcript)

        # Save verbatim transcript to OneDrive/Meetings
        save_transcript_to_onedrive(full_transcript)

        # Save to local memory
        save_transcripts_to_memory([full_transcript])

        # Email formatted notes as attachment
        email_result = send_transcript_email(docx_bytes, docx_filename, title, date_str)

        saved_loc = onedrive_url or "OneDrive upload failed"
        results.append(f"📄 *{title}* ({date_str})\n   Saved: {saved_loc}\n   {email_result}")

    return "\n\n".join(results)


if __name__ == "__main__":
    print("Testing Fireflies pipeline...")
    print(run_transcript_pipeline(3))
