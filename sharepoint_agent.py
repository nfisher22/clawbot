import os
import requests
import msal
from datetime import datetime, timezone

from vault_secrets import get_secrets
get_secrets()

AZURE_CLIENT_ID     = os.getenv("AZURE_CLIENT_ID")
AZURE_TENANT_ID     = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
MS_USER_EMAIL       = os.getenv("MS_USER_EMAIL", "nfisher@peak10group.com")
AUDIT_LOG           = "/opt/clawbot/logs/audit.log"

GRAPH = "https://graph.microsoft.com/v1.0"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _audit(level, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(f"{ts} | {level} | sharepoint-agent | {message}\n")
    except Exception:
        pass

def _get_token():
    app = msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{AZURE_TENANT_ID}",
        client_credential=AZURE_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    return result.get("access_token")

def _headers():
    token = _get_token()
    if not token:
        raise RuntimeError("SharePoint: could not acquire Graph API token.")
    return {"Authorization": "Bearer " + token}

def _fmt_size(size):
    if size is None:
        return "—"
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f}MB"
    if size >= 1_024:
        return f"{size // 1_024}KB"
    return f"{size}B"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_sites(limit=20):
    """Return a formatted list of all accessible SharePoint sites."""
    try:
        h = _headers()
        resp = requests.get(
            f"{GRAPH}/sites?search=*&$select=id,displayName,webUrl&$top={limit}",
            headers=h,
        ).json()
        sites = resp.get("value", [])
        if not sites:
            return "No SharePoint sites found."
        lines = [f"📂 Found {len(sites)} SharePoint site(s):\n"]
        for s in sites:
            lines.append(f"  🏢 {s.get('displayName','(unnamed)')}")
            lines.append(f"     {s.get('webUrl','')}")
            lines.append(f"     ID: {s.get('id','')}")
        _audit("INFO", f"list_sites returned {len(sites)} sites")
        return "\n".join(lines)
    except Exception as e:
        _audit("ERROR", f"list_sites failed: {e}")
        return f"Error listing SharePoint sites: {e}"


def list_folders(site_id, folder_path=None, limit=50):
    """List folders (and files) inside a SharePoint document library.

    Args:
        site_id:     Full Graph site ID (e.g. 'peak10groupcom.sharepoint.com,xxx,yyy')
                     OR a short keyword like 'Peak10' that will be resolved automatically.
        folder_path: Optional sub-path within the drive root (e.g. 'General/Reports').
                     Pass None to list the drive root.
        limit:       Max items to return.
    """
    try:
        h = _headers()
        sid = _resolve_site(site_id, h)
        if sid is None:
            return f"Could not find SharePoint site matching '{site_id}'."

        if folder_path:
            url = f"{GRAPH}/sites/{sid}/drive/root:/{folder_path}:/children?$top={limit}&$select=name,size,lastModifiedDateTime,webUrl,folder"
        else:
            url = f"{GRAPH}/sites/{sid}/drive/root/children?$top={limit}&$select=name,size,lastModifiedDateTime,webUrl,folder"

        resp = requests.get(url, headers=h).json()
        if "error" in resp:
            return f"Graph API error: {resp['error'].get('message', resp['error'])}"

        items = resp.get("value", [])
        if not items:
            return "No items found."

        lines = [f"📂 {'Root' if not folder_path else folder_path} — {len(items)} item(s):\n"]
        for item in sorted(items, key=lambda x: (0 if "folder" in x else 1, x.get("name",""))):
            is_folder = "folder" in item
            icon = "📁" if is_folder else "📄"
            name = item.get("name", "")
            modified = item.get("lastModifiedDateTime", "")[:10]
            size = "" if is_folder else f" | {_fmt_size(item.get('size'))}"
            lines.append(f"  {icon} {name}{size} | {modified}")

        _audit("INFO", f"list_folders site={sid} path={folder_path} returned {len(items)} items")
        return "\n".join(lines)
    except Exception as e:
        _audit("ERROR", f"list_folders failed: {e}")
        return f"Error listing SharePoint folder: {e}"


def search_files(query, site_id=None, limit=10):
    """Search for files across all SharePoint sites, or within a specific site.

    Args:
        query:   Search term.
        site_id: Optional site ID or keyword to scope the search.
        limit:   Max results.
    """
    try:
        h = _headers()
        if site_id:
            sid = _resolve_site(site_id, h)
            if sid is None:
                return f"Could not find SharePoint site matching '{site_id}'."
            url = f"{GRAPH}/sites/{sid}/drive/root/search(q='{query}')?$top={limit}&$select=name,size,lastModifiedDateTime,webUrl"
        else:
            url = f"{GRAPH}/search/query"
            payload = {
                "requests": [{
                    "entityTypes": ["driveItem"],
                    "query": {"queryString": query},
                    "from": 0,
                    "size": limit,
                    "fields": ["name", "lastModifiedDateTime", "webUrl", "size"]
                }]
            }
            resp = requests.post(url, headers={**h, "Content-Type": "application/json"},
                                 json=payload).json()
            hits = (resp.get("value", [{}])[0]
                       .get("hitsContainers", [{}])[0]
                       .get("hits", []))
            if not hits:
                return f"No files found matching '{query}'."
            lines = [f"🔍 Search results for '{query}':\n"]
            for hit in hits:
                r = hit.get("resource", {})
                lines.append(f"  📄 {r.get('name','')}")
                lines.append(f"     Modified: {r.get('lastModifiedDateTime','')[:10]}")
                lines.append(f"     🔗 {r.get('webUrl','')}\n")
            _audit("INFO", f"search_files '{query}' (global) returned {len(hits)} hits")
            return "\n".join(lines)

        # Site-scoped search
        resp = requests.get(url, headers=h).json()
        items = resp.get("value", [])
        if not items:
            return f"No files found matching '{query}'."
        lines = [f"🔍 Search results for '{query}':\n"]
        for item in items:
            lines.append(f"  📄 {item.get('name','')}")
            lines.append(f"     Modified: {item.get('lastModifiedDateTime','')[:10]}")
            lines.append(f"     Size: {_fmt_size(item.get('size'))}")
            lines.append(f"     🔗 {item.get('webUrl','')}\n")
        _audit("INFO", f"search_files '{query}' site={site_id} returned {len(items)} results")
        return "\n".join(lines)
    except Exception as e:
        _audit("ERROR", f"search_files failed: {e}")
        return f"Error searching SharePoint: {e}"


def read_file(site_id, file_path, max_chars=3000):
    """Download and return the text content of a file from SharePoint.

    Args:
        site_id:   Site ID or keyword.
        file_path: Path within drive root (e.g. 'General/Notes.txt').
        max_chars: Truncate response to this many characters.
    """
    try:
        h = _headers()
        sid = _resolve_site(site_id, h)
        if sid is None:
            return f"Could not find SharePoint site matching '{site_id}'."

        url = f"{GRAPH}/sites/{sid}/drive/root:/{file_path}:/content"
        resp = requests.get(url, headers=h, allow_redirects=True)
        if resp.status_code != 200:
            return f"Could not download file (HTTP {resp.status_code})."
        text = resp.content.decode("utf-8", errors="replace")
        _audit("INFO", f"read_file site={sid} path={file_path}")
        if len(text) > max_chars:
            return text[:max_chars] + f"\n\n[...truncated at {max_chars} chars]"
        return text
    except Exception as e:
        _audit("ERROR", f"read_file failed: {e}")
        return f"Error reading SharePoint file: {e}"


def save_file(site_id, folder_path, filename, content):
    """Upload/overwrite a text file to a SharePoint document library.

    Args:
        site_id:     Site ID or keyword.
        folder_path: Folder within drive root (e.g. 'General/Reports').
        filename:    File name (e.g. 'summary.txt').
        content:     Text content to write.
    """
    try:
        h = {**_headers(), "Content-Type": "text/plain"}
        sid = _resolve_site(site_id, h)
        if sid is None:
            return f"Could not find SharePoint site matching '{site_id}'."

        url = f"{GRAPH}/sites/{sid}/drive/root:/{folder_path}/{filename}:/content"
        resp = requests.put(url, headers=h, data=content.encode("utf-8"))
        if resp.status_code in [200, 201]:
            _audit("SUCCESS", f"save_file site={sid} {folder_path}/{filename}")
            return f"✅ File saved to SharePoint: {folder_path}/{filename}"
        _audit("ERROR", f"save_file failed: {resp.status_code} {resp.text[:200]}")
        return f"Failed to save file (HTTP {resp.status_code})."
    except Exception as e:
        _audit("ERROR", f"save_file failed: {e}")
        return f"Error saving SharePoint file: {e}"


# ---------------------------------------------------------------------------
# Internal: site ID resolver
# ---------------------------------------------------------------------------

# Short aliases for the two primary team sites
SITE_ALIASES = {
    "peak10":         "Peak 10 Main",
    "peak 10":        "Peak 10 Main",
    "peak 10 main":   "Peak 10 Main",
    "main":           "Peak 10 Main",
    "dayton":         "P10 Mgmt Dayton",
    "p10 dayton":     "P10 Mgmt Dayton",
    "p10 mgmt dayton":"P10 Mgmt Dayton",
    "mgmt dayton":    "P10 Mgmt Dayton",
    "mgmt":           "P10 Mgmt Dayton",
}

def _resolve_site(site_id_or_name, headers):
    """Accept a full Graph site ID, a short alias, or a display-name keyword.
    Returns the full site ID string, or None if not found.
    """
    # Already looks like a full ID (contains commas)
    if "," in str(site_id_or_name):
        return site_id_or_name

    # Normalise and check aliases first
    name_lower = str(site_id_or_name).strip().lower()
    display_name = SITE_ALIASES.get(name_lower, site_id_or_name)

    # Search Graph API by (possibly aliased) display name
    resp = requests.get(
        f"{GRAPH}/sites?search={display_name}&$select=id,displayName&$top=5",
        headers=headers,
    ).json()
    sites = resp.get("value", [])
    if not sites:
        return None
    # Prefer exact display name match, then fall back to first result
    target = display_name.lower()
    for s in sites:
        if s.get("displayName", "").lower() == target:
            return s["id"]
    return sites[0]["id"]


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== SharePoint Sites ===")
    print(list_sites())
    print("\n=== Root folders — Peak 10 Main ===")
    print(list_folders("Peak10"))
