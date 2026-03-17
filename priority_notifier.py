import os
import time
import requests
import msal
from datetime import datetime, timezone
from dotenv import load_dotenv

from vault_secrets import get_secrets
get_secrets()
from dotenv import load_dotenv
load_dotenv("/opt/clawbot/app/.env")  # fallback

AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
MS_USER_EMAIL = os.getenv("MS_USER_EMAIL", "nfisher@peak10group.com")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AUDIT_LOG = "/opt/clawbot/logs/audit.log"
CUTOFF_DATE = "2026-03-08T00:00:00Z"

URGENT_KEYWORDS = ["urgent", "asap", "emergency", "critical", "immediate", "action required", "time sensitive"]
HIGH_PRIORITY_SENDERS = ["nfisher@peak10group.com"]

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass
    print(line.strip())

def get_graph_token():
    app = msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority="https://login.microsoftonline.com/" + AZURE_TENANT_ID,
        client_credential=AZURE_CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    return result.get("access_token")

def get_recent_emails(token):
    headers = {"Authorization": "Bearer " + token}
    url = ("https://graph.microsoft.com/v1.0/users/" + MS_USER_EMAIL +
           "/messages?$filter=receivedDateTime ge " + CUTOFF_DATE +
           "&$select=id,subject,from,receivedDateTime,bodyPreview,isRead&$top=20&$orderby=receivedDateTime desc")
    response = requests.get(url, headers=headers).json()
    return response.get("value", [])

def get_priority(email):
    subject = email.get("subject", "").lower()
    sender = email.get("from", {}).get("emailAddress", {}).get("address", "").lower()
    if any(k in subject for k in URGENT_KEYWORDS):
        return "URGENT"
    if sender in [s.lower() for s in HIGH_PRIORITY_SENDERS]:
        return "HIGH"
    return "NORMAL"

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        audit("ERROR", "priority-notifier", "Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    r = requests.post(url, json=payload)
    return r.status_code == 200

def main():
    audit("INFO", "priority-notifier", "Service started")
    notified = set()
    while True:
        try:
            token = get_graph_token()
            emails = get_recent_emails(token)
            for email in emails:
                email_id = email["id"]
                if email_id in notified:
                    continue
                priority = get_priority(email)
                if priority in ["URGENT", "HIGH"]:
                    subject = email.get("subject", "No subject")
                    sender_name = email.get("from", {}).get("emailAddress", {}).get("name", "")
                    sender_addr = email.get("from", {}).get("emailAddress", {}).get("address", "")
                    preview = email.get("bodyPreview", "")[:150]
                    received = email.get("receivedDateTime", "")[:16].replace("T", " ")
                    emoji = "🔴" if priority == "URGENT" else "🟡"
                    message = (f"{emoji} *{priority} EMAIL*\n\n"
                               f"*From:* {sender_name} <{sender_addr}>\n"
                               f"*Subject:* {subject}\n"
                               f"*Received:* {received}\n"
                               f"*Preview:* {preview}")
                    if send_telegram(message):
                        audit("SUCCESS", "priority-notifier", f"{priority} email notified: {subject}")
                        notified.add(email_id)
                    else:
                        audit("ERROR", "priority-notifier", f"Failed to send Telegram notification: {subject}")
        except Exception as e:
            audit("ERROR", "priority-notifier", f"Exception: {str(e)}")
        time.sleep(120)

if __name__ == "__main__":
    main()
