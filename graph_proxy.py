import os, requests, subprocess
from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

EST = ZoneInfo('America/New_York')

load_dotenv('/root/.env')

app = Flask(__name__)
# Restrict CORS to the local dashboard origin only; update PROXY_ALLOWED_ORIGIN in .env if needed
_ALLOWED_ORIGIN = os.getenv('PROXY_ALLOWED_ORIGIN', 'http://localhost:3000')
CORS(app, origins=[_ALLOWED_ORIGIN])

TENANT   = os.getenv('AZURE_TENANT_ID')
CLIENT   = os.getenv('AZURE_CLIENT_ID')
SECRET   = os.getenv('AZURE_CLIENT_SECRET')
EMAIL    = os.getenv('MS_EMAIL', 'nfisher@peak10group.com')
ANT_KEY  = os.getenv('ANTHROPIC_API_KEY')
TRACY    = 'tracy@peak10group.com'

# Internal API key to protect proxy endpoints — set PROXY_API_KEY in Vault / .env
_PROXY_API_KEY = os.getenv('PROXY_API_KEY', '')

def _require_auth():
    """Abort with 401 if the request does not carry the correct bearer token."""
    if not _PROXY_API_KEY:
        return  # key not configured — proxy operates unprotected (dev mode)
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer ') or auth[7:] != _PROXY_API_KEY:
        abort(401)

def get_token():
    r = requests.post(
        f'https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token',
        data={
            'grant_type':    'client_credentials',
            'client_id':     CLIENT,
            'client_secret': SECRET,
            'scope':         'https://graph.microsoft.com/.default'
        },
        timeout=10
    )
    r.raise_for_status()
    return r.json()['access_token']

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'graph-proxy'})

@app.route('/calendar')
def calendar():
    _require_auth()
    try:
        token = get_token()
        now   = datetime.now(EST)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end   = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        r = requests.get(
            f'https://graph.microsoft.com/v1.0/users/{EMAIL}/calendarView',
            headers={
                'Authorization': f'Bearer {token}',
                'Prefer':        'outlook.timezone="Eastern Standard Time"'
            },
            params={
                'startDateTime': start,
                'endDateTime':   end,
                '$select':       'subject,start,end,location,bodyPreview,attendees',
                '$orderby':      'start/dateTime',
                '$top':          '20'
            },
            timeout=10
        )
        r.raise_for_status()
        events = []
        for e in r.json().get('value', []):
            t = e.get('start', {}).get('dateTime', '')
            try:
                t_clean = t.split('.')[0]  # strip fractional seconds (Graph returns 7-digit .0000000)
                dt = datetime.fromisoformat(t_clean)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=EST)
                else:
                    dt = dt.astimezone(EST)
                time_str = dt.strftime('%-I:%M %p')
            except Exception:
                time_str = t[:16]
            events.append({
                'time':     time_str,
                'title':    e.get('subject', ''),
                'location': e.get('location', {}).get('displayName', ''),
                'preview':  e.get('bodyPreview', '')[:120]
            })
        return jsonify({'calendar': events})
    except Exception as ex:
        return jsonify({'error': str(ex), 'calendar': []}), 200

@app.route('/email')
def email():
    _require_auth()
    try:
        token = get_token()
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        r = requests.get(
            f'https://graph.microsoft.com/v1.0/users/{EMAIL}/messages',
            headers={'Authorization': f'Bearer {token}'},
            params={
                '$filter':  f"receivedDateTime ge {since}",
                '$select':  'subject,from,receivedDateTime,bodyPreview,isRead',
                '$orderby': 'receivedDateTime desc',
                '$top':     '15'
            },
            timeout=10
        )
        r.raise_for_status()
        emails = []
        for m in r.json().get('value', []):
            emails.append({
                'from':    m.get('from', {}).get('emailAddress', {}).get('name', ''),
                'subject': m.get('subject', ''),
                'snippet': m.get('bodyPreview', '')[:150],
                'isRead':  m.get('isRead', True)
            })
        return jsonify({'emails': emails})
    except Exception as ex:
        return jsonify({'error': str(ex), 'emails': []}), 200

@app.route('/usage')
def usage():
    _require_auth()
    try:
        if not ANT_KEY:
            return jsonify({'error': 'ANTHROPIC_API_KEY not configured'}), 200
        # Monthly window
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        r = requests.get(
            'https://api.anthropic.com/v1/usage',
            headers={
                'x-api-key':           ANT_KEY,
                'anthropic-version':   '2023-06-01'
            },
            params={'start_time': month_start},
            timeout=10
        )
        r.raise_for_status()
        return jsonify(r.json())
    except requests.HTTPError as ex:
        status = ex.response.status_code if ex.response is not None else 0
        body = ''
        try:
            body = ex.response.json().get('error', {}).get('message', '')
        except Exception:
            pass
        return jsonify({'error': f'HTTP {status}: {body}'}), 200
    except Exception as ex:
        return jsonify({'error': str(ex)}), 200

@app.route('/history')
def history():
    _require_auth()
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'clawbot', '--no-pager', '-n', '300', '--output=short-iso'],
            capture_output=True, text=True, timeout=15
        )
        entries = []
        for line in result.stdout.splitlines():
            if not line or 'clawbot' not in line:
                continue
            # Extract message after ']:' marker
            try:
                idx = line.index(']: ') + 3
                msg = line[idx:].strip()
            except ValueError:
                continue
            if len(msg) < 4:
                continue
            # Keep command lines and meaningful bot events
            if 'site-packages' in msg or msg.startswith('File "'):
                continue
            if any(kw in msg.lower() for kw in [
                'command', 'received', 'sent', 'brief', 'status',
                'processed', 'trigger', 'user', 'started', 'dispatching',
                'handling', 'bot', 'message'
            ]) or (msg.startswith('/') and len(msg.split()) <= 4):
                try:
                    ts_raw = line.split()[0]
                    dt = datetime.fromisoformat(ts_raw.replace('+0000', '+00:00'))
                    ts = dt.strftime('%-m/%-d %-I:%M %p')
                except Exception:
                    ts = ''
                entries.append({'time': ts, 'message': msg[:100]})
        return jsonify({'history': entries[-10:]})
    except Exception as ex:
        return jsonify({'error': str(ex), 'history': []}), 200

@app.route('/tracy')
def tracy():
    _require_auth()
    try:
        token = get_token()
        since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        r = requests.get(
            f'https://graph.microsoft.com/v1.0/users/{EMAIL}/mailFolders/SentItems/messages',
            headers={'Authorization': f'Bearer {token}'},
            params={
                '$filter':  f"sentDateTime ge {since}",
                '$select':  'subject,sentDateTime,bodyPreview,toRecipients',
                '$orderby': 'sentDateTime desc',
                '$top':     '50'
            },
            timeout=10
        )
        r.raise_for_status()
        task_kw = [
            'please', 'can you', 'could you', 'would you', 'follow up',
            'schedule', 'reach out', 'book', 'arrange', 'confirm',
            'remind', 'draft', 'set up', 'coordinate', 'handle',
            'take care', 'make sure', 'need you', 'get me', 'send'
        ]
        tasks = []
        for m in r.json().get('value', []):
            recipients = [
                x.get('emailAddress', {}).get('address', '').lower()
                for x in m.get('toRecipients', [])
            ]
            if TRACY not in recipients:
                continue
            combined = (m.get('subject', '') + ' ' + m.get('bodyPreview', '')).lower()
            if not any(kw in combined for kw in task_kw):
                continue
            sent_dt = m.get('sentDateTime', '')
            try:
                dt = datetime.fromisoformat(sent_dt.replace('Z', '+00:00'))
                date_str = dt.strftime('%b %-d')
            except Exception:
                date_str = sent_dt[:10]
            tasks.append({
                'subject': m.get('subject', ''),
                'snippet': m.get('bodyPreview', '')[:120],
                'date':    date_str
            })
        return jsonify({'tasks': tasks[:10]})
    except Exception as ex:
        return jsonify({'error': str(ex), 'tasks': []}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8001)
