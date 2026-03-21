#!/usr/bin/env python3
"""
Shared transcript formatting module — Peak 10 meeting notes format.
Used by both fathom_agent.py and fireflies_agent.py.
"""
import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone

AUDIT_LOG = "/opt/clawbot/logs/audit.log"
OUTPUT_DIR = Path("/opt/clawbot/transcripts")


def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


def structure_with_llm(summary_text, action_items_raw, title, attendees_str=""):
    """Use LLM to parse summary into Peak 10 structured sections."""
    try:
        from llm_client import chat_with_fallback

        # Normalize action items to a text block
        if isinstance(action_items_raw, list):
            actions_text = "\n".join(
                f"- {item.get('description', item) if isinstance(item, dict) else item}"
                for item in action_items_raw if item
            )
        else:
            actions_text = str(action_items_raw or "")

        prompt = f"""You are formatting meeting notes for Peak 10 Group, a real estate company.

Meeting Title: {title}
Attendees: {attendees_str}

Meeting Summary:
{summary_text}

Action Items:
{actions_text}

Return a JSON object with exactly these fields:
- "sections": array of objects, each with:
    - "title": section name in format "1. SECTION NAME" (ALL CAPS, numbered). Use 2-5 sections based on content. Common sections: FINANCIAL REVIEW, LEASING & OCCUPANCY, OPERATIONS & MAINTENANCE, STAFFING, CAPITAL PROJECTS, KEY DECISIONS & WINS. Only include sections with actual content.
    - "bullets": array of concise bullet point strings (no bullet characters)
- "action_items": array of objects with:
    - "action": description of the action item
    - "owner": person responsible (first and last name, or "TBD")
    - "due": timeframe such as "This week", "ASAP", "April", "Ongoing", or "TBD"
- "prepared_by": name of the meeting organizer/host (default "Nate Fisher" if unclear)

Return ONLY valid JSON. No markdown, no code blocks, no extra text."""

        response = chat_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2500,
            temperature=0.3
        )

        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"```[a-z]*\n?", "", response).strip().rstrip("```").strip()

        return json.loads(response)

    except Exception as e:
        audit("ERROR", "transcript-formatter", f"LLM structuring failed: {e}")
        return None


def save_formatted_docx(title, date_str, attendees_str, summary_text,
                        action_items_raw, utterances, source_tag):
    """
    Create a Peak 10 format meeting notes .docx via Node.js docx-js.
    Uploads to OneDrive 'Meeting Notes' folder. Returns the OneDrive web URL
    (or local path as fallback if OneDrive upload fails).
    """
    import json
    import subprocess
    import tempfile

    # Step 1: LLM-structure the content
    structured = structure_with_llm(summary_text, action_items_raw, title, attendees_str)

    sections = []
    action_items = []
    prepared_by = "Nate Fisher"

    if structured:
        sections = structured.get("sections", [])
        action_items = structured.get("action_items", [])
        prepared_by = structured.get("prepared_by") or "Nate Fisher"
    else:
        if summary_text:
            sections = [{"title": "MEETING SUMMARY", "bullets": [summary_text[:500]]}]
        if isinstance(action_items_raw, list):
            for item in action_items_raw:
                if isinstance(item, dict):
                    action_items.append({"action": item.get("description", ""), "owner": "TBD", "due": "TBD"})
                elif isinstance(item, str) and item.strip():
                    action_items.append({"action": item.strip(), "owner": "TBD", "due": "TBD"})

    # Build transcript utterances list
    transcript = []
    for u in (utterances or []):
        speaker = u.get("speaker") or u.get("speaker_name") or "Unknown"
        text = (u.get("text") or u.get("content") or "").strip()
        if text:
            transcript.append({"speaker": speaker, "text": text})

    # Step 2: Write JSON data and call Node.js script
    data = {
        "title": title,
        "date_str": date_str,
        "attendees_str": attendees_str or "See recording",
        "prepared_by": prepared_by,
        "note": "",
        "sections": sections,
        "action_items": action_items,
        "transcript": transcript,
    }

    safe_title = re.sub(r"[^\w\s-]", "", title)[:50].strip().replace(" ", "-")
    filename = f"{date_str}-{safe_title}.docx"

    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = Path(tmpdir) / "data.json"
        output_path = Path(tmpdir) / filename
        data_path.write_text(json.dumps(data, ensure_ascii=False))

        node_script = Path("/opt/clawbot/app/generate_meeting_notes.js")
        result = subprocess.run(
            ["node", str(node_script), str(data_path), str(output_path)],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0 or not output_path.exists():
            audit("ERROR", source_tag, f"Node.js docx failed: {result.stderr[:300]}")
            return None, None, filename

        # Step 3: Read bytes before temp dir is cleaned up
        file_bytes = output_path.read_bytes()

    from onedrive_agent import save_binary_file
    web_url, err = save_binary_file(filename, file_bytes, folder="Meeting Notes")
    if err:
        audit("ERROR", source_tag, f"OneDrive upload failed: {err}")
        return None, file_bytes, filename

    audit("INFO", source_tag, f"Uploaded to OneDrive Meeting Notes: {filename}")
    return web_url, file_bytes, filename
