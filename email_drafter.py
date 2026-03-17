import os
import time
import requests
import msal
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import OpenAI

from vault_secrets import get_secrets
from llm_client import chat_with_fallback
get_secrets()
from dotenv import load_dotenv
load_dotenv("/opt/clawbot/app/.env")  # fallback

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
MS_USER_EMAIL = os.getenv("MS_USER_EMAIL", "nfisher@peak10group.com")
CUTOFF_DATE = "2026-03-08T00:00:00Z"
AUDIT_LOG = "/opt/clawbot/logs/audit.log"

SIGNATURE = "\n\nThanks,\n\nNathan D. Fisher\nPeak 10 Group\n970-315-2244 (ofc)\nwww.peak10group.com"

client = OpenAI(api_key=OPENAI_API_KEY)

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass
    print(line.strip())

def strip_html(html):
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    html = re.sub(r'&lt;', '<', html)
    html = re.sub(r'&gt;', '>', html)
    html = re.sub(r'\s+', ' ', html)
    return html.strip()

def get_graph_token():
    app = msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority="https://login.microsoftonline.com/" + AZURE_TENANT_ID,
        client_credential=AZURE_CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    return result.get("access_token")

def get_flagged_emails(token):
    headers = {"Authorization": "Bearer " + token}
    url = ("https://graph.microsoft.com/v1.0/users/" + MS_USER_EMAIL +
           "/messages?$filter=flag/flagStatus eq 'flagged' and receivedDateTime ge " + CUTOFF_DATE +
           "&$select=id,subject,from,body,receivedDateTime,toRecipients,ccRecipients&$top=10")
    response = requests.get(url, headers=headers).json()
    return response.get("value", [])

def draft_reply(email):
    subject = email.get("subject", "")
    sender = email.get("from", {}).get("emailAddress", {}).get("address", "")
    sender_name = email.get("from", {}).get("emailAddress", {}).get("name", "")
    raw_body = email.get("body", {}).get("content", "")
    content_type = email.get("body", {}).get("contentType", "text")
    if content_type.lower() == "html":
        clean_body = strip_html(raw_body)
    else:
        clean_body = raw_body
    clean_body = clean_body[:2000]
    prompt = ("You are ClawBot, the Chief of Staff AI for Nathan Fisher. "
              "Draft a professional reply to this email. Do not include a signature.\n\n"
              "FROM: " + sender_name + " <" + sender + ">\n"
              "SUBJECT: " + subject + "\n"
              "BODY:\n" + clean_body + "\n\n"
              "Write a concise, professional reply on behalf of Nathan Fisher. Do not include a signature.")
    reply_body = chat_with_fallback([{"role": "user", "content": prompt}])
    signature_html = "<br><br>Thanks,<br><br>Nathan D. Fisher<br>Peak 10 Group<br>970-315-2244 (ofc)<br>www.peak10group.com"
    original_thread_html = (
        "<br><br><hr style='border:1px solid #ccc;'>"
        "<b>From:</b> " + sender_name + " &lt;" + sender + "&gt;<br>"
        "<b>Subject:</b> " + subject + "<br><br>"
        "<div style='color:#555;'>" + clean_body.replace("\n", "<br>") + "</div>"
    )
    full_body = "<div>" + reply_body.replace("\n", "<br>") + signature_html + original_thread_html + "</div>"
    return full_body

def save_draft(token, email, draft_body):
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    sender = email.get("from", {}).get("emailAddress", {})
    subject = "Re: " + email.get("subject", "")
    # Reply-all: original sender in To, all original To/CC recipients in CC
    original_to = email.get("toRecipients", [])
    original_cc = email.get("ccRecipients", [])
    cc_recipients = [r for r in original_to + original_cc
                     if r.get("emailAddress", {}).get("address", "").lower() != MS_USER_EMAIL.lower()]
    payload = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": draft_body},
        "toRecipients": [{"emailAddress": sender}],
        "ccRecipients": cc_recipients
    }
    url = "https://graph.microsoft.com/v1.0/users/" + MS_USER_EMAIL + "/messages"
    response = requests.post(url, headers=headers, json=payload)
    return response.status_code

def unflag_email(token, email_id):
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    url = "https://graph.microsoft.com/v1.0/users/" + MS_USER_EMAIL + "/messages/" + email_id
    payload = {"flag": {"flagStatus": "complete"}}
    requests.patch(url, headers=headers, json=payload)

def main():
    audit("INFO", "email-drafter", "Service started")
    processed = set()
    while True:
        try:
            token = get_graph_token()
            flagged = get_flagged_emails(token)
            audit("INFO", "email-drafter", f"Checked flagged emails — found {len(flagged)}")
            for email in flagged:
                email_id = email["id"]
                received = email.get("receivedDateTime", "")
                if received and received < CUTOFF_DATE:
                    audit("SKIP", "email-drafter", f"Skipping old email: {email.get('subject','')}")
                    continue
                if email_id in processed:
                    continue
                subject = email.get("subject", "No subject")
                audit("INFO", "email-drafter", f"Processing: {subject}")
                draft = draft_reply(email)
                status = save_draft(token, email, draft)
                if status in [200, 201]:
                    audit("SUCCESS", "email-drafter", f"Draft saved: {subject}")
                    unflag_email(token, email_id)
                    processed.add(email_id)
                else:
                    audit("ERROR", "email-drafter", f"Failed to save draft (status {status}): {subject}")
        except Exception as e:
            audit("ERROR", "email-drafter", f"Exception: {str(e)}")
        time.sleep(300)

if __name__ == "__main__":
    main()
