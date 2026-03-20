#!/usr/bin/env python3
"""
Email Listener — Polls MrSoulCFO@gmail.com for tasks to complete automatically.

Every email sent to Mr Soul is treated as a task. He reads it, completes it,
and replies with the result.

Setup:
  1. Enable IMAP in Gmail → Settings → See all settings → Forwarding and POP/IMAP
  2. Credentials are stored in .env

Usage:
  python3 email_listener.py
"""

import imaplib
import smtplib
import email
import anyio
import os
import sys
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from agent import MR_SOUL_CFO, CFO_SYSTEM_PROMPT
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

# ── CONFIG — load from .env if present ────────────────────────────────────────
def load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                # Use os.environ[] (not setdefault) so .env always wins
                os.environ[k.strip()] = v.strip()

load_env()

GMAIL_ADDRESS      = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

OUTLOOK_ADDRESS    = os.environ.get("OUTLOOK_ADDRESS", "")
OUTLOOK_PASSWORD   = os.environ.get("OUTLOOK_PASSWORD", "")
OUTLOOK_IMAP_HOST  = os.environ.get("OUTLOOK_IMAP_HOST", "outlook.office365.com")
OUTLOOK_SMTP_HOST  = os.environ.get("OUTLOOK_SMTP_HOST", "smtp.office365.com")

POLL_INTERVAL_SEC  = 60               # Check every 60 seconds
CFO_WORKING_DIR    = str(Path(__file__).parent)
ALWAYS_CC          = "nfisher@peak10group.com"  # Always included on every reply


# ── EMAIL HELPERS ──────────────────────────────────────────────────────────────
def decode_str(value) -> str:
    """Decode email header value."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def get_body(msg) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")
    return ""


def save_attachments(msg, uid: bytes) -> list[Path]:
    """Save any file attachments from the email to the inbox/ folder."""
    inbox_dir = Path(CFO_WORKING_DIR) / "inbox"
    inbox_dir.mkdir(exist_ok=True)
    saved = []
    for part in msg.walk():
        cd = str(part.get("Content-Disposition", ""))
        filename = part.get_filename()
        if filename and ("attachment" in cd or "inline" in cd):
            filename = decode_str(filename).strip()
            # Use clean original filename — overwrite if re-sent
            dest = inbox_dir / filename
            dest.write_bytes(part.get_payload(decode=True))
            saved.append(dest)
            print(f"  Saved attachment: {filename} → {dest}")
    return saved


def fetch_cfo_emails(imap: imaplib.IMAP4_SSL, account_label: str) -> list[dict]:
    """Fetch all unread emails — every email to Mr Soul is a task."""
    imap.select("INBOX")
    _, data = imap.search(None, "UNSEEN")
    uids = data[0].split()
    emails = []
    for uid in uids:
        _, msg_data = imap.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        subject = decode_str(msg.get("Subject", "")).strip()
        sender  = decode_str(msg.get("From", ""))
        # Collect all CC recipients from the original email
        cc_raw  = decode_str(msg.get("CC", ""))
        to_raw  = decode_str(msg.get("To", ""))
        # Build reply-all CC list: original TO + CC, minus Mr Soul's own address, plus Nate
        all_recipients = set()
        for addr_field in [cc_raw, to_raw]:
            for part in addr_field.split(","):
                part = part.strip()
                if part and GMAIL_ADDRESS.lower() not in part.lower():
                    all_recipients.add(part)
        all_recipients.add(ALWAYS_CC)
        reply_cc = ", ".join(sorted(all_recipients - {sender}))

        body        = get_body(msg).strip()
        attachments = save_attachments(msg, uid)

        task = f"{subject}\n\n{body}".strip() if body else subject

        # Always include inbox files — whether attached to this email or previously saved
        inbox_dir = Path(CFO_WORKING_DIR) / "inbox"
        inbox_files = sorted(inbox_dir.glob("*")) if inbox_dir.exists() else []
        all_files = list({p: None for p in list(attachments) + inbox_files}.keys())  # dedupe, preserve order

        if all_files:
            paths = "\n".join(f"  - {p.resolve()}" for p in all_files)
            task += f"""

⚠️ MANDATORY FIRST STEP — READ ALL ATTACHED FILES BEFORE DOING ANYTHING ELSE:
{paths}

You MUST open and read every file listed above using the Read or Bash tool before starting your analysis.
Do NOT skip this step. Do NOT summarize without reading. The data in these files IS your source material."""

        emails.append({
            "uid":      uid,
            "msg_id":   msg.get("Message-ID", ""),
            "subject":  subject,
            "sender":   sender,
            "reply_cc": reply_cc,
            "task":     task,
            "account":  account_label,
        })
        # Mark as read so it's not processed again
        imap.store(uid, "+FLAGS", "\\Seen")
    return emails


def send_reply(smtp_host: str, smtp_port: int, address: str, password: str,
               to: str, subject: str, body: str, in_reply_to: str = "",
               cc: str = "", attachments: list[Path] = []) -> None:
    """Send an email reply via SMTP, optionally with CC and file attachments."""
    msg = MIMEMultipart("mixed")
    msg["From"]    = address
    msg["To"]      = to
    if cc:
        msg["CC"] = cc
    msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"]  = in_reply_to

    msg.attach(MIMEText(body, "plain"))

    for path in attachments:
        mime_type, _ = mimetypes.guess_type(str(path))
        main_type, sub_type = (mime_type or "application/octet-stream").split("/", 1)
        with open(path, "rb") as f:
            part = MIMEBase(main_type, sub_type)
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=path.name)
        msg.attach(part)

    all_to = [to] + [a.strip() for a in cc.split(",") if a.strip()]
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(address, password)
        server.sendmail(address, all_to, msg.as_string())


# ── MR SOUL RUNNER ─────────────────────────────────────────────────────────────
async def run_mr_soul(task: str) -> tuple[str, list[Path]]:
    """Run Mr Soul CFO. Returns (reply_text, list_of_output_files_to_attach)."""
    # Snapshot files + modification times before task runs
    def snapshot():
        return {p: p.stat().st_mtime for p in Path(CFO_WORKING_DIR).rglob("*")
                if p.is_file() and not p.name.startswith(".")}

    before = snapshot()
    start_time = datetime.now().timestamp()

    result_text = ""
    async for msg in query(
        prompt=task,
        options=ClaudeAgentOptions(
            cwd=CFO_WORKING_DIR,
            system_prompt=CFO_SYSTEM_PROMPT,
            model="claude-opus-4-6",
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch"],
            permission_mode="bypassPermissions",
            max_turns=40,
        ),
    ):
        if isinstance(msg, ResultMessage):
            result_text = msg.result

    # Collect output files — only from ./output/, only supported formats
    output_dir = Path(CFO_WORKING_DIR) / "output"
    output_files = sorted(
        p for p in output_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in (".docx", ".xlsx", ".pptx", ".pdf", ".csv")
        and p.stat().st_mtime > start_time  # only files created/updated this run
    ) if output_dir.exists() else []

    return result_text or "(Task completed — no text output returned.)", output_files


# ── ACCOUNT POLLING ────────────────────────────────────────────────────────────
async def poll_account(
    imap_host: str, address: str, password: str,
    smtp_host: str, smtp_port: int, label: str
) -> int:
    """Poll one email account. Returns number of tasks processed."""
    processed = 0
    try:
        imap = imaplib.IMAP4_SSL(imap_host)
        imap.login(address, password)

        emails = fetch_cfo_emails(imap, label)
        imap.logout()

        for e in emails:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [{label}] Task from {e['sender']}: {e['task'][:60]}...")
            try:
                result, new_files = await run_mr_soul(e["task"])
            except Exception as agent_err:
                print(f"[{ts}] [{label}] Agent error: {agent_err}")
                result = f"Mr Soul CFO encountered an error while processing your request:\n\n{agent_err}\n\nPlease try again or contact support."
                new_files = []

            if new_files:
                print(f"[{ts}] [{label}] Attaching {len(new_files)} file(s): {[f.name for f in new_files]}")

            send_reply(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                address=address,
                password=password,
                to=e["sender"],
                subject=e["subject"],
                body=result,
                in_reply_to=e["msg_id"],
                cc=e["reply_cc"],
                attachments=new_files,
            )
            print(f"[{ts}] [{label}] Reply sent.")
            processed += 1

    except imaplib.IMAP4.error as e:
        print(f"[{label}] IMAP error: {e}")
    except Exception as e:
        print(f"[{label}] Error: {e}")

    return processed


# ── MAIN LOOP ──────────────────────────────────────────────────────────────────
async def main() -> None:
    accounts = []

    if GMAIL_ADDRESS and GMAIL_APP_PASSWORD:
        accounts.append({
            "imap_host": "imap.gmail.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "address":   GMAIL_ADDRESS,
            "password":  GMAIL_APP_PASSWORD,
            "label":     "Gmail",
        })
    else:
        print("Gmail not configured — set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env")

    if OUTLOOK_ADDRESS and OUTLOOK_PASSWORD:
        accounts.append({
            "imap_host": OUTLOOK_IMAP_HOST,
            "smtp_host": OUTLOOK_SMTP_HOST,
            "smtp_port": 587,
            "address":   OUTLOOK_ADDRESS,
            "password":  OUTLOOK_PASSWORD,
            "label":     "Outlook",
        })
    else:
        print("Outlook not configured — set OUTLOOK_ADDRESS and OUTLOOK_PASSWORD in .env")

    if not accounts:
        print("\nNo accounts configured. Create a .env file — see .env.example")
        return

    labels = " + ".join(a["label"] for a in accounts)
    print(f"\n📬 Mr Soul CFO — Email Listener")
    print(f"   Watching: {labels}")
    print(f"   Polling every {POLL_INTERVAL_SEC}s — every email is a task\n")

    while True:
        for acct in accounts:
            await poll_account(**acct)
        await anyio.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    anyio.run(main)
