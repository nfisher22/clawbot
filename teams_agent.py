import os
import requests
import msal
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv("/opt/clawbot/app/.env")

AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
MS_USER_EMAIL = os.getenv("MS_USER_EMAIL", "nfisher@peak10group.com")
AUDIT_LOG = "/opt/clawbot/logs/audit.log"

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass

def get_graph_token():
    app = msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority="https://login.microsoftonline.com/" + AZURE_TENANT_ID,
        client_credential=AZURE_CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    return result.get("access_token")

def get_my_chats(count=5):
    token = get_graph_token()
    if not token:
        return "Could not authenticate with Microsoft."
    headers = {"Authorization": "Bearer " + token}
    url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/chats?$top={count}&$select=id,topic,chatType,lastUpdatedDateTime"
    response = requests.get(url, headers=headers).json()
    chats = response.get("value", [])
    if not chats:
        return "No chats found."
    output = []
    for c in chats:
        topic = c.get("topic") or "Direct Message"
        chat_type = c.get("chatType", "")
        updated = c.get("lastUpdatedDateTime", "")[:10]
        output.append(f"💬 {topic} | Type: {chat_type} | Updated: {updated} | ID: {c['id']}")
    audit("INFO", "teams-agent", f"Listed {len(chats)} chats")
    return "\n".join(output)

def get_chat_messages(chat_id, count=5):
    token = get_graph_token()
    if not token:
        return "Could not authenticate with Microsoft."
    headers = {"Authorization": "Bearer " + token}
    url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/chats/{chat_id}/messages?$top={count}"
    response = requests.get(url, headers=headers).json()
    messages = response.get("value", [])
    if not messages:
        return "No messages found."
    output = []
    for m in messages:
        sender = m.get("from", {}).get("user", {}).get("displayName", "Unknown")
        body = m.get("body", {}).get("content", "")
        # Strip HTML
        import re
        body = re.sub(r'<[^>]+>', ' ', body).strip()[:200]
        created = m.get("createdDateTime", "")[:16].replace("T", " ")
        if body:
            output.append(f"👤 {sender} [{created}]:\n{body}")
    audit("INFO", "teams-agent", f"Retrieved {len(messages)} messages")
    return "\n---\n".join(output)

def get_teams_list():
    token = get_graph_token()
    if not token:
        return "Could not authenticate with Microsoft."
    headers = {"Authorization": "Bearer " + token}
    url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/joinedTeams?$select=id,displayName,description"
    response = requests.get(url, headers=headers).json()
    teams = response.get("value", [])
    if not teams:
        return "No teams found."
    output = []
    for t in teams:
        name = t.get("displayName", "")
        desc = t.get("description", "")[:100]
        output.append(f"👥 {name}\n   {desc}")
    audit("INFO", "teams-agent", f"Listed {len(teams)} teams")
    return "\n---\n".join(output)

def get_channel_messages(team_id, channel_id, count=5):
    token = get_graph_token()
    if not token:
        return "Could not authenticate with Microsoft."
    headers = {"Authorization": "Bearer " + token}
    url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/messages?$top={count}"
    response = requests.get(url, headers=headers).json()
    messages = response.get("value", [])
    if not messages:
        return "No messages found."
    output = []
    for m in messages:
        import re
        sender = m.get("from", {}).get("user", {}).get("displayName", "Unknown")
        body = re.sub(r'<[^>]+>', ' ', m.get("body", {}).get("content", "")).strip()[:200]
        created = m.get("createdDateTime", "")[:16].replace("T", " ")
        if body:
            output.append(f"👤 {sender} [{created}]:\n{body}")
    audit("INFO", "teams-agent", f"Retrieved channel messages")
    return "\n---\n".join(output)

if __name__ == "__main__":
    print("Testing Teams connection...")
    print("Your Teams:")
    print(get_teams_list())
    print("\nYour Chats:")
    print(get_my_chats())
