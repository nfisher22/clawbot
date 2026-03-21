import os
import requests
import msal
from datetime import datetime, timezone
from dotenv import load_dotenv

from vault_secrets import get_secrets
get_secrets()

AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
MS_USER_EMAIL = os.getenv("MS_USER_EMAIL") or os.getenv("MS_EMAIL", "nfisher@peak10group.com")
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

def list_files(folder="root", count=10):
    token = get_graph_token()
    if not token:
        return "Could not authenticate with Microsoft."
    headers = {"Authorization": "Bearer " + token}
    if folder == "root":
        url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/drive/root/children?$top={count}&$select=name,size,lastModifiedDateTime,webUrl"
    else:
        url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/drive/root:/{folder}:/children?$top={count}&$select=name,size,lastModifiedDateTime,webUrl"
    response = requests.get(url, headers=headers).json()
    items = response.get("value", [])
    if not items:
        return "No files found."
    output = []
    for item in items:
        name = item.get("name", "")
        modified = item.get("lastModifiedDateTime", "")[:10]
        size = item.get("size", 0)
        size_str = f"{size // 1024}KB" if size > 1024 else f"{size}B"
        output.append(f"📄 {name} | {size_str} | Modified: {modified}")
    audit("INFO", "onedrive-agent", f"Listed {len(items)} files from {folder}")
    return "\n".join(output)

def save_file(filename, content, folder="ClawBot"):
    token = get_graph_token()
    if not token:
        return "Could not authenticate with Microsoft."
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "text/plain"
    }
    url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/drive/root:/{folder}/{filename}:/content"
    response = requests.put(url, headers=headers, data=content.encode("utf-8"))
    if response.status_code in [200, 201]:
        audit("SUCCESS", "onedrive-agent", f"File saved: {folder}/{filename}")
        return f"✅ File saved to OneDrive: {folder}/{filename}"
    audit("ERROR", "onedrive-agent", f"Failed to save file: {response.status_code}")
    return f"Failed to save file: {response.status_code}"

def search_files(query):
    token = get_graph_token()
    if not token:
        return "Could not authenticate with Microsoft."
    headers = {"Authorization": "Bearer " + token}
    url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/drive/root/search(q='{query}')?$select=name,size,lastModifiedDateTime,webUrl&$top=5"
    response = requests.get(url, headers=headers).json()
    items = response.get("value", [])
    if not items:
        return f"No files found matching '{query}'."
    output = []
    for item in items:
        name = item.get("name", "")
        modified = item.get("lastModifiedDateTime", "")[:10]
        url_link = item.get("webUrl", "")
        output.append(f"📄 {name} | Modified: {modified}\n🔗 {url_link}")
    audit("INFO", "onedrive-agent", f"Search for '{query}' returned {len(items)} results")
    return "\n---\n".join(output)

def save_binary_file(filename, file_bytes, folder="Meeting Notes"):
    """Upload binary file (e.g. .docx) to OneDrive. Returns (web_url, error)."""
    token = get_graph_token()
    if not token:
        return None, "Could not authenticate with Microsoft."
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
    url = f"https://graph.microsoft.com/v1.0/users/{MS_USER_EMAIL}/drive/root:/{folder}/{filename}:/content"
    response = requests.put(url, headers=headers, data=file_bytes)
    if response.status_code in [200, 201]:
        item = response.json()
        web_url = item.get("webUrl", f"OneDrive:/{folder}/{filename}")
        audit("SUCCESS", "onedrive-agent", f"Uploaded: {folder}/{filename}")
        return web_url, None
    audit("ERROR", "onedrive-agent", f"Upload failed: {response.status_code} {response.text[:200]}")
    return None, f"Failed: {response.status_code} {response.text[:100]}"

def save_daily_summary():
    from pathlib import Path
    today = datetime.now().strftime("%Y-%m-%d")
    daily_path = Path(f"/root/.openclaw/workspace-hatfield/memory/{today}.md")
    if not daily_path.exists():
        return "No daily log found to save."
    content = daily_path.read_text(encoding="utf-8")
    filename = f"ClawBot-Daily-{today}.md"
    return save_file(filename, content, folder="ClawBot/Daily Logs")

if __name__ == "__main__":
    print("Testing OneDrive connection...")
    print(list_files())
    print("\nSaving test file...")
    print(save_file("test.txt", "ClawBot OneDrive integration test - " + datetime.now().strftime("%Y-%m-%d %H:%M")))
