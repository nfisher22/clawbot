import os
import time
import requests
import subprocess
from datetime import datetime, timezone
from dotenv import load_dotenv

from vault_secrets import get_secrets
get_secrets()
from dotenv import load_dotenv
load_dotenv("/opt/clawbot/app/.env")  # fallback

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
AUDIT_LOG = "/opt/clawbot/logs/audit.log"

SERVICES = [
    "clawbot",
    "email-drafter",
    "priority-notifier"
]

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass
    print(line.strip())

def check_service(name):
    result = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == "active"

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    r = requests.post(url, json=payload)
    return r.status_code == 200

def restart_service(name):
    result = subprocess.run(
        ["systemctl", "restart", name],
        capture_output=True, text=True
    )
    return result.returncode == 0

def main():
    audit("INFO", "heartbeat", "Heartbeat monitor started")
    send_telegram("💚 *ClawBot Heartbeat Monitor Started*\nWatching: " + ", ".join(SERVICES))
    
    down_counts = {s: 0 for s in SERVICES}
    
    while True:
        try:
            for service in SERVICES:
                is_up = check_service(service)
                if is_up:
                    if down_counts[service] > 0:
                        audit("INFO", "heartbeat", f"{service} recovered")
                        send_telegram(f"💚 *RECOVERED*: `{service}` is back online")
                    down_counts[service] = 0
                else:
                    down_counts[service] += 1
                    audit("ERROR", "heartbeat", f"{service} is DOWN (count: {down_counts[service]})")
                    
                    if down_counts[service] == 1:
                        audit("INFO", "heartbeat", f"Attempting to restart {service}")
                        restarted = restart_service(service)
                        if restarted:
                            audit("SUCCESS", "heartbeat", f"{service} restarted successfully")
                            send_telegram(f"🟡 *AUTO-RESTARTED*: `{service}` was down — restarted successfully")
                        else:
                            audit("ERROR", "heartbeat", f"Failed to restart {service}")
                            send_telegram(f"🔴 *SERVICE DOWN*: `{service}` is down and could not be restarted. Manual intervention needed.")

        except Exception as e:
            audit("ERROR", "heartbeat", f"Exception: {str(e)}")
        
        time.sleep(300)

if __name__ == "__main__":
    main()
